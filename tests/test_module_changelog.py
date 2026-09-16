"""``module changelog``: the page a person reads to see what changed in a module, and why.

The executable half of docs/MODULES.md, "A generated changelog per module". Every fixture is a
synthetic module in a git repository this test creates inside its own temporary directory, with a
pinned author, pinned dates and no read of the machine's git configuration, so the commits and the
rendered bytes are the same on every host. Nothing here reads the toolkit's own repository, a real
bank or a game.
"""
import hashlib
import json
import os
import subprocess
from unittest import mock

from plutonium_agent_toolkit.dev import changelog
from tests.test_dev_routes import invoke
from tests.test_module_verify import ModuleVerifyFixture

SCOPE = {"base": "stock", "map": "zm_transit"}
ISSUE = {"type": "known-issue", "issue": "Box table misses the donor rifle after round 10",
         "seen_by": "agent-7", "at": "2026-09-02", "scope": SCOPE}
TESTED = {"type": "game-tested", "run": "run-1", "result": "passed", "at": "2026-09-05",
          "scope": {"base": "stock", "foundation": "bo2-stock", "maps": ["zm_transit", "zm_prison"]}}
ACCEPTED = {"type": "player-accepted", "outcome": "accepted", "scope": SCOPE,
            "record": {"path": "modules/alpha/docs/ACCEPTED.json"}}


class ChangelogFixture(ModuleVerifyFixture):
    """A module with a history: three commits at 0.1.0, the bump to 0.1.1, then two more."""

    def setUp(self):
        super().setUp()
        # Discovery stops above the temporary directory, so a module outside a repository reads as
        # one here even when the temporary directory itself sits inside somebody's checkout.
        ceiling = mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(self.root.parent)})
        ceiling.start()
        self.addCleanup(ceiling.stop)
        self.git_env = dict(os.environ, HOME=str(self.root),
                            GIT_CONFIG_GLOBAL=str(self.root / "gitconfig"), GIT_CONFIG_SYSTEM=os.devnull,
                            GIT_AUTHOR_NAME="Toolkit Test", GIT_AUTHOR_EMAIL="test@example.invalid",
                            GIT_COMMITTER_NAME="Toolkit Test", GIT_COMMITTER_EMAIL="test@example.invalid")

    def git(self, *args, date=None):
        env = dict(self.git_env)
        if date is not None:
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"{date}T10:00:00+00:00"
        done = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, env=env)
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
        return done.stdout.decode("utf-8", "replace")

    def commit(self, subject, date):
        self.git("add", "--all", "--", "modules")
        self.git("commit", "-qm", subject, date=date)

    def ledger(self, directory, rows=(ISSUE, TESTED, ACCEPTED)):
        (directory / "evidence.json").write_text(json.dumps(
            {"schema": 1, "subject": {"id": directory.name}, "rows": list(rows)}, indent=2))
        return directory

    def history(self, mid="alpha", rows=(ISSUE, TESTED, ACCEPTED)):
        """The module and its six commits, the fourth of them the bump to 0.1.1."""
        directory = self.module(mid)
        self.git("init", "-q")
        self.commit("the module, as it was first written", "2026-09-01")
        (directory / "scripts" / f"{mid}.gsc").write_text("main()\n{\n    wait 1;\n}\n")
        self.commit("the map guard that made it load", "2026-09-02")
        (directory / "docs").mkdir(exist_ok=True)
        (directory / "docs" / "TEST.md").write_text("# Test\n")
        self.commit("what a person should look at", "2026-09-03")
        self.redeclare(directory, mid, version="0.1.1")
        self.commit("0.1.1: the fix that landed", "2026-09-04")
        (directory / "scripts" / f"{mid}.gsc").write_text("main()\n{\n    wait 2;\n}\n")
        self.commit("the wait that was too short", "2026-09-05")
        if rows:
            self.ledger(directory, rows)
        (directory / "README.md").write_text("# alpha\n")
        self.commit("a readme for the shelf", "2026-09-06")
        return directory

    def changelog(self, directory, *extra, expect=0):
        code, row = invoke(["module", "changelog", str(directory), "--json", *extra])
        self.assertEqual(code, expect, row)
        return row["result"] if expect == 0 else row["details"]

    def text(self, directory, *extra):
        return self.changelog(directory, *extra)["text"]

    def sections(self, text):
        return [line[3:] for line in text.splitlines() if line.startswith("## ")]

    def body(self, text, version):
        """The lines of one ``## <version>`` section, without its blank lines."""
        out, inside = [], False
        for line in text.splitlines():
            if line.startswith("## "):
                inside = line[3:] == version
                continue
            if inside and line.strip():
                out.append(line)
        return out

    def listing(self, directory):
        return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(directory.rglob("*")) if p.is_file()}


