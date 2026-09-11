"""``dev builtin`` and the registry that ships with the toolkit.

The built-in registry (``dev/builtin.json``) is always listed with origin ``builtin``; ``dev builtin``
fetches its entries into the toolkit home from one snapshot per repository and commit, with a
receipt per entry, and a rerun verifies. No network: ``registry.fetch_bytes`` is patched to serve a
tarball shaped like the toolkit repository at the pinned commit.
"""
import contextlib
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
from plutonium_agent_toolkit.dev import builtin, registry

ROOT = Path(__file__).resolve().parents[1]
FAKES = ROOT / "tests" / "fakes"


def invoke(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = entry(argv)
    return code, json.loads(buf.getvalue())


def repo_tarball(commit: str) -> bytes:
    """The toolkit repository at the pinned commit, as GitHub's codeload would serve it: the three
    example directories (copied from this checkout) plus a file outside them that must not be kept."""
    buf = io.BytesIO()
    root = "plutonium-agent-toolkit-" + commit[:7]
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        info = tarfile.TarInfo(root + "/"); info.type = tarfile.DIRTYPE; info.mode = 0o755
        t.addfile(info)
        for rel in ("README.md",):
            body = b"# toolkit\n"
            info = tarfile.TarInfo(f"{root}/{rel}"); info.size = len(body); info.mode = 0o644
            t.addfile(info, io.BytesIO(body))
        for example in ("hello-zm", "hello-zm-two", "hello-pack"):
            for p in sorted((ROOT / "examples" / example).rglob("*")):
                if p.is_file():
                    body = p.read_bytes()
                    info = tarfile.TarInfo(f"{root}/examples/{example}/{p.relative_to(ROOT / 'examples' / example).as_posix()}")
                    info.size = len(body); info.mode = 0o644
                    t.addfile(info, io.BytesIO(body))
    return buf.getvalue()


class BuiltinFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.saved = os.environ.get("PAT_HOME")
        os.environ["PAT_HOME"] = str(self.root / "home")
        self.addCleanup(self._restore)
        self.entries = registry.builtin_registry()["entries"]
        self.commit = self.entries[0]["listed"]["commit"]
        self.url = registry.snapshot_url(self.entries[0]["repository"], self.commit)
        self.served = {self.url: repo_tarball(self.commit)}
        self.requests = []
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
        return self.served[url]

    def out(self):
        self.n += 1
        return str(self.root / f"job-{self.n:03d}")


class BuiltinRegistryTests(BuiltinFixture):
    def test_shipped_registry_is_the_examples_registry_and_always_listed(self):
        shipped = json.loads(builtin.registry.BUILTIN_FILE.read_text(encoding="utf-8"))
        example = json.loads((ROOT / "examples" / "registry.json").read_text(encoding="utf-8"))
        self.assertEqual(shipped["entries"], example["entries"], "examples/registry.json lists the same entries as the shipped registry; keep them equal")
        self.assertEqual(shipped["name"], registry.BUILTIN_NAME)
        self.assertNotEqual(example["name"], registry.BUILTIN_NAME, "the example stays addable with registry add; only the shipped copy carries the reserved name")
        for e in shipped["entries"]:
            self.assertEqual(e["listed"]["commit"], self.commit, "one snapshot serves every built-in")
            self.assertTrue((ROOT / e["path"]).is_dir(), e["path"])
            declared = json.loads((ROOT / e["path"] / ("composition.json" if e["kind"] == "composition" else "module.json")).read_text())
            self.assertEqual(declared.get("id", declared.get("name")), e["declaration"]["id"], e["name"])
        code, row = invoke(["registry", "list"])
        self.assertEqual(code, 0, row)
        self.assertEqual([(r["name"], r["origin"]) for r in row["result"]["registries"]], [(registry.BUILTIN_NAME, "builtin")])
        code, row = invoke(["registry", "search", "--origin", "builtin"])
        self.assertEqual(row["result"]["count"], len(shipped["entries"]))
        self.assertTrue(all(h["origin"] == "builtin" and h["builtin_dir"] is None and h["fetch"][:3] == ["pat", "dev", "builtin"] for h in row["result"]["hits"]))
        code, row = invoke(["registry", "search", "--origin", "added"])
        self.assertEqual(row["result"]["count"], 0)
        code, row = invoke(["registry", "show", "sickohours/stock_hello_pack"])
        self.assertEqual(row["result"]["listings"][0]["origin"], "builtin")
        self.assertIsNone(row["result"]["listings"][0]["builtin_dir"])

    def test_the_built_in_name_is_reserved_for_registry_add(self):
        data = {"schema": 1, "name": registry.BUILTIN_NAME, "description": "impostor", "entries": []}
        path = self.root / "registry.json"
        path.write_text(json.dumps(data))
        code, row = invoke(["registry", "add", str(path)])
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("reserved", row["message"])
        data["name"] = "mine"
        path.write_text(json.dumps(data))
        code, row = invoke(["registry", "add", str(path)])
        self.assertEqual(code, 0, row)
        code, row = invoke(["registry", "list"])
        self.assertEqual([(r["name"], r["origin"]) for r in row["result"]["registries"]], [(registry.BUILTIN_NAME, "builtin"), ("mine", "added")])
        code, row = invoke(["registry", "search", "--origin", "nowhere"])
        self.assertEqual(code, 2)

    def test_an_added_registry_listing_a_built_in_is_one_hit_per_commit(self):
        shipped = registry.builtin_registry()
        same = dict(shipped["entries"][0])
        newer = json.loads(json.dumps(shipped["entries"][1]))
        newer["listed"] = {"commit": "f" * 40, "at": "2026-09-12"}
        path = self.root / "registry.json"
        path.write_text(json.dumps({"schema": 1, "name": "official", "description": "", "entries": [same, newer]}))
        code, row = invoke(["registry", "add", str(path)])
        self.assertEqual(code, 0, row)
        code, row = invoke(["registry", "search"])
        by = {}
        for h in row["result"]["hits"]:
            by.setdefault(h["name"], []).append(h)
        self.assertEqual(len(by[same["name"]]), 1, "same name and commit in two registries is one hit")
        self.assertEqual(by[same["name"]][0]["origin"], "builtin")
        self.assertEqual(by[same["name"]][0]["also_listed_by"], ["official"])
        self.assertEqual([(h["origin"], h["commit"][:1]) for h in by[newer["name"]]], [("builtin", self.commit[:1]), ("added", "f")],
                         "a newer listing in an added registry is its own hit")
        code, row = invoke(["registry", "search", "--origin", "added"])
        self.assertEqual({h["registry"] for h in row["result"]["hits"]}, {"official"})
        self.assertEqual(row["result"]["count"], 2)


class DevBuiltinTests(BuiltinFixture):
    def test_plan_touches_no_network_and_install_fetches_once_then_verifies(self):
        code, row = invoke(["dev", "builtin", "--plan"])
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertTrue(result["plan"])
        self.assertEqual({r["state"] for r in result["results"]}, {"absent"})
        self.assertEqual(result["downloads"], [[self.entries[0]["repository"], self.commit]])
        self.assertEqual(self.requests, [])

        code, row = invoke(["dev", "builtin"])
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertEqual(self.requests, [self.url], "one snapshot download serves every built-in at that commit")
        self.assertEqual([r["action"] for r in result["results"]], ["installed"] * len(self.entries))
        by_name = {r["name"]: r for r in result["results"]}
        pack_dir = Path(by_name["sickohours/stock_hello_pack"]["module_dir"])
        self.assertTrue((pack_dir / "composition.json").is_file())
        self.assertTrue(pack_dir.is_relative_to(builtin.shelf_dir()))
        self.assertEqual(pack_dir.parent.parent.name, self.commit, "laid out under <owner>/<repo>/<commit>/<path>")
        shelf_commit = pack_dir.parent.parent
        self.assertFalse((shelf_commit / "README.md").exists(), "only the entries and what their recipes name are kept")
        self.assertTrue((Path(by_name["sickohours/hello_zm"]["module_dir"]) / "scripts" / "hello.gsc").is_file())
        short = self.commit[:12]
        receipts = sorted(p.name for p in Path(result["receipts"]).glob("*.json"))
        self.assertEqual(receipts, [f"sickohours--hello_zm--{short}.json", f"sickohours--round_announcer--{short}.json", f"sickohours--stock_hello_pack--{short}.json"])
        pack_receipt = json.loads((Path(result["receipts"]) / f"sickohours--stock_hello_pack--{short}.json").read_text())
        self.assertEqual(pack_receipt["commit"], self.commit)
        self.assertEqual(sorted(pack_receipt["paths"]), ["examples/hello-pack", "examples/hello-zm", "examples/hello-zm-two"],
                         "a pack's receipt covers its member directories in the same snapshot")
        self.assertEqual(pack_receipt["placed"], ["examples/hello-pack"], "members already placed by their own entries are shared, not copied twice")
        self.assertTrue(all(len(v) == 64 for v in pack_receipt["files"].values()))
        self.assertFalse(result["game_touched"])

        # The shelf composes: the pack's relative member paths resolve inside the snapshot layout.
        with mock.patch.dict(os.environ, {"PAT_BACKEND_GSC": str(FAKES / "fake_gsc.py"), "PAT_BACKEND_LINKER": str(FAKES / "fake_linker.py"),
                                          "PAT_BACKEND_UNLINKER": str(FAKES / "fake_unlinker.py")}):
            code, row = invoke(["module", "plan", str(pack_dir / "composition.json"), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual([m["id"] for m in row["result"]["modules"]], ["hello_zm", "round_announcer"])

        # Search and doctor now point at the shelf.
        code, row = invoke(["registry", "search", "--origin", "builtin", "--entry-kind", "composition"])
        self.assertEqual(row["result"]["hits"][0]["builtin_dir"], str(pack_dir))
        code, row = invoke(["doctor"])
        self.assertEqual((row["result"]["builtin"]["present"], row["result"]["builtin"]["total"]), (3, 3))
        self.assertIsNone(row["result"]["builtin"]["fetch"])

        # A rerun re-hashes and downloads nothing.
        code, row = invoke(["dev", "builtin"])
        self.assertEqual(code, 0, row)
        self.assertEqual([r["action"] for r in row["result"]["results"]], ["verified"] * len(self.entries))
        self.assertEqual(row["result"]["downloads"], [])
        self.assertEqual(self.requests, [self.url])
        code, row = invoke(["dev", "builtin", "--plan"])
        self.assertEqual({r["action"] for r in row["result"]["results"]}, {"verify"})

    def test_changed_and_unrecorded_trees_are_preserved_and_refused(self):
        code, row = invoke(["dev", "builtin", "--only", "sickohours/hello_zm"])
        self.assertEqual(code, 0, row)
        module_dir = Path(row["result"]["results"][0]["module_dir"])
        script = module_dir / "scripts" / "hello.gsc"
        original = script.read_bytes()
        script.write_bytes(original + b"\n// edited by hand\n")
        code, row = invoke(["dev", "builtin", "--only", "sickohours/hello_zm"])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "artifact_changed")
        self.assertEqual(row["details"]["changed"], ["examples/hello-zm/scripts/hello.gsc"])
        self.assertEqual(script.read_bytes(), original + b"\n// edited by hand\n", "never overwritten")
        code, row = invoke(["dev", "builtin", "--plan", "--only", "sickohours/hello_zm"])
        self.assertEqual(row["result"]["results"][0]["action"], "refuse")
        # A directory at the shelf path with no receipt is somebody's; refuse it too.
        other = self.entries[1]
        builtin.entry_dir(other).mkdir(parents=True)
        (builtin.entry_dir(other) / "module.json").write_text("{}")
        code, row = invoke(["dev", "builtin", "--only", other["name"]])
        self.assertEqual(row["error_code"], "output_exists")
        code, row = invoke(["dev", "builtin", "--only", "nobody/nothing"])
        self.assertEqual(row["error_code"], "input_invalid")

    def test_an_added_file_is_a_changed_tree_and_a_pack_records_the_members_it_lays_out(self):
        code, row = invoke(["dev", "builtin", "--only", "sickohours/stock_hello_pack"])
        self.assertEqual(code, 0, row)
        actions = {r["name"]: r["action"] for r in row["result"]["results"]}
        self.assertEqual(actions, {"sickohours/stock_hello_pack": "installed", "sickohours/hello_zm": "recorded", "sickohours/round_announcer": "recorded"},
                         "members the pack laid out get their own receipts from the same snapshot")
        self.assertEqual(self.requests, [self.url])
        code, row = invoke(["dev", "builtin"])
        self.assertEqual(code, 0, row)
        self.assertEqual({r["action"] for r in row["result"]["results"]}, {"verified"}, "no stranger, no second download")
        self.assertEqual(self.requests, [self.url])
        module_dir = Path(next(r["module_dir"] for r in row["result"]["results"] if r["name"] == "sickohours/hello_zm"))
        (module_dir / "notes.txt").write_text("added by hand")
        code, row = invoke(["dev", "builtin", "--only", "sickohours/hello_zm"])
        self.assertEqual(row["error_code"], "artifact_changed")
        self.assertEqual(row["details"]["added"], ["examples/hello-zm/notes.txt"])
        self.assertTrue((module_dir / "notes.txt").is_file(), "preserved")
        code, row = invoke(["dev", "builtin", "--plan"])
        by = {r["name"]: r for r in row["result"]["results"]}
        self.assertEqual(by["sickohours/hello_zm"]["action"], "refuse")
        self.assertEqual(by["sickohours/stock_hello_pack"]["action"], "refuse", "the pack's receipt covers its members too")
        self.assertEqual(by["sickohours/round_announcer"]["action"], "verify")

    def test_a_moved_pin_starts_absent_and_keeps_the_old_snapshot(self):
        code, row = invoke(["dev", "builtin"])
        self.assertEqual(code, 0, row)
        old_dir = Path(row["result"]["results"][0]["module_dir"])
        # A later release pins a newer commit: the shipped registry lists every entry there.
        newer = "f" * 40
        shipped = registry.builtin_registry()
        moved = dict(shipped, entries=[dict(e, listed={**e["listed"], "commit": newer}) for e in shipped["entries"]])
        self.served[registry.snapshot_url(shipped["entries"][0]["repository"], newer)] = repo_tarball(newer)
        with mock.patch.object(registry, "builtin_registry", return_value=moved):
            code, row = invoke(["dev", "builtin", "--plan"])
            self.assertEqual(code, 0, row)
            self.assertEqual({r["state"] for r in row["result"]["results"]}, {"absent"}, "the old receipt is not this pin's receipt")
            code, row = invoke(["dev", "builtin"])
            self.assertEqual(code, 0, row)
            self.assertEqual({r["action"] for r in row["result"]["results"]}, {"installed"})
            new_dir = Path(row["result"]["results"][0]["module_dir"])
            self.assertEqual(new_dir.parent.parent.name, newer)
            code, row = invoke(["dev", "builtin"])
            self.assertEqual({r["action"] for r in row["result"]["results"]}, {"verified"})
        self.assertTrue(old_dir.is_dir(), "the previous snapshot stays on the shelf")
        receipts = sorted(p.name for p in Path(row["result"]["receipts"]).glob("sickohours--hello_zm--*.json"))
        self.assertEqual(len(receipts), 2, "one receipt per pin")
        code, row = invoke(["dev", "builtin"])
        self.assertEqual({r["action"] for r in row["result"]["results"]}, {"verified"}, "the shipped pin still verifies against its own receipt")

    def test_lock_and_download_failures_leave_no_partial_shelf(self):
        builtin.shelf_dir().mkdir(parents=True)
        (builtin.shelf_dir() / "builtin.lock").write_text("1")
        code, row = invoke(["dev", "builtin"])
        self.assertEqual(row["error_code"], "busy")
        (builtin.shelf_dir() / "builtin.lock").unlink()
        self.served.clear()
        code, row = invoke(["dev", "builtin"])
        self.assertEqual(row["error_code"], "input_missing")
        self.assertEqual([p.name for p in builtin.shelf_dir().iterdir()], [], "a failed download leaves no snapshot and no scratch directory")
        code, row = invoke(["doctor"])
        self.assertEqual(row["result"]["builtin"]["present"], 0)
        self.assertEqual(row["result"]["builtin"]["fetch"], "pat dev builtin --json")

    def test_a_pack_whose_recipe_escapes_its_snapshot_is_refused(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            root = "repo-" + self.commit[:7]
            for rel, body in (("examples/hello-pack/composition.json", json.dumps({"schema": 1, "name": "stock_hello_pack", "base": "stock",
                                                                                   "map": "zm_transit", "modules": ["../../../outside"]})),):
                info = tarfile.TarInfo(f"{root}/{rel}"); data = body.encode(); info.size = len(data); info.mode = 0o644
                t.addfile(info, io.BytesIO(data))
        self.served[self.url] = buf.getvalue()
        code, row = invoke(["dev", "builtin", "--only", "sickohours/stock_hello_pack"])
        self.assertEqual(row["error_code"], "input_missing")
        self.assertIn("outside its snapshot", row["message"])

    def test_route_contract(self):
        code, row = invoke(["describe", "dev", "builtin"])
        self.assertEqual(row["result"]["effect"], "downloads-source")
        self.assertIn("artifact_changed", row["result"]["notes"])
        code, row = invoke(["manifest"])
        by_id = {r["id"]: r for r in row["result"]["routes"]}
        self.assertIn("origin", by_id["registry.search"]["notes"])


if __name__ == "__main__":
    unittest.main()
