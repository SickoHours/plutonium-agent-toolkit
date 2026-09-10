"""gsc / ff / project routes against fake backends. Exercises the real Job runner
(Job Object on Windows, process group elsewhere) with PAT_DEV_UNGATED for non-Windows hosts."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from plutonium_agent_toolkit.cli import entry

FAKES = Path(__file__).resolve().parent / "fakes"


def invoke(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = entry(argv)
    return code, json.loads(buf.getvalue())


class DevRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {
            "PAT_HOME": str(self.root / "home"),
            "PAT_DEV_UNGATED": "1",
            "PAT_BACKEND_GSC": str(FAKES / "fake_gsc.py"),
            "PAT_BACKEND_LINKER": str(FAKES / "fake_linker.py"),
            "PAT_BACKEND_UNLINKER": str(FAKES / "fake_unlinker.py"),
        }
        self.saved = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        self.addCleanup(self._restore)
        self.n = 0

    def _restore(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def out(self):
        self.n += 1
        return str(self.root / f"job-{self.n:03d}")

    def test_init_plan_build_verify_round_trip(self):
        code, row = invoke(["project", "init", "--name", "hello_test", "--output", self.out()])
        self.assertEqual(code, 0, row)
        project = Path(row["result"]["output"])
        self.assertTrue((project / "project.json").is_file())
        self.assertTrue((project / "receipt.json").is_file())

        code, row = invoke(["project", "plan", str(project / "project.json"), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertTrue(row["result"]["backends_available"])
        self.assertEqual(row["result"]["scripts"], 1)

        code, row = invoke(["project", "build", str(project / "project.json"), "--output", self.out()])
        self.assertEqual(code, 0, row)
        build = Path(row["result"]["output"])
        self.assertEqual(row["result"]["rawfiles_verified"], 2)
        self.assertTrue((build / row["result"]["mod_ff"]).is_file())
        receipt = json.loads((build / "receipt.json").read_text())
        self.assertEqual(receipt["status"], "succeeded")
        self.assertIn("packages/mod.ff", receipt["outputs"])
        self.assertTrue(any(step["argv"][-1].endswith("mod") for step in receipt["steps"]), "linker step recorded")
        self.assertTrue(all("receipt.json" != rel for rel in receipt["outputs"]))

        code, row = invoke(["project", "verify", str(build / "receipt.json"), "--inputs", "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertTrue(row["result"]["outputs"]["verified"])
        self.assertTrue(row["result"]["inputs"]["verified"])

        (build / "packages" / "mod.ff").write_bytes(b"tampered")
        code, row = invoke(["project", "verify", str(build / "receipt.json"), "--output", self.out()])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "artifact_changed")
        self.assertEqual(row["details"]["outputs"]["changed"], ["packages/mod.ff"])

    def test_compile_error_in_log_fails_even_with_exit_zero(self):
        src = self.root / "bad.gsc"
        src.write_text("main() { FAIL_COMPILE }\n")
        code, row = invoke(["gsc", "compile", str(src), "--output", self.out()])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "backend_failed")
        self.assertIn("fixture compile failure", row["details"]["first_error"])
        receipt = json.loads((Path(row["details"]["receipt"]) if "receipt" in row["details"] else Path(row["receipt"])).read_text())
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["steps"][0]["exit_code"], 0)

    def test_backend_crash_reports_exit_code_and_keeps_receipt(self):
        src = self.root / "crash.gsc"
        src.write_text("main() { CRASH }\n")
        code, row = invoke(["gsc", "compile", str(src), "--output", self.out()])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "backend_failed")
        self.assertEqual(row["details"]["exit_code"], 3)
        self.assertTrue(Path(row["receipt"]).is_file())

    def test_output_directory_must_be_new_and_input_must_exist(self):
        out = self.out()
        Path(out).mkdir()
        code, row = invoke(["gsc", "compile", str(self.root / "x.gsc"), "--output", out])
        self.assertEqual(row["error_code"], "output_exists")
        code, row = invoke(["gsc", "compile", str(self.root / "missing.gsc"), "--output", self.out()])
        self.assertEqual(row["error_code"], "input_missing")

    def test_recipe_rejects_escapes_duplicates_and_bad_suffixes(self):
        base = self.root / "recipe"
        base.mkdir()
        (base / "a.gsc").write_text("main(){}\n")
        cases = {
            "escape": {"scripts": [{"source": "../a.gsc", "target": "scripts/zm/a.gsc"}]},
            "absolute": {"scripts": [{"source": str(base / "a.gsc"), "target": "scripts/zm/a.gsc"}]},
            "suffix": {"scripts": [{"source": "a.gsc", "target": "scripts/zm/a.csc"}]},
            "duplicate": {"scripts": [{"source": "a.gsc", "target": "scripts/zm/a.gsc"}, {"source": "a.gsc", "target": "scripts/zm/a.gsc"}]},
            "traversal-target": {"scripts": [{"source": "a.gsc", "target": "../a.gsc"}]},
            "unknown-field": {"scripts": [{"source": "a.gsc", "target": "scripts/zm/a.gsc", "evil": 1}]},
        }
        for label, extra in cases.items():
            recipe = {"schema": 1, "game": "t6", "name": "x", "assets": [], "loads": [], **extra}
            (base / "project.json").write_text(json.dumps(recipe))
            code, row = invoke(["project", "plan", str(base / "project.json"), "--output", self.out()])
            self.assertEqual(code, 1, label)
            self.assertEqual(row["error_code"], "input_invalid", label)

    def test_ff_inspect_and_extract(self):
        ff = self.root / "sample.ff"
        import base64
        ff.write_text(json.dumps({"zone": "s", "rawfiles": {"scripts/zm/a.gsc": base64.b64encode(b"X").decode()}}))
        code, row = invoke(["ff", "inspect", str(ff), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertIn("rawfile scripts/zm/a.gsc", row["result"]["listing"])
        code, row = invoke(["ff", "extract", str(ff), "--types", "rawfile", "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertTrue((Path(row["result"]["output"]) / "assets" / "scripts/zm/a.gsc").is_file())
        bad = self.root / "bad.ff"
        bad.write_text("not json")
        code, row = invoke(["ff", "inspect", str(bad), "--output", self.out()])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "backend_failed")

    def test_execution_is_windows_gated_without_the_test_hook(self):
        if os.name == "nt":
            self.skipTest("gate does not apply on Windows")
        os.environ.pop("PAT_DEV_UNGATED")
        src = self.root / "a.gsc"
        src.write_text("main(){}\n")
        code, row = invoke(["gsc", "compile", str(src), "--output", self.out()])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "unsupported_platform")
        self.assertFalse(Path(self.root / "job-001").exists(), "no output directory before the gate")

    def test_manifest_marks_dev_routes_implemented(self):
        code, row = invoke(["manifest"])
        by_id = {r["id"]: r for r in row["result"]["routes"]}
        for rid in ("gsc.compile", "ff.link", "project.build", "project.verify"):
            self.assertEqual(by_id[rid]["status"], "implemented", rid)
        for rid in ("game.launch", "capture.start", "test.start", "model.convert"):
            self.assertEqual(by_id[rid]["status"], "planned", rid)


if __name__ == "__main__":
    unittest.main()


class ReviewRegressionTests(DevRouteTests):
    """Regressions for the findings raised on the first review of these routes."""

    def test_names_with_trailing_newline_are_rejected(self):
        base = self.root / "nl"
        base.mkdir()
        (base / "a.gsc").write_text("main(){}\n")
        for label, recipe in {
            "name": {"schema": 1, "game": "t6", "name": "ok\n", "scripts": [], "assets": [], "loads": []},
            "type": {"schema": 1, "game": "t6", "name": "ok", "scripts": [],
                     "assets": [{"source": "a.gsc", "target": "a.txt", "type": "rawfile\n", "name": "a.txt"}], "loads": []},
            "target": {"schema": 1, "game": "t6", "name": "ok",
                       "scripts": [{"source": "a.gsc", "target": "scripts/zm/a.gsc\n"}], "assets": [], "loads": []},
        }.items():
            (base / "project.json").write_text(json.dumps(recipe))
            code, row = invoke(["project", "plan", str(base / "project.json"), "--output", self.out()])
            self.assertEqual(row.get("error_code"), "input_invalid", label)

    def test_symlinked_source_directory_is_rejected(self):
        base = self.root / "linked"
        (base / "real").mkdir(parents=True)
        (base / "real" / "a.gsc").write_text("main(){}\n")
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.gsc").write_text("main(){}\n")
        try:
            (base / "real" / "link").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        code, row = invoke(["gsc", "compile", str(base / "real" / "a.gsc"), "--includes", str(base / "real"), "--output", self.out()])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("Linked source directories", row["message"])

    def test_non_executable_override_is_backend_unavailable_not_a_traceback(self):
        bogus = self.root / "not-a-program.bin"
        bogus.write_bytes(b"\x00\x01 not executable")
        os.environ["PAT_BACKEND_GSC"] = str(bogus)
        src = self.root / "a.gsc"
        src.write_text("main(){}\n")
        code, row = invoke(["gsc", "compile", str(src), "--output", self.out()])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "backend_unavailable", row)
        receipt = json.loads(Path(row["receipt"]).read_text())
        self.assertEqual(receipt["status"], "failed")

    def test_malformed_receipt_is_input_invalid(self):
        bad = self.root / "b" / "receipt.json"
        bad.parent.mkdir()
        bad.write_text("{not json")
        code, row = invoke(["project", "verify", str(bad), "--output", self.out()])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "input_invalid")
        bad.write_text(json.dumps({"schema_version": 1}))
        code, row = invoke(["project", "verify", str(bad), "--inputs", "--output", self.out()])
        self.assertEqual(row["error_code"], "input_invalid")

    def test_finish_rechecks_output_bound(self):
        from unittest.mock import patch

        from plutonium_agent_toolkit.core import jobs

        src = self.root / "a.gsc"
        src.write_text("main(){}\n")
        with patch.object(jobs, "MAX_OUTPUT", 8):
            code, row = invoke(["gsc", "compile", str(src), "--output", self.out()])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "output_limit")

    def test_wine_is_refused_as_not_native(self):
        from unittest.mock import patch

        from plutonium_agent_toolkit.core import platform as plat

        os.environ.pop("PAT_DEV_UNGATED")
        src = self.root / "a.gsc"
        src.write_text("main(){}\n")
        with patch.object(plat, "is_windows", return_value=True), patch.object(plat, "is_wine", return_value=True):
            code, row = invoke(["gsc", "compile", str(src), "--output", self.out()])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "unsupported_platform")
        self.assertIn("Wine", row["message"])

    def test_init_template_and_example_have_no_includes(self):
        code, row = invoke(["project", "init", "--name", "plain", "--output", self.out()])
        text = (Path(row["result"]["output"]) / "scripts" / "plain.gsc").read_text()
        self.assertNotIn("#include", text)
        example = Path(__file__).resolve().parents[1] / "examples" / "hello-zm" / "scripts" / "hello.gsc"
        self.assertNotIn("#include", example.read_text())


class SecondReviewRegressionTests(DevRouteTests):
    """Regressions for the second review round."""

    def test_log_over_bound_at_exit_is_output_limit(self):
        from unittest.mock import patch

        from plutonium_agent_toolkit.core import jobs

        src = self.root / "spam.gsc"
        src.write_text("main() { SPAM_LOG }\n")
        with patch.object(jobs, "MAX_LOG", 4096):
            code, row = invoke(["gsc", "compile", str(src), "--output", self.out()])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "output_limit")
        receipt = json.loads(Path(row["receipt"]).read_text())
        self.assertEqual(receipt["status"], "failed")
        self.assertTrue(receipt["steps"][0].get("log_truncated"))

    def test_wine_discovery_matches_execution_gate(self):
        from unittest.mock import patch

        from plutonium_agent_toolkit.core import platform as plat

        with patch.object(plat, "is_windows", return_value=True), patch.object(plat, "is_wine", return_value=True):
            code, row = invoke(["manifest"])
        self.assertFalse(row["result"]["platform"]["supported"])
        gated = [r for r in row["result"]["routes"] if r["requires_windows"]]
        self.assertTrue(gated)
        self.assertTrue(all(r["available_here"] is False for r in gated))

    def test_backend_replacing_receipt_with_directory_still_yields_a_receipt_file(self):
        src = self.root / "hijack.gsc"
        src.write_text("main() { HIJACK_RECEIPT }\n")
        code, row = invoke(["gsc", "compile", str(src), "--output", self.out()])
        self.assertEqual(code, 0, row)
        receipt_path = Path(row["result"]["receipt"])
        self.assertTrue(receipt_path.is_file())
        receipt = json.loads(receipt_path.read_text())
        self.assertIn("receipt_path_repaired", receipt)
        self.assertTrue((receipt_path.parent / receipt["receipt_path_repaired"][0]).is_dir(), "moved aside, not deleted")

    def test_verify_rejects_escaping_output_keys(self):
        build = self.root / "b"
        build.mkdir()
        outside = self.root / "outside.bin"
        outside.write_bytes(b"external")
        import hashlib
        digest = hashlib.sha256(b"external").hexdigest()
        for key in ("../outside.bin", str(outside), "", "a\\b"):
            (build / "receipt.json").write_text(json.dumps({"schema_version": 1, "outputs": {key: digest}, "inputs": {}}))
            code, row = invoke(["project", "verify", str(build / "receipt.json"), "--output", self.out()])
            self.assertEqual(row.get("error_code"), "input_invalid", key)

    def test_link_readback_failure_with_exit_zero_fails(self):
        project = self.root / "proj"
        (project / "zone_source").mkdir(parents=True)
        (project / "raw").mkdir()
        (project / "raw" / "a.txt").write_text("A")
        (project / "zone_source" / "bad.zone").write_text("> game,T6\n> fixture_readback_fail\nrawfile,a.txt\n")
        code, row = invoke(["ff", "link", str(project), "--zone", "bad", "--output", self.out()])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "backend_failed")
        self.assertIn("loading failure", row["message"])


class ThirdReviewRegressionTests(DevRouteTests):
    def test_extract_accepts_zero_byte_assets(self):
        import base64
        ff = self.root / "empty.ff"
        ff.write_text(json.dumps({"zone": "e", "rawfiles": {"scripts/zm/empty.gsc": base64.b64encode(b"").decode()}}))
        code, row = invoke(["ff", "extract", str(ff), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertTrue((Path(row["result"]["output"]) / "assets/scripts/zm/empty.gsc").is_file())

    def test_asset_names_containing_error_words_do_not_fail_inspect(self):
        import base64
        ff = self.root / "named.ff"
        names = {"scripts/fatal error.gsc": "A", "failed to load.txt": "B", "x/error loading.csv": "C"}
        ff.write_text(json.dumps({"zone": "n", "rawfiles": {k: base64.b64encode(v.encode()).decode() for k, v in names.items()}}))
        code, row = invoke(["ff", "inspect", str(ff), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertIn("rawfile scripts/fatal error.gsc", row["result"]["listing"])

    def test_directory_count_is_bounded(self):
        from unittest.mock import patch

        from plutonium_agent_toolkit.core import jobs

        src = self.root / "dirs.gsc"
        src.write_text("main() { MANY_DIRS }\n")
        with patch.object(jobs, "MAX_FILES", 10):
            code, row = invoke(["gsc", "compile", str(src), "--output", self.out()])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "output_limit")

    def test_dangling_symlink_output_is_output_exists_json(self):
        link = self.root / "dangling"
        try:
            link.symlink_to(self.root / "nowhere")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        src = self.root / "a.gsc"
        src.write_text("main(){}\n")
        code, row = invoke(["gsc", "compile", str(src), "--output", str(link)])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "output_exists")
