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
