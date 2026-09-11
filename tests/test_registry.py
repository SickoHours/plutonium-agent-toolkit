"""``registry add|list|search|show`` and ``module fetch``: registries as files, snapshots by exact commit.

No network: ``registry.fetch_bytes`` is patched to serve bytes from a dict keyed by URL. The
snapshot the fake serves is a real tar.gz built in the test, so the archive safety checks and
the extraction run for real.
"""
import contextlib
import hashlib
import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from plutonium_agent_toolkit.cli import entry
from plutonium_agent_toolkit.core.errors import Failure
from plutonium_agent_toolkit.dev import registry

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "b" * 40
OTHER = "c" * 40


def invoke(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = entry(argv)
    return code, json.loads(buf.getvalue())


def tarball(files: dict, root="owner-repo-" + COMMIT[:7]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        info = tarfile.TarInfo(root + "/"); info.type = tarfile.DIRTYPE; info.mode = 0o755
        t.addfile(info)
        for rel, data in files.items():
            body = data if isinstance(data, bytes) else data.encode()
            info = tarfile.TarInfo(f"{root}/{rel}"); info.size = len(body); info.mode = 0o644
            t.addfile(info, io.BytesIO(body))
    return buf.getvalue()


def entry_row(name="someone/round_announcer", commit=COMMIT, **over):
    row = {"name": name, "kind": "module", "repository": "https://github.com/someone/mods", "path": "round-announcer",
           "listed": {"commit": commit, "at": "2026-09-11"}, "distribution": "source",
           "declaration": {"id": "round_announcer", "version": "0.1.0", "title": "Round announcer", "category": "scripts",
                           "kind": "script", "tags": ["example"], "bases": ["stock"], "maps": ["*"]},
           "verification": {"snapshot_status": "unverified"}}
    row.update(over)
    return row


def registry_file(entries=None, name="test-registry"):
    return {"schema": 1, "name": name, "description": "fixture", "entries": entries if entries is not None else [entry_row()]}


class RegistryFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.saved = os.environ.get("PAT_HOME")
        os.environ["PAT_HOME"] = str(self.root / "home")
        self.addCleanup(self._restore)
        self.served: dict[str, bytes] = {}
        self.requests: list[str] = []
        patcher = mock.patch.object(registry, "fetch_bytes", side_effect=self._serve)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.n = 0

    def _restore(self):
        if self.saved is None:
            os.environ.pop("PAT_HOME", None)
        else:
            os.environ["PAT_HOME"] = self.saved

    def _serve(self, url, limit, timeout=60):
        self.requests.append(url)
        if url not in self.served:
            raise Failure("input_missing", f"HTTP 404 for {url}")
        data = self.served[url]
        if len(data) > limit:
            raise Failure("input_limit", f"Download exceeded {limit} bytes")
        return data

    def out(self):
        self.n += 1
        return str(self.root / f"job-{self.n:03d}")

    def write_registry(self, data, name="registry.json"):
        p = self.root / name
        p.write_text(json.dumps(data, indent=2))
        return p

    def module_snapshot(self, declaration_extra=None, path="round-announcer"):
        decl = {"schema": 1, "id": "round_announcer", "version": "0.1.0", "title": "Round announcer", "category": "scripts",
                "kind": "script", "tags": ["example"], "recipe": "project.json", "bases": ["stock"], "maps": ["*"],
                "source": {"repository": "https://github.com/someone/mods", "commit": COMMIT}}
        decl.update(declaration_extra or {})
        recipe = {"schema": 1, "game": "t6", "mode": "zm", "name": "round_announcer",
                  "scripts": [{"source": "scripts/round_announcer.gsc", "target": "scripts/zm/round_announcer.gsc", "instance": "server"}],
                  "assets": [], "loads": []}
        return tarball({f"{path}/module.json": json.dumps(decl), f"{path}/project.json": json.dumps(recipe),
                        f"{path}/scripts/round_announcer.gsc": "main()\n{\n}\n", "README.md": "# mods\n"})


class RegistryFileTests(RegistryFixture):
    def test_add_list_search_show_from_a_local_file(self):
        code, row = invoke(["registry", "add", str(self.write_registry(registry_file()))])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["entries"], 1)
        self.assertEqual(row["result"]["name"], "test-registry")
        code, row = invoke(["registry", "list"])
        self.assertEqual(code, 0, row)
        self.assertEqual([r["name"] for r in row["result"]["registries"]], ["test-registry"])
        code, row = invoke(["registry", "search", "round"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["count"], 1)
        hit = row["result"]["hits"][0]
        self.assertEqual(hit["name"], "someone/round_announcer")
        self.assertEqual(hit["fetch"][3], f"someone/round_announcer@{COMMIT}")
        for filters, expected in ((["--category", "scripts"], 1), (["--category", "weapons"], 0), (["--tag", "example"], 1),
                                  (["--base", "stock"], 1), (["--base", "b2"], 0), (["--map", "zm_transit"], 1), (["--kind", "script"], 1),
                                  (["--entry-kind", "composition"], 0), (["nothing", "matches"], 0)):
            code, row = invoke(["registry", "search", *filters])
            self.assertEqual(row["result"]["count"], expected, filters)
        code, row = invoke(["registry", "show", "someone/round_announcer"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["count"], 1)
        self.assertIn("codeload.github.com/someone/mods/tar.gz/" + COMMIT, row["result"]["listings"][0]["snapshot_url"])
        code, row = invoke(["registry", "show", "nobody/nothing"])
        self.assertEqual(row["error_code"], "input_missing")
        code, row = invoke(["registry", "show", "Bad Name"])
        self.assertEqual(row["error_code"], "input_invalid")

    def test_add_from_https_and_re_add_replaces(self):
        data = registry_file()
        self.served["https://example.invalid/registry.json"] = json.dumps(data).encode()
        code, row = invoke(["registry", "add", "https://example.invalid/registry.json"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["source"]["kind"], "url")
        self.assertEqual(row["result"]["sha256"], hashlib.sha256(json.dumps(data).encode()).hexdigest())
        data["entries"].append(entry_row(name="someone/other", declaration={"id": "other", "version": "1", "category": "weapons", "kind": "melee", "bases": ["b2"], "maps": ["zm_factory"]}))
        self.served["https://example.invalid/registry.json"] = json.dumps(data).encode()
        code, row = invoke(["registry", "add", "https://example.invalid/registry.json"])
        self.assertEqual(row["result"]["entries"], 2)
        code, row = invoke(["registry", "list"])
        self.assertEqual(len(row["result"]["registries"]), 1, "same name replaces, never duplicates")
        code, row = invoke(["registry", "search", "--category", "weapons", "--kind", "melee"])
        self.assertEqual(row["result"]["hits"][0]["name"], "someone/other")
        code, row = invoke(["registry", "add", "http://insecure.invalid/registry.json"])
        self.assertEqual(row["error_code"], "input_missing", "not https: treated as a local path that does not exist")

    def test_registry_validation(self):
        bad = [
            ({**registry_file(), "schema": 2}, "schema"),
            ({**registry_file(), "name": "Bad Name"}, "name"),
            (registry_file([entry_row(name="Some/One")]), "name"),
            (registry_file([entry_row(name="plutonium/thing")]), "reserved"),
            (registry_file([entry_row(repository="https://gitlab.com/someone/mods")]), "github"),
            (registry_file([entry_row(repository="https://github.com/other/mods")]), "owned"),
            (registry_file([entry_row(listed={"commit": "short"})]), "commit"),
            (registry_file([entry_row(kind="plugin")]), "kind"),
            (registry_file([entry_row(distribution="binary")]), "distribution"),
            (registry_file([entry_row(path="../escape")]), "path"),
            (registry_file([entry_row(), entry_row()]), "twice"),
            (registry_file([entry_row(declaration={"bogus": 1})]), "declaration"),
        ]
        for data, word in bad:
            code, row = invoke(["registry", "add", str(self.write_registry(data))])
            self.assertEqual(code, 1, data)
            self.assertEqual(row["error_code"], "input_invalid", data)
            self.assertIn(word, row["message"].lower(), (word, row["message"]))
        code, row = invoke(["registry", "add", str(self.root / "missing.json")])
        self.assertEqual(row["error_code"], "input_missing")


class FetchTests(RegistryFixture):
    def test_fetch_by_name_through_a_registry(self):
        invoke(["registry", "add", str(self.write_registry(registry_file()))])
        self.served[f"https://codeload.github.com/someone/mods/tar.gz/{COMMIT}"] = self.module_snapshot()
        code, row = invoke(["module", "fetch", f"someone/round_announcer@{COMMIT}", "--output", self.out()])
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertEqual(result["kind"], "module")
        self.assertEqual(result["facts"]["id"], "round_announcer")
        self.assertEqual(result["facts"]["payload"], "recipe")
        self.assertEqual(result["path"], "round-announcer")
        module_dir = Path(result["module_dir"])
        self.assertTrue((module_dir / "module.json").is_file())
        self.assertTrue((module_dir / "scripts" / "round_announcer.gsc").is_file())
        record = json.loads((Path(result["output"]) / "fetch.json").read_text())
        self.assertEqual(record["commit"], COMMIT)
        self.assertEqual(record["registry"], "test-registry")
        self.assertRegex(record["archive_sha256"], r"^[0-9a-f]{64}$")
        receipt = json.loads((Path(result["output"]) / "receipt.json").read_text())
        self.assertEqual(receipt["status"], "succeeded")
        self.assertIn("snapshot/" + COMMIT + ".tar.gz", receipt["outputs"])
        self.assertEqual(result["composition_member"]["name"], "someone/round_announcer")
        # The fetched directory composes: a composition naming it as a reference member plans.
        pack = self.root / "packs" / "stock_fetched_test"
        pack.mkdir(parents=True)
        rel = os.path.relpath(module_dir, pack).replace(os.sep, "/")
        (pack / "composition.json").write_text(json.dumps({"schema": 1, "name": "stock_fetched_test", "base": "stock", "map": "zm_transit",
                                                            "modules": [{"name": "someone/round_announcer", "commit": COMMIT, "path": rel}]}))
        fakes = ROOT / "tests" / "fakes"
        with mock.patch.dict(os.environ, {"PAT_BACKEND_GSC": str(fakes / "fake_gsc.py"), "PAT_BACKEND_LINKER": str(fakes / "fake_linker.py"),
                                          "PAT_BACKEND_UNLINKER": str(fakes / "fake_unlinker.py")}):
            code, row = invoke(["module", "plan", str(pack / "composition.json"), "--output", self.out()])
        self.assertEqual(code, 0, row)
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        self.assertEqual(plan["modules"][0]["reference"], {"name": "someone/round_announcer", "commit": COMMIT})

    def test_fetch_by_url_without_a_registry_and_path_override(self):
        self.served[f"https://codeload.github.com/someone/mods/tar.gz/{COMMIT}"] = self.module_snapshot(path="mods/announcer")
        code, row = invoke(["module", "fetch", f"https://github.com/someone/mods@{COMMIT}", "--path", "mods/announcer", "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertIsNone(row["result"]["name"])
        self.assertNotIn("name", row["result"]["composition_member"])
        code, row = invoke(["module", "fetch", f"https://github.com/someone/mods@{COMMIT}", "--output", self.out()])
        self.assertEqual(row["error_code"], "input_missing", "root has no module.json")

    def test_fetch_refusals(self):
        invoke(["registry", "add", str(self.write_registry(registry_file()))])
        for ref, code_expected in ((f"someone/round_announcer@{OTHER}", "input_invalid"), ("someone/round_announcer", "input_invalid"),
                                   ("someone/round_announcer@main", "input_invalid"), (f"nobody/nothing@{COMMIT}", "input_missing"),
                                   (f"https://gitlab.com/x/y@{COMMIT}", "input_invalid")):
            code, row = invoke(["module", "fetch", ref, "--output", self.out()])
            self.assertEqual(code, 1, ref)
            self.assertEqual(row["error_code"], code_expected, (ref, row["message"]))
        self.assertEqual(self.requests, [], "no download before the reference resolved")
        # 404 from the host
        code, row = invoke(["module", "fetch", f"someone/round_announcer@{COMMIT}", "--output", self.out()])
        self.assertEqual(row["error_code"], "input_missing")
        self.assertIn("404", row["message"])
        # declaration mismatch: the snapshot's declaration names another commit
        self.served[f"https://codeload.github.com/someone/mods/tar.gz/{COMMIT}"] = self.module_snapshot({"source": {"repository": "https://github.com/someone/mods", "commit": OTHER}})
        code, row = invoke(["module", "fetch", f"someone/round_announcer@{COMMIT}", "--output", self.out()])
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("declaration-mismatch", row["message"])
        # id mismatch between the registry name and the declaration
        self.served[f"https://codeload.github.com/someone/mods/tar.gz/{COMMIT}"] = self.module_snapshot({"id": "something_else"})
        code, row = invoke(["module", "fetch", f"someone/round_announcer@{COMMIT}", "--output", self.out()])
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("declaration-mismatch", row["message"])
        # a snapshot with a traversal entry is refused by the archive safety checks
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            info = tarfile.TarInfo("owner-repo-x/../evil"); info.size = 1
            t.addfile(info, io.BytesIO(b"x"))
        self.served[f"https://codeload.github.com/someone/mods/tar.gz/{COMMIT}"] = buf.getvalue()
        code, row = invoke(["module", "fetch", f"someone/round_announcer@{COMMIT}", "--output", self.out()])
        self.assertEqual(code, 1)
        self.assertIn(row["error_code"], ("input_invalid", "input_limit"))

    def test_fetched_private_seed_reports_the_missing_package(self):
        decl = {"schema": 1, "id": "penetrator", "version": "0.1.0", "category": "weapons", "kind": "melee", "seed": "seed.json",
                "bases": ["b2"], "maps": ["zm_factory"], "distribution": "private"}
        manifest = {"schema": 1, "package": "mod.ff", "files": {"mod.ff": "0" * 64}, "roots": ["weapon,halo_penetrator_zm"],
                    "embedded": ["weapon,halo_penetrator_zm"], "referenced": []}
        self.served[f"https://codeload.github.com/someone/mods/tar.gz/{COMMIT}"] = tarball({"module.json": json.dumps(decl), "seed.json": json.dumps(manifest)})
        code, row = invoke(["module", "fetch", f"https://github.com/someone/mods@{COMMIT}", "--output", self.out()])
        self.assertEqual(code, 0, row)
        facts = row["result"]["facts"]
        self.assertEqual(facts["payload"], "seed")
        self.assertEqual(facts["distribution"], "private")
        self.assertTrue(facts["seed_manifest_present"])
        self.assertFalse(facts["seed_package_present"])


class ManifestTests(unittest.TestCase):
    def test_routes_are_registered_with_honest_effects(self):
        code, row = invoke(["manifest"])
        by_id = {r["id"]: r for r in row["result"]["routes"]}
        self.assertEqual(by_id["module.fetch"]["effect"], "downloads-source")
        for rid in ("registry.list", "registry.search", "registry.show"):
            self.assertEqual(by_id[rid]["effect"], "inert", rid)
        self.assertEqual(by_id["registry.add"]["effect"], "writes-config")
        self.assertEqual(registry.snapshot_url("https://github.com/Some/Repo/", COMMIT), f"https://codeload.github.com/Some/Repo/tar.gz/{COMMIT}")


if __name__ == "__main__":
    unittest.main()
