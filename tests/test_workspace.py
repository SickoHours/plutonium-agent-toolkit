"""``workspace init``: a workspace directory outside the checkout, created once, never over anything."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from plutonium_agent_toolkit.cli import entry

ROOT = Path(__file__).resolve().parents[1]


def invoke(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = entry(argv)
    return code, json.loads(buf.getvalue())


class WorkspaceInitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()  # Windows temp paths carry a short 8.3 form

    def test_creates_layout_record_and_agents_file_pointing_at_the_checkout(self):
        target = self.root / "my-mods"
        code, row = invoke(["workspace", "init", str(target), "--json"])
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertEqual(result["workspace"], str(target))
        for rel in ("AGENTS.md", "CLAUDE.md", "README.md", ".gitignore", "workspace.json"):
            self.assertTrue((target / rel).is_file(), rel)
        for rel in ("modules", "compositions", "jobs", "receipts", "registries", "donors"):
            self.assertTrue((target / rel).is_dir(), rel)
        agents = (target / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(str(ROOT), agents, "the workspace names the checkout its skills and docs live in")
        self.assertIn("pat manifest --json", agents)
        self.assertEqual((target / "CLAUDE.md").read_text(encoding="utf-8"), "@AGENTS.md\n")
        record = json.loads((target / "workspace.json").read_text(encoding="utf-8"))
        self.assertEqual(record["name"], "my-mods")
        self.assertEqual(record["toolkit_checkout"], str(ROOT))
        self.assertIn("AGENTS.md", record["files"])
        self.assertFalse(result["game_touched"])

    def test_refuses_non_empty_directory_relative_names_and_the_checkout(self):
        target = self.root / "busy"
        target.mkdir()
        (target / "note.txt").write_text("mine")
        code, row = invoke(["workspace", "init", str(target), "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "output_exists")
        self.assertEqual((target / "note.txt").read_text(), "mine")
        self.assertFalse((target / "AGENTS.md").exists())
        code, row = invoke(["workspace", "init", str(self.root / "ok"), "--name", "Bad Name", "--json"])
        self.assertEqual(row["error_code"], "input_invalid")
        code, row = invoke(["workspace", "init", str(ROOT / "examples" / "never"), "--json"])
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertFalse((ROOT / "examples" / "never").exists())

    def test_empty_existing_directory_is_filled_and_a_rerun_refuses(self):
        target = self.root / "empty"
        target.mkdir()
        code, row = invoke(["workspace", "init", str(target), "--json"])
        self.assertEqual(code, 0, row)
        code, row = invoke(["workspace", "init", str(target), "--json"])
        self.assertEqual(row["error_code"], "output_exists")

    def test_a_file_that_appears_mid_run_is_never_overwritten(self):
        from unittest import mock
        from plutonium_agent_toolkit.dev import workspace
        target = self.root / "racy"
        real_mkdir = Path.mkdir

        def mkdir_then_plant(self_path, *a, **k):
            real_mkdir(self_path, *a, **k)
            if self_path == target:
                (target / "AGENTS.md").write_text("theirs")
        with mock.patch.object(Path, "mkdir", mkdir_then_plant):
            code, row = invoke(["workspace", "init", str(target), "--json"])
        self.assertEqual(row["error_code"], "output_exists")
        self.assertEqual((target / "AGENTS.md").read_text(), "theirs")

    def test_gitignore_keeps_nested_donor_inventories(self):
        import shutil, subprocess
        if not shutil.which("git"):
            self.skipTest("git not available")
        target = self.root / "gi"
        invoke(["workspace", "init", str(target), "--json"])
        (target / "donors/source").mkdir(parents=True)
        (target / "donors/source/index.json").write_text("{}")
        (target / "donors/source/blob.ff").write_bytes(b"x")
        subprocess.run(["git", "init", "-q", str(target)], check=True)
        kept = subprocess.run(["git", "-C", str(target), "check-ignore", "donors/source/index.json"], capture_output=True, text=True)
        self.assertEqual(kept.returncode, 1, "the nested inventory is not ignored")
        dropped = subprocess.run(["git", "-C", str(target), "check-ignore", "donors/source/blob.ff"], capture_output=True, text=True)
        self.assertEqual(dropped.returncode, 0, "the nested package is ignored")

    def test_manifest_lists_the_route_as_implemented_and_inert_to_the_game(self):
        code, row = invoke(["describe", "workspace", "init", "--json"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["status"], "implemented")
        self.assertEqual(row["result"]["effect"], "writes-output")


if __name__ == "__main__":
    unittest.main()
