"""release_notes.py and bump_version.py against a scratch copy of the repository."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPY_FILES = ["CHANGELOG.md", "pyproject.toml", "src/plutonium_agent_toolkit/__init__.py", "docs/SUPPORT.md",
              "tools/release_check.py", "tools/release_notes.py", "tools/bump_version.py"]


class ReleaseNotesTests(unittest.TestCase):
    def run_notes(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "tools/release_notes.py"), *args], capture_output=True, text=True, cwd=ROOT)

    def test_current_version_section_prints_with_footer(self):
        from plutonium_agent_toolkit import __version__
        proc = self.run_notes(__version__)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("### Added", proc.stdout)
        self.assertIn("docs/SUPPORT.md", proc.stdout)

    def test_tag_form_is_accepted(self):
        proc = self.run_notes("v0.1.0-alpha.1")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_missing_version_fails(self):
        proc = self.run_notes("9.9.9")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no section", proc.stderr)


class BumpVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        for rel in COPY_FILES:
            dest = self.repo / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / rel, dest)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.repo, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "seed"], cwd=self.repo, check=True)

    def run_tool(self, name, *args):
        return subprocess.run([sys.executable, str(self.repo / "tools" / name), *args], capture_output=True, text=True, cwd=self.repo)

    def test_bump_promotes_unreleased_and_release_check_agrees(self):
        changelog = self.repo / "CHANGELOG.md"
        text = changelog.read_text()
        if not re.search(r"^## \[Unreleased\]\n\n### ", text, re.M):
            text = text.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Added\n\n- fixture entry\n", 1)
            changelog.write_text(text)
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "unreleased"], cwd=self.repo, check=True)
        proc = self.run_tool("bump_version.py", "0.2.0", "--date", "2026-09-12")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("tag as v0.2.0", proc.stdout)
        self.assertIn('__version__ = "0.2.0"', (self.repo / "src/plutonium_agent_toolkit/__init__.py").read_text())
        self.assertIn('version = "0.2.0"', (self.repo / "pyproject.toml").read_text())
        self.assertIn("`0.2.0`", (self.repo / "docs/SUPPORT.md").read_text().splitlines()[0])
        new_log = changelog.read_text()
        self.assertIn("## [0.2.0] - 2026-09-12", new_log)
        self.assertRegex(new_log, r"(?m)^## \[Unreleased\]\n\n## \[0\.2\.0\]", "fresh empty Unreleased section on top")
        check = self.run_tool("release_check.py", "--tag", "v0.2.0")
        self.assertEqual(check.returncode, 0, check.stdout)
        self.assertTrue(json.loads(check.stdout)["ok"])

    def test_bump_refuses_dirty_tree_bad_version_and_empty_unreleased(self):
        (self.repo / "pyproject.toml").write_text((self.repo / "pyproject.toml").read_text() + "\n# dirty\n")
        proc = self.run_tool("bump_version.py", "0.2.0")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Commit or stash", proc.stderr)
        subprocess.run(["git", "checkout", "--", "pyproject.toml"], cwd=self.repo, check=True)
        proc = self.run_tool("bump_version.py", "1.0")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("PEP 440", proc.stderr)
        # Ensure the Unreleased section is empty. After a real release bump it already is, so only
        # commit if emptying it actually changed the file; a clean tree is the precondition anyway.
        changelog = self.repo / "CHANGELOG.md"
        changelog.write_text(re.sub(r"(^## \[Unreleased\]\n)(.*?)(?=^## \[)", r"\1\n", changelog.read_text(), count=1, flags=re.M | re.S))
        if subprocess.run(["git", "status", "--porcelain"], cwd=self.repo, capture_output=True, text=True).stdout.strip():
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "empty"], cwd=self.repo, check=True)
        proc = self.run_tool("bump_version.py", "0.2.0")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("nothing to release", proc.stderr)


class ReleaseWorkflowTests(unittest.TestCase):
    def test_workflow_verifies_tag_before_building_and_publishes_with_write_scope_only(self):
        text = (ROOT / ".github/workflows/release.yml").read_text()
        self.assertIn('tags: ["v*"]', text)
        self.assertIn("release_check.py --tag", text)
        self.assertIn("release_notes.py", text)
        self.assertIn("--verify-tag", text)
        self.assertIn("--prerelease", text)
        # Only the publish job may write; the top-level default is read.
        top = text.split("jobs:")[0]
        self.assertIn("contents: read", top)
        self.assertEqual(text.count("contents: write"), 1)
        # verify runs before build, build before publish
        self.assertLess(text.index("name: Verify tag"), text.index("name: Build wheel"))
        self.assertIn("needs: [verify]", text)
        self.assertIn("needs: [build]", text)


if __name__ == "__main__":
    unittest.main()
