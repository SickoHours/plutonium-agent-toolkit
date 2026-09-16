"""``known-issue``: the ninth ledger row type, the one that states no fact.

A row says a module has a bug, who saw it and when, and optionally the 40-hex commit that closes
it. ``module state --ledger`` reads the rows against the module directory's own git head: a fix
that is an ancestor of it is closed, everything else -- no fix yet, a fix this checkout does not
have, a commit git cannot place -- is open, so nobody stitches a broken version because a fix
landed somewhere they are not. Fixtures use synthetic ids, hashes and paths, and the repository
the ancestry is read from is created inside the test.
"""
import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from plutonium_agent_toolkit import cli
from plutonium_agent_toolkit.dev import ledger

DECLARATION = {"schema": 1, "id": "example", "version": "1", "bases": ["stock"],
               "maps": ["zm_transit"], "recipe": "recipe.json"}
SCOPE = {"base": "stock", "foundation": "bo2-stock", "map": "zm_transit"}
ISSUE = {"type": "known-issue", "issue": "Box weapon table misses the donor rifle after round 10",
         "seen_by": "agent-7", "at": "2026-09-14", "scope": SCOPE}
UNKNOWN_COMMIT = "a" * 40


def invoke(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.entry(argv)
    return code, json.loads(out.getvalue())


def book(*rows):
    return {"schema": 1, "subject": {"id": "example"}, "rows": list(rows)}


class KnownIssueValidationTests(unittest.TestCase):
    def check_row(self, row, field, fragment=None):
        _, diagnostics = ledger.validate(book(row))
        self.assertEqual(len(diagnostics), 1, diagnostics)
        self.assertEqual(diagnostics[0]["field"], field, diagnostics)
        if fragment is not None:
            self.assertIn(fragment, diagnostics[0]["message"])

    def test_a_dated_issue_with_a_witness_and_a_scope_validates(self):
        normalized, diagnostics = ledger.validate(book(ISSUE))
        self.assertEqual(diagnostics, [])
        row = normalized["rows"][0]
        self.assertEqual(row["type"], "known-issue")
        self.assertEqual(row["issue"], ISSUE["issue"])
        self.assertEqual(row["seen_by"], "agent-7")
        self.assertEqual(row["at"], "2026-09-14")
        self.assertEqual(row["scope"]["maps"], ["zm_transit"])
        self.assertNotIn("closes_with", row)

    def test_each_required_field_is_required(self):
        for key in ("issue", "seen_by", "scope", "at"):
            with self.subTest(key=key):
                self.check_row({k: v for k, v in ISSUE.items() if k != key}, f"/rows/0/{key}")

    def test_an_issue_is_one_line(self):
        self.check_row({**ISSUE, "issue": "Box misses the rifle\nand the pistol"}, "/rows/0/issue", "one line")
        self.check_row({**ISSUE, "issue": "Box misses the rifle\rand the pistol"}, "/rows/0/issue", "one line")

    def test_an_issue_is_non_empty_text_within_the_limit(self):
        self.check_row({**ISSUE, "issue": "   "}, "/rows/0/issue")
        self.check_row({**ISSUE, "issue": "x" * (ledger.MAX_TEXT + 1)}, "/rows/0/issue")

    def test_seen_by_is_a_person_or_agent_id_of_at_most_200_characters(self):
        self.check_row({**ISSUE, "seen_by": "n" * 201}, "/rows/0/seen_by", "200")
        normalized, diagnostics = ledger.validate(book({**ISSUE, "seen_by": "n" * 200}))
        self.assertEqual(diagnostics, [])
        self.assertEqual(normalized["rows"][0]["seen_by"], "n" * 200)

    def test_closes_with_is_a_whole_commit_not_an_abbreviation(self):
        self.check_row({**ISSUE, "closes_with": "1234abc"}, "/rows/0/closes_with",
                       "closes_with is the 40-hex commit that closes the issue")
        self.check_row({**ISSUE, "closes_with": "A" * 40}, "/rows/0/closes_with")
        normalized, diagnostics = ledger.validate(book({**ISSUE, "closes_with": "b" * 40}))
        self.assertEqual(diagnostics, [])
        self.assertEqual(normalized["rows"][0]["closes_with"], "b" * 40)

    def test_a_capture_is_a_record_pointer(self):
        capture = {"path": "modules/example/docs/issue-11.mp4", "sha256": "c" * 64}
        normalized, diagnostics = ledger.validate(book({**ISSUE, "capture": capture}))
        self.assertEqual(diagnostics, [])
        self.assertEqual(normalized["rows"][0]["capture"], capture)
        self.check_row({**ISSUE, "capture": {"path": "../outside/issue-11.mp4"}}, "/rows/0/capture/path")

    def test_a_field_the_type_does_not_know_is_refused(self):
        self.check_row({**ISSUE, "outcome": "failed"}, "/rows/0/outcome", "unknown field")

    def test_the_row_states_no_fact_and_is_counted_as_history(self):
        self.assertEqual(ledger.row_facts(ledger.validate_row(ISSUE, "/rows/0")), {})
        normalized, _ = ledger.validate(book(ISSUE, {**ISSUE, "at": "2026-09-15", "closes_with": "b" * 40}))
        derived = ledger.facts(normalized, base="stock", map_id="zm_transit")
        self.assertEqual({key: value["value"] for key, value in derived["facts"].items()},
                         {fact: None for fact in ledger.FACTS})
        self.assertEqual(derived["history"]["known-issue"], 2)
        self.assertEqual(derived["scopes"], [])


class KnownIssueReportTests(unittest.TestCase):
    """The open/closed reading, against a git repository this test creates."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.module = self.root / "modules" / "example"
        self.module.mkdir(parents=True)
        (self.module / "module.json").write_text(json.dumps(DECLARATION, indent=2) + "\n", encoding="utf-8")
        self.ledger = self.module / "evidence.json"

    def write(self, *rows):
        self.ledger.write_text(json.dumps(book(*rows), indent=2) + "\n", encoding="utf-8")

    def git(self, *args, check=True):
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, check=check)

    def repository(self):
        """A repository around the module directory, and the sha of the commit that made it."""
        env = {**os.environ, "GIT_CONFIG_GLOBAL": str(self.root / "gitconfig"), "GIT_CONFIG_SYSTEM": os.devnull}
        with mock.patch.dict(os.environ, env, clear=True):
            self.git("init", "--quiet")
            self.git("config", "user.email", "test@example.invalid")
            self.git("config", "user.name", "Test")
            self.git("add", "modules/example/module.json")
            self.git("commit", "--quiet", "-m", "the module")
            return self.git("rev-parse", "HEAD").stdout.strip()

    def report(self, **query):
        return ledger.report(self.module, **query)

    def test_a_fix_in_this_checkout_closes_the_row(self):
        head = self.repository()
        self.write({**ISSUE, "closes_with": head})
        issues = self.report()["known_issues"]
        self.assertEqual(issues["open"], [])
        self.assertEqual(len(issues["closed"]), 1)
        entry = issues["closed"][0]
        self.assertEqual(entry["row"], 0)
        self.assertEqual(entry["issue"], ISSUE["issue"])
        self.assertEqual(entry["seen_by"], "agent-7")
        self.assertEqual(entry["at"], "2026-09-14")
        self.assertEqual(entry["closes_with"], head)
        self.assertEqual(entry["scope"], {"base": "stock", "foundation": "bo2-stock", "maps": ["zm_transit"]})
        self.assertNotIn("ancestry", entry)

    def test_a_commit_this_repository_does_not_know_leaves_the_row_open(self):
        self.repository()
        self.write({**ISSUE, "closes_with": UNKNOWN_COMMIT})
        issues = self.report()["known_issues"]
        self.assertEqual(issues["closed"], [])
        self.assertEqual(len(issues["open"]), 1)
        self.assertEqual(issues["open"][0]["ancestry"], "unknown")
        self.assertEqual(issues["open"][0]["closes_with"], UNKNOWN_COMMIT)

    def test_a_row_with_no_fix_is_open_and_says_nothing_about_ancestry(self):
        self.repository()
        self.write(ISSUE)
        issues = self.report()["known_issues"]
        self.assertEqual(issues["closed"], [])
        self.assertEqual(len(issues["open"]), 1)
        self.assertIsNone(issues["open"][0]["closes_with"])
        self.assertNotIn("ancestry", issues["open"][0])

    def test_open_and_closed_rows_are_read_together_in_row_order(self):
        head = self.repository()
        self.write(ISSUE, {**ISSUE, "at": "2026-09-15", "closes_with": head},
                   {**ISSUE, "at": "2026-09-15", "closes_with": UNKNOWN_COMMIT})
        issues = self.report()["known_issues"]
        self.assertEqual([entry["row"] for entry in issues["open"]], [0, 2])
        self.assertEqual([entry["row"] for entry in issues["closed"]], [1])

    def test_a_directory_that_is_no_repository_leaves_every_fix_unplaced(self):
        self.write({**ISSUE, "closes_with": UNKNOWN_COMMIT})
        issues = self.report()["known_issues"]
        self.assertEqual(issues["closed"], [])
        self.assertEqual(issues["open"][0]["ancestry"], "unknown")

    def test_a_host_without_git_leaves_every_fix_unplaced_and_never_raises(self):
        self.write({**ISSUE, "closes_with": UNKNOWN_COMMIT})
        with mock.patch.object(ledger.subprocess, "run", side_effect=FileNotFoundError("git")):
            issues = self.report()["known_issues"]
        self.assertEqual(issues["closed"], [])
        self.assertEqual(issues["open"][0]["ancestry"], "unknown")

    def test_git_taking_too_long_leaves_the_fix_unplaced(self):
        self.write({**ISSUE, "closes_with": UNKNOWN_COMMIT})
        with mock.patch.object(ledger.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 10)):
            issues = self.report()["known_issues"]
        self.assertEqual(issues["open"][0]["ancestry"], "unknown")

    def test_one_commit_is_asked_about_once_however_many_rows_name_it(self):
        head = self.repository()
        self.write({**ISSUE, "closes_with": head}, {**ISSUE, "at": "2026-09-15", "closes_with": head})
        with mock.patch.object(ledger, "_landed", wraps=ledger._landed) as landed:
            issues = self.report()["known_issues"]
        self.assertEqual(landed.call_count, 1)
        self.assertEqual(len(issues["closed"]), 2)

    def test_a_ledger_with_no_known_issue_row_reports_two_empty_lists_and_runs_no_git(self):
        self.write({"type": "agent-reviewed", "outcome": "noted", "scope": SCOPE})
        with mock.patch.object(ledger.subprocess, "run", side_effect=AssertionError("git was run")) as run:
            result = self.report()
        self.assertEqual(result["known_issues"], {"open": [], "closed": []})
        self.assertFalse(run.called)

    def test_an_invalid_header_derives_no_issues_either(self):
        self.ledger.write_text(json.dumps({"schema": 2, "subject": {"id": "example"}, "rows": []}) + "\n", encoding="utf-8")
        result = self.report()
        self.assertEqual(result["validation"], "invalid")
        self.assertEqual(result["known_issues"], {"open": [], "closed": []})

    def test_the_cli_reports_the_issues_beside_the_facts(self):
        head = self.repository()
        self.write(ISSUE, {**ISSUE, "at": "2026-09-15", "closes_with": head})
        status, payload = invoke(["module", "state", "--ledger", str(self.module), "--json"])
        self.assertEqual(status, 0, payload)
        issues = payload["result"]["known_issues"]
        self.assertEqual([entry["row"] for entry in issues["open"]], [0])
        self.assertEqual([entry["row"] for entry in issues["closed"]], [1])
        self.assertEqual(payload["result"]["history"]["known-issue"], 2)

    def test_ledger_add_appends_a_known_issue_row_and_reads_it_back(self):
        row = self.root / "row.json"
        row.write_text(json.dumps(ISSUE, indent=2) + "\n", encoding="utf-8")
        status, payload = invoke(["module", "ledger-add", str(self.module), "--row", str(row), "--json"])
        self.assertEqual(status, 0, payload)
        result = payload["result"]
        self.assertTrue(result["created"])
        self.assertEqual((result["rows_before"], result["rows_after"], result["appended"]), (0, 1, [0]))
        self.assertEqual(result["validation"], "valid")
        self.assertEqual(result["rows"][0]["type"], "known-issue")
        # The row states nothing, so the facts the ledger now derives for its scope stay unknown.
        self.assertEqual({key: value["value"] for key, value in result["rows"][0]["scopes"][0]["facts"].items()},
                         {fact: None for fact in ledger.FACTS})
        self.assertEqual(json.loads(self.ledger.read_text(encoding="utf-8"))["rows"], [ISSUE])
        issues = self.report()["known_issues"]
        self.assertEqual(len(issues["open"]), 1)
        self.assertEqual(issues["open"][0]["issue"], ISSUE["issue"])

    def test_ledger_add_refuses_a_row_with_no_date(self):
        row = self.root / "row.json"
        row.write_text(json.dumps({k: v for k, v in ISSUE.items() if k != "at"}, indent=2) + "\n", encoding="utf-8")
        status, payload = invoke(["module", "ledger-add", str(self.module), "--row", str(row), "--json"])
        self.assertEqual(status, 1, payload)
        self.assertEqual(payload["details"]["diagnostics"][0]["field"], "/rows/0/at")
        self.assertFalse(self.ledger.exists())


if __name__ == "__main__":
    unittest.main()
