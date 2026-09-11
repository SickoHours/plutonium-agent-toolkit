"""``dev install-skills``: the checkout's skills copied into each harness's skills directory under a
fake home, with the record and receipt under an isolated toolkit home. No harness is launched."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from plutonium_agent_toolkit.cli import entry
from plutonium_agent_toolkit.dev import skills

ROOT = Path(__file__).resolve().parents[1]


def invoke(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = entry(argv)
    return code, json.loads(buf.getvalue())


class SkillsFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.saved = os.environ.get("PAT_HOME")
        os.environ["PAT_HOME"] = str(self.root / "pat-home")
        self.addCleanup(self._restore)
        self.home = self.root / "home"
        for marker in (".claude", ".codex", ".gemini"):
            (self.home / marker).mkdir(parents=True)
        self.names = sorted(p.name for p in (ROOT / "skills").iterdir() if (p / "SKILL.md").is_file())

    def _restore(self):
        if self.saved is None:
            os.environ.pop("PAT_HOME", None)
        else:
            os.environ["PAT_HOME"] = self.saved

    def install(self, *extra):
        return invoke(["dev", "install-skills", "--home", str(self.home), *extra])


class InstallSkillsTests(SkillsFixture):
    def test_plan_writes_nothing_and_install_writes_stamped_copies_with_a_receipt(self):
        code, row = self.install("--plan")
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertTrue(result["plan"])
        self.assertEqual(result["skills"], self.names)
        found = {h["id"]: h for h in result["harnesses"]}
        self.assertTrue(found["claude"]["found"] and found["codex"]["found"] and found["gemini"]["found"])
        self.assertFalse(found["cursor"]["found"])
        self.assertEqual(found["cursor"]["reason"], "home directory absent")
        self.assertEqual(result["summary"]["found"], 3)
        self.assertFalse((self.home / ".claude" / "skills").exists(), "plan writes nothing")
        self.assertIsNone(result["receipt"])

        code, row = self.install()
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertEqual(result["summary"]["refused"], 0)
        self.assertEqual(result["summary"]["written"], sum(len(h["files"]) for h in result["harnesses"]))
        installed = self.home / ".claude" / "skills" / "pat-build" / "SKILL.md"
        text = installed.read_text(encoding="utf-8")
        source = (ROOT / "skills" / "pat-build" / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: pat-build\n"), "frontmatter is preserved verbatim")
        self.assertIn("Installed by `pat dev install-skills`", text)
        self.assertIn(str(ROOT), text, "the note names the checkout the relative paths refer to")
        body = source[source.index("\n---\n") + 5:].lstrip("\n")
        self.assertTrue(text.endswith(body), "the skill's own text is unchanged after the note")
        for name in self.names:
            for harness in (".claude", ".codex", ".gemini"):
                self.assertTrue((self.home / harness / "skills" / name / "SKILL.md").is_file(), (harness, name))
        record = json.loads(Path(result["record"]).read_text(encoding="utf-8"))
        self.assertEqual(len(record["files"]), result["summary"]["written"])
        receipt = json.loads(Path(result["receipt"]).read_text(encoding="utf-8"))
        self.assertEqual(receipt["command"], "dev install-skills")
        self.assertEqual(receipt["summary"], result["summary"])
        self.assertFalse(receipt["game_touched"])

        code, row = self.install()
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["summary"]["written"], 0)
        self.assertEqual(row["result"]["summary"]["unchanged"], result["summary"]["written"], "a rerun with nothing changed writes nothing")

    def test_foreign_files_are_refused_and_everything_else_is_still_written(self):
        foreign = self.home / ".codex" / "skills" / "pat-help" / "SKILL.md"
        foreign.parent.mkdir(parents=True)
        foreign.write_text("---\nname: pat-help\n---\nsomebody else's skill\n", encoding="utf-8")
        code, row = self.install()
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "output_exists")
        details = row["details"]
        self.assertEqual(details["summary"]["refused"], 1)
        self.assertGreater(details["summary"]["written"], 0)
        self.assertEqual(foreign.read_text(encoding="utf-8"), "---\nname: pat-help\n---\nsomebody else's skill\n", "never overwritten")
        refused = [f for h in details["harnesses"] for f in h["files"] if f["action"] == "refused"]
        # Paths are reported under the resolved home (on Windows the runner's temp directory is a short name).
        self.assertEqual([Path(f["path"]).resolve() for f in refused], [foreign.resolve()])
        self.assertIn("did not write", refused[0]["reason"])
        self.assertTrue((self.home / ".claude" / "skills" / "pat-help" / "SKILL.md").is_file())
        # The record holds only what was written, so a later run still refuses the same file.
        record = json.loads(Path(details["record"]).read_text(encoding="utf-8"))
        self.assertNotIn(str(foreign.resolve()), record["files"])

    def test_a_file_this_route_wrote_is_updated_when_the_source_changes(self):
        code, row = self.install("--only", "claude")
        self.assertEqual(code, 0, row)
        target = self.home / ".claude" / "skills" / "pat-help" / "SKILL.md"
        before = target.read_bytes()
        # A newer checkout renders different bytes; simulate it by changing what the route would write.
        original = skills.stamp
        try:
            skills.stamp = lambda text, root, name: original(text, root, name) + "\nA line the next release added.\n"
            code, row = self.install("--only", "claude")
        finally:
            skills.stamp = original
        self.assertEqual(code, 0, row)
        summary = row["result"]["summary"]
        self.assertEqual((summary["refused"], summary["written"]), (0, 0))
        self.assertEqual(summary["updated"], len(self.names), "each SKILL.md this route wrote is refreshed; other files are unchanged")
        self.assertNotEqual(target.read_bytes(), before)
        self.assertTrue(target.read_text(encoding="utf-8").endswith("A line the next release added.\n"))

    def test_linked_destinations_and_bad_arguments_are_refused(self):
        (self.home / ".codex" / "skills").mkdir()
        try:
            (self.home / ".codex" / "skills" / "pat-build").symlink_to(self.root / "elsewhere")
        except (OSError, NotImplementedError):
            linked = False
        else:
            linked = True
        if linked:
            code, row = self.install("--only", "codex")
            self.assertEqual(row["error_code"], "output_exists")
            refused = [f for h in row["details"]["harnesses"] for f in h["files"] if f["action"] == "refused"]
            self.assertTrue(refused and all("link" in f["reason"] for f in refused))
            self.assertFalse((self.root / "elsewhere").exists(), "nothing was written through the link")
        code, row = self.install("--only", "cursor")
        self.assertEqual(row["error_code"], "input_missing", "a named harness that is not set up here")
        code, row = self.install("--only", "vscode")
        self.assertEqual(row["error_code"], "input_invalid")
        code, row = invoke(["dev", "install-skills", "--home", "relative/home"])
        self.assertEqual(row["error_code"], "input_invalid")
        code, row = invoke(["dev", "install-skills", "--home", str(self.root / "no-such-home")])
        self.assertEqual(row["error_code"], "input_missing")
        for source in ("relative/checkout", str(self.root / "not-a-checkout")):
            code, row = invoke(["dev", "install-skills", "--home", str(self.home), "--source", source])
            self.assertEqual(row["error_code"], "input_invalid" if source.startswith("relative") else "input_missing", source)
        (self.root / "not-a-checkout").mkdir()
        code, row = invoke(["dev", "install-skills", "--home", str(self.home), "--source", str(self.root / "not-a-checkout")])
        self.assertEqual(row["error_code"], "input_missing", "an existing directory that is not a toolkit checkout")

    def test_review_findings_files_in_the_way_oversized_targets_linked_home_and_bad_records(self):
        # A regular file where a skill directory should be: refused, never a crash.
        (self.home / ".gemini" / "skills").mkdir()
        (self.home / ".gemini" / "skills" / "pat-build").write_text("not a directory")
        code, row = self.install("--only", "gemini")
        self.assertEqual(row["error_code"], "output_exists")
        refused = [f for h in row["details"]["harnesses"] for f in h["files"] if f["action"] == "refused"]
        self.assertTrue(refused and all("is a file" in f["reason"] for f in refused))
        self.assertEqual((self.home / ".gemini" / "skills" / "pat-build").read_text(), "not a directory")
        # An oversized destination is refused without being read.
        big = self.home / ".claude" / "skills" / "pat-help" / "SKILL.md"
        big.parent.mkdir(parents=True)
        with big.open("wb") as handle:
            handle.truncate(skills.MAX_SKILL_FILE_BYTES + 1)
        code, row = self.install("--only", "claude")
        self.assertEqual(row["error_code"], "output_exists")
        refused = [f for h in row["details"]["harnesses"] for f in h["files"] if f["action"] == "refused"]
        self.assertEqual(len(refused), 1)
        self.assertIn("larger than any skill file", refused[0]["reason"])
        self.assertEqual(big.stat().st_size, skills.MAX_SKILL_FILE_BYTES + 1)
        # A home that is itself a link is used at its real location, and the result says so.
        link = self.root / "home-link"
        try:
            link.symlink_to(self.home, target_is_directory=True)
        except (OSError, NotImplementedError):
            link = None
        if link is not None:
            code, row = invoke(["dev", "install-skills", "--home", str(link), "--only", "codex", "--plan"])
            self.assertEqual(code, 0, row)
            self.assertEqual(row["result"]["home"], str(link))
            self.assertEqual(row["result"]["home_resolved"], str(self.home.resolve()))
            self.assertTrue(all(f["path"].startswith(str(self.home.resolve())) for h in row["result"]["harnesses"] for f in h["files"]))
            # A linked directory below the home (dotfile setups) is refused, not written through.
            (self.home / ".config").mkdir()
            elsewhere = self.root / "dotfiles-opencode"
            elsewhere.mkdir()
            (self.home / ".config" / "opencode").symlink_to(elsewhere, target_is_directory=True)
            code, row = self.install("--only", "opencode", "--plan")
            self.assertEqual(row["error_code"], "input_missing", "a linked harness home directory is not detected as a harness")
        # A malformed install record is a structured failure, never a traceback.
        record = Path(skills.state_dir()) / "installed.json"
        record.write_text(json.dumps({"schema": 1, "files": {str(big): None}}))
        code, row = self.install("--only", "codex")
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("malformed entry", row["message"])

    def test_second_review_round_oversized_render_partial_installs_and_a_swapped_directory(self):
        # A source SKILL.md at exactly the limit would be installed larger than it: refused before writing.
        largest = max((ROOT / "skills" / n / "SKILL.md").stat().st_size for n in self.names)
        with mock.patch.object(skills, "MAX_SKILL_FILE_BYTES", largest):
            code, row = self.install("--only", "claude", "--plan")
        self.assertEqual(row["error_code"], "input_limit")
        self.assertIn("as installed", row["message"])
        # status judges every file a skill installs, not only SKILL.md: a fake checkout with a two-file skill.
        checkout = self.root / "checkout"
        (checkout / "skills" / "two-file").mkdir(parents=True)
        (checkout / "AGENTS.md").write_text("agents\n")
        (checkout / "CONTEXT.md").write_text("context\n")
        (checkout / "skills" / "two-file" / "SKILL.md").write_text("---\nname: two-file\ndescription: test\n---\n\nBody.\n")
        (checkout / "skills" / "two-file" / "reporting.md").write_text("asset\n")
        code, row = invoke(["dev", "install-skills", "--home", str(self.home), "--only", "codex", "--source", str(checkout)])
        self.assertEqual(code, 0, row)
        report = skills.status(str(self.home), source=str(checkout))
        codex = next(h for h in report["harnesses"] if h["id"] == "codex")
        self.assertEqual((codex["current"], codex["ok"]), (1, True))
        (self.home / ".codex" / "skills" / "two-file" / "reporting.md").unlink()
        codex = next(h for h in skills.status(str(self.home), source=str(checkout))["harnesses"] if h["id"] == "codex")
        self.assertEqual((codex["current"], codex["missing"], codex["ok"]), (0, 1, False), "a skill with an asset missing is not current")
        # A directory swapped for a link after the decision is caught by the write itself.
        home = self.home.resolve()
        skills_dir = home / ".gemini" / "skills"
        skills_dir.mkdir(parents=True)
        elsewhere = self.root / "swap-target"
        elsewhere.mkdir()
        try:
            (skills_dir / "pat-build").symlink_to(elsewhere, target_is_directory=True)
        except (OSError, NotImplementedError):
            return
        reason = skills._apply(skills_dir / "pat-build" / "SKILL.md", b"x", home)
        self.assertIn("link", reason)
        self.assertEqual(list(elsewhere.iterdir()), [], "nothing was written through the swapped-in link")

    def test_no_harness_found_is_a_clean_result_with_a_hint(self):
        empty = self.root / "empty-home"
        empty.mkdir()
        code, row = invoke(["dev", "install-skills", "--home", str(empty)])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["summary"]["found"], 0)
        self.assertIn(".agents/skills", row["result"]["hint"])

    def test_doctor_reports_skill_status_per_harness(self):
        code, row = invoke(["doctor"])
        self.assertEqual(code, 0, row)
        status = row["result"]["skills"]
        self.assertEqual(status["source"], str(ROOT))
        self.assertEqual(status["skills"], len(self.names))
        self.assertIsInstance(status["harnesses"], list)
        # doctor reads the real home; the per-harness rows are advisory and never fail doctor.
        for harness in status["harnesses"]:
            self.assertEqual(set(harness) >= {"id", "directory", "current", "stale", "foreign", "missing", "ok"}, True)
        report = skills.status(str(self.home))
        self.assertEqual([h["id"] for h in report["harnesses"]], ["claude", "codex", "gemini"])
        self.assertTrue(all(h["missing"] == len(self.names) for h in report["harnesses"]))
        self.assertEqual(report["install"], "pat dev install-skills --json")
        self.install()
        report = skills.status(str(self.home))
        self.assertTrue(all(h["ok"] for h in report["harnesses"]))
        self.assertIsNone(report["install"])

    def test_route_is_registered_as_writes_config_and_launches_nothing(self):
        code, row = invoke(["describe", "dev", "install-skills"])
        self.assertEqual(code, 0)
        self.assertEqual(row["result"]["effect"], "writes-config")
        self.assertIn("launches nothing", row["result"]["notes"])
        self.assertEqual(set(skills.HARNESSES), {"claude", "codex", "gemini", "opencode", "cursor", "hermes", "agents"})


if __name__ == "__main__":
    unittest.main()