class RenderTests(ChangelogFixture):
    def test_the_header_names_the_module_and_says_the_page_is_generated(self):
        text = self.text(self.history())
        self.assertEqual(text.splitlines()[0], "# Changelog: alpha")
        self.assertIn(changelog.GENERATED, text)
        self.assertTrue(text.endswith("\n") and not text.endswith("\n\n"), repr(text[-40:]))

    def test_versions_run_newest_first_with_the_declarations_own_version_leading(self):
        self.assertEqual(self.sections(self.text(self.history())), ["0.1.1", "0.1.0"])

    def test_a_commit_older_than_the_declaration_lands_under_unversioned_and_it_comes_last(self):
        directory = self.module("alpha")
        declaration = (directory / "module.json").read_bytes()
        (directory / "module.json").unlink()
        self.git("init", "-q")
        self.commit("the scripts, before there was a declaration", "2026-08-30")
        (directory / "module.json").write_bytes(declaration)
        self.commit("the declaration", "2026-08-31")
        text = self.text(directory)
        self.assertEqual(self.sections(text), ["0.1.0", "unversioned"])
        self.assertEqual(self.body(text, "unversioned"),
                         ["- " + self.short("the scripts, before there was a declaration")
                          + " 2026-08-30 the scripts, before there was a declaration"])

    def short(self, subject):
        sha = self.git("log", "--format=%H%x09%s").splitlines()
        return next(line.split("\t")[0][:8] for line in sha if line.split("\t")[1] == subject)

    def test_each_commit_is_under_the_version_its_own_declaration_carried_newest_first(self):
        text = self.text(self.history())
        self.assertEqual([line.split(" ", 3)[2:] for line in self.body(text, "0.1.1") if line[2:10].isalnum()][:3],
                         [["2026-09-06", "a readme for the shelf"],
                          ["2026-09-05", "the wait that was too short"],
                          ["2026-09-04", "0.1.1: the fix that landed"]])
        self.assertEqual([line.split(" ", 3)[2:] for line in self.body(text, "0.1.0") if line[2:10].isalnum()],
                         [["2026-09-03", "what a person should look at"],
                          ["2026-09-02", "the map guard that made it load"],
                          ["2026-09-01", "the module, as it was first written"]])

    def test_the_commit_line_is_the_short_sha_the_date_and_the_subject(self):
        directory = self.history()
        newest = self.git("log", "-1", "--format=%H").strip()
        self.assertIn(f"- {newest[:8]} 2026-09-06 a readme for the shelf", self.text(directory))

    def test_the_three_ledger_rows_land_under_the_version_their_date_falls_in(self):
        text = self.text(self.history())
        self.assertIn("- known issue (2026-09-02, agent-7): Box table misses the donor rifle after round 10",
                      self.body(text, "0.1.0"))
        self.assertIn("- game-tested passed on zm_transit, zm_prison (2026-09-05, run run-1)",
                      self.body(text, "0.1.1"))
        self.assertIn("- player-accepted accepted on zm_transit (undated)", self.body(text, "0.1.1"))

    def test_a_closed_issue_names_the_commit_that_closes_it(self):
        closed = dict(ISSUE, closes_with="0123456789abcdef0123456789abcdef01234567")
        text = self.text(self.history(rows=(closed,)))
        self.assertIn("- known issue (2026-09-02, agent-7): Box table misses the donor rifle after round 10 "
                      "closed by 01234567", self.body(text, "0.1.0"))

    def test_a_module_with_no_ledger_renders_its_commits_and_no_evidence_lines(self):
        text = self.text(self.history(rows=()))
        self.assertEqual(self.sections(text), ["0.1.1", "0.1.0"])
        for word in ("known issue", "game-tested", "player-accepted"):
            self.assertNotIn(word, text)

    def test_the_current_version_leads_even_when_no_commit_carries_it_yet(self):
        directory = self.history()
        self.redeclare(directory, "alpha", version="0.2.0")
        text = self.text(directory)
        self.assertEqual(self.sections(text), ["0.2.0", "0.1.1", "0.1.0"])
        # The undated verdict has no version span to fall in, so it reads under the current one.
        self.assertEqual(self.body(text, "0.2.0"), ["- player-accepted accepted on zm_transit (undated)"])

    def test_two_renders_of_one_module_are_byte_identical(self):
        directory = self.history()
        self.assertEqual(self.text(directory), self.text(directory))

    def test_a_directory_outside_any_repository_says_the_history_could_not_be_read(self):
        directory = self.module("alpha")
        result = self.changelog(directory)
        self.assertEqual(result["inputs"]["history"], "not_counted")
        self.assertEqual(result["inputs"]["reason"], "the module directory is not inside a git repository")
        self.assertEqual(result["versions"], [])
        self.assertIn("The history of this module could not be read "
                      "(the module directory is not inside a git repository)", result["text"])
        self.assertEqual(self.sections(result["text"]), [])
        self.assertEqual(self.changelog(directory, "--check", expect=1)["report"]["current"], False)

    def test_a_module_with_no_commit_of_its_own_yet_is_its_current_version_and_nothing_else(self):
        directory = self.module("alpha")
        self.git("init", "-q")
        (self.root / "elsewhere.txt").write_text("a commit that is not this module's\n")
        self.git("add", "--", "elsewhere.txt")
        self.git("commit", "-qm", "something else entirely", date="2026-09-01")
        text = self.text(directory)
        self.assertEqual(self.sections(text), ["0.1.0"])
        self.assertEqual(self.body(text, "0.1.0"), ["No commit and no evidence row under this version yet."])

    def test_a_directory_with_no_declaration_is_refused(self):
        code, row = invoke(["module", "changelog", str(self.root), "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "input_missing")


class WriteTests(ChangelogFixture):
    def test_a_plain_run_prints_the_page_and_changes_nothing_under_the_module(self):
        directory = self.history()
        before = self.listing(directory)
        result = self.changelog(directory)
        self.assertFalse(result["written"])
        self.assertTrue(result["text"].startswith("# Changelog: alpha"))
        self.assertFalse((directory / "CHANGELOG.md").exists())
        self.assertEqual(self.listing(directory), before)

    def test_write_creates_the_file_and_a_second_write_leaves_it_byte_identical(self):
        directory = self.history()
        path = directory / "CHANGELOG.md"
        first = self.changelog(directory, "--write")
        self.assertTrue(first["written"] and first["changed"])
        self.assertEqual(path.read_text(encoding="utf-8"), self.text(directory))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(digest, first["sha256"])
        second = self.changelog(directory, "--write")
        self.assertFalse(second["changed"])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_the_written_page_has_no_text_key_and_the_plain_run_does(self):
        directory = self.history()
        self.assertNotIn("text", self.changelog(directory, "--write"))
        self.assertIn("text", self.changelog(directory))

    def test_write_refuses_a_changelog_that_is_a_symlink_and_leaves_its_target_untouched(self):
        directory = self.history()
        target = self.root / "elsewhere.md"
        target.write_text("bytes that are not this module's page\n")
        (directory / "CHANGELOG.md").symlink_to(target)
        code, row = invoke(["module", "changelog", str(directory), "--write", "--json"])
        self.assertEqual((code, row["error_code"]), (1, "input_invalid"), row)
        self.assertIn("not a regular file", row["message"])
        self.assertEqual(target.read_text(), "bytes that are not this module's page\n")
        self.assertTrue((directory / "CHANGELOG.md").is_symlink())

    def test_write_and_check_are_mutually_exclusive(self):
        code, row = invoke(["module", "changelog", str(self.root / "modules" / "alpha"), "--write", "--check", "--json"])
        self.assertEqual(code, 2, row)
        self.assertEqual(row["error_code"], "invalid_arguments")


class CheckTests(ChangelogFixture):
    def test_check_is_current_after_a_write_and_writes_nothing(self):
        directory = self.history()
        self.changelog(directory, "--write")
        before = self.listing(directory)
        report = self.changelog(directory, "--check")
        self.assertEqual((report["current"], report["diff_lines"], report["exists"]), (True, 0, True))
        self.assertEqual(self.listing(directory), before)

    def test_check_fails_with_the_differing_line_count_after_a_hand_edit(self):
        directory = self.history()
        self.changelog(directory, "--write")
        path = directory / "CHANGELOG.md"
        path.write_text(path.read_text(encoding="utf-8") + "- and a line somebody typed\n", encoding="utf-8")
        code, row = invoke(["module", "changelog", str(directory), "--check", "--json"])
        self.assertEqual((code, row["error_code"]), (1, "input_invalid"), row)
        self.assertEqual((row["details"]["current"], row["details"]["report"]["exists"]), (False, True))
        self.assertGreater(row["details"]["diff_lines"], 0)
        self.assertIn("stale", row["message"])
        self.assertIn("--write", row["hint"])

    def test_check_fails_when_there_is_no_changelog_at_all(self):
        directory = self.history()
        details = self.changelog(directory, "--check", expect=1)
        self.assertEqual((details["current"], details["report"]["exists"]), (False, False))
        self.assertGreater(details["diff_lines"], 0)
        self.assertFalse((directory / "CHANGELOG.md").exists())

    def test_check_fails_again_once_the_module_moved_on_from_the_page(self):
        directory = self.history()
        self.changelog(directory, "--write")
        (directory / "scripts" / "alpha.gsc").write_text("main()\n{\n    wait 3;\n}\n")
        self.commit("a commit the page does not know", "2026-09-07")
        details = self.changelog(directory, "--check", expect=1)
        self.assertEqual(details["current"], False)


class VerifyRowTests(ChangelogFixture):
    def test_the_row_agrees_when_the_page_on_disk_is_the_generated_one(self):
        directory = self.history()
        self.changelog(directory, "--write")
        row = self.one(self.verify(directory), "/changelog", "agrees")
        self.assertEqual((row["declared"], row["observed"]), (["CHANGELOG.md"], ["CHANGELOG.md"]))

    def test_the_row_reports_a_hand_edited_page_with_the_command_that_regenerates_it(self):
        directory = self.history()
        self.changelog(directory, "--write")
        path = directory / "CHANGELOG.md"
        path.write_text(path.read_text(encoding="utf-8").replace("Box table", "Bux table"), encoding="utf-8")
        row = self.one(self.verify(directory), "/changelog", "observed_not_declared")
        self.assertEqual(row["observed"], ["1 differing lines"])
        self.assertEqual(row["note"], "CHANGELOG.md was edited by hand or is stale; "
                                      "run pat module changelog --write")
        self.one(self.verify(directory, "--strict", expect=1), "/changelog", "observed_not_declared")

    def test_the_row_is_not_counted_when_the_module_has_no_page_and_strict_still_passes_it(self):
        directory = self.history()
        row = self.one(self.verify(directory), "/changelog", "not_counted")
        self.assertEqual(row["note"], "no CHANGELOG.md; pat module changelog --write generates one")
        self.assertFalse(self.rows(self.verify(directory), "/changelog", "observed_not_declared"))

    def test_verify_writes_no_changelog_of_its_own(self):
        directory = self.history()
        before = self.listing(directory)
        self.verify(directory)
        self.assertEqual(self.listing(directory), before)


class ManifestTests(ChangelogFixture):
    def test_the_manifest_lists_the_route_and_describe_names_the_write_flag(self):
        code, row = invoke(["manifest", "--json"])
        self.assertEqual(code, 0, row)
        found = [r for r in row["result"]["routes"] if r["id"] == "module.changelog"]
        self.assertEqual(len(found), 1, "module changelog is not in the manifest")
        self.assertEqual(found[0]["status"], "implemented")
        self.assertIn("Only --write writes", found[0]["notes"])
        code, described = invoke(["describe", "module", "changelog", "--json"])
        self.assertEqual(code, 0, described)
        self.assertEqual(described["result"]["argv"], ["pat", "module", "changelog"])
