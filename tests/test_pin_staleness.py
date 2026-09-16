"""``module plan``: what has happened to a pinned member's folder since the pin.

A member written as ``{"name": …, "commit": …, "path": …}`` says which commit the pack was built
from. When that folder has moved on in the clone the path points at, the plan row carries ``stale``
and the plan carries one warning. It is never a refusal: the pack is honest about what it was, and
whether to fetch again is the person's decision. A local-path member carries no ``stale`` at all
and costs no git call.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest import mock

from tests.test_compositions import CompositionFixture
from tests.test_dev_routes import invoke

# A scratch repository answers for itself alone: no user, system or global git config is read, and
# the identity is the test's own, so a machine with no git identity still commits.
GIT_ENV = {"GIT_AUTHOR_NAME": "pat tests", "GIT_AUTHOR_EMAIL": "tests@example.invalid",
           "GIT_COMMITTER_NAME": "pat tests", "GIT_COMMITTER_EMAIL": "tests@example.invalid",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


class PinStalenessFixture(CompositionFixture):
    def setUp(self):
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")

    def git(self, *argv):
        row = subprocess.run(["git", "-C", str(self.root), *argv], capture_output=True, text=True,
                             env={**os.environ, **GIT_ENV})
        self.assertEqual(row.returncode, 0, row.stderr)
        return row.stdout.strip()

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def repository(self, *mids):
        """A repository in the test's own temp directory holding one folder per module."""
        for mid in mids:
            self.module(mid)
        self.git("init", "-q", "-b", "main")
        self.git("config", "core.autocrlf", "false")
        return self.commit("seed")

    def edit(self, mid, text, message):
        (self.root / "modules" / mid / "notes.txt").write_text(text)
        return self.commit(message)

    def member(self, mid, commit, name=None):
        return {"name": name or f"someone/{mid}", "commit": commit, "path": f"../../modules/{mid}"}

    def plan(self, *members):
        """The plan summary and plan.json of a composition of these members; ok in every case."""
        comp = self.composition(list(members))
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertTrue(row["ok"], row)
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        return row["result"], plan

    def warnings(self, plan):
        """The pin's own warnings. No declaration here names a `reach`, so every member also draws
        the plan's derived "reachable unknown" row; that row is tests/test_reach.py's subject."""
        return [w for w in plan["warnings"] if ": reachable " not in w["message"]]


class PinStalenessTests(PinStalenessFixture):
    def test_a_pin_at_the_folder_head_is_not_stale(self):
        head = self.repository("alpha")
        summary, plan = self.plan(self.member("alpha", head))
        self.assertIsNone(plan["modules"][0]["stale"])
        self.assertEqual(summary["modules"][0]["stale"], plan["modules"][0]["stale"],
                         "the summary row carries what the plan row carries")
        self.assertEqual(self.warnings(plan), [], "an up-to-date pin says nothing")

    def test_later_commits_in_the_folder_are_counted_and_warned_once(self):
        pinned = self.repository("alpha")
        self.edit("alpha", "one", "first change")
        newest = self.edit("alpha", "two", "second change")
        summary, plan = self.plan(self.member("alpha", pinned))
        self.assertEqual(plan["modules"][0]["stale"],
                         {"pinned": pinned, "newest": newest, "commits_between": 2})
        self.assertEqual(summary["modules"][0]["stale"], plan["modules"][0]["stale"])
        self.assertEqual(self.warnings(plan),
                         [{"module": "alpha",
                           "message": f"alpha is pinned at {pinned[:12]} and its folder has "
                                      f"2 newer commit(s), newest {newest[:12]}"}])

    def test_a_commit_touching_another_folder_is_not_this_members_staleness(self):
        pinned = self.repository("alpha", "beta")
        self.edit("beta", "beta moved on", "a change next door")
        summary, plan = self.plan(self.member("alpha", pinned))
        self.assertIsNone(plan["modules"][0]["stale"], "only commits touching this folder count")
        self.assertEqual(summary["modules"][0]["stale"], None)
        self.assertEqual(self.warnings(plan), [])

    def test_a_pin_this_clone_does_not_know_is_a_reason_not_a_refusal(self):
        self.repository("alpha")
        summary, plan = self.plan(self.member("alpha", "b" * 40))
        stale = plan["modules"][0]["stale"]
        self.assertEqual((stale["pinned"], stale["newest"], stale["commits_between"]), ("b" * 40, None, None))
        self.assertIn("not a known commit", stale["reason"])
        self.assertEqual(summary["modules"][0]["stale"], stale)
        self.assertEqual(self.warnings(plan), [], "what git cannot answer is not a warning")

    def test_a_member_outside_any_repository_reports_a_reason(self):
        self.module("alpha")
        summary, plan = self.plan(self.member("alpha", "c" * 40))
        stale = plan["modules"][0]["stale"]
        self.assertEqual((stale["newest"], stale["commits_between"]), (None, None))
        self.assertIn("not inside a git repository", stale["reason"])
        self.assertEqual(summary["modules"][0]["stale"], stale)
        self.assertEqual(self.warnings(plan), [])

    def test_a_local_path_member_carries_no_stale_key_at_all(self):
        self.repository("alpha")
        summary, plan = self.plan("alpha")
        self.assertNotIn("stale", plan["modules"][0])
        self.assertNotIn("stale", summary["modules"][0])
        self.assertIsNone(plan["modules"][0]["reference"])

    def test_a_member_without_a_reference_runs_no_git(self):
        self.module("alpha")
        with mock.patch("plutonium_agent_toolkit.dev.compositions.subprocess.run",
                        side_effect=AssertionError("a local-path member asked git")):
            summary, plan = self.plan("alpha")
        self.assertNotIn("stale", plan["modules"][0])

    def test_two_pinned_members_each_answer_for_their_own_folder(self):
        pinned = self.repository("alpha", "beta")
        newest = self.edit("beta", "beta moved on", "a change next door")
        summary, plan = self.plan(self.member("alpha", pinned), self.member("beta", pinned))
        rows = {row["id"]: row for row in plan["modules"]}
        self.assertIsNone(rows["alpha"]["stale"])
        self.assertEqual(rows["beta"]["stale"], {"pinned": pinned, "newest": newest, "commits_between": 1})
        self.assertEqual(self.warnings(plan),
                         [{"module": "beta",
                           "message": f"beta is pinned at {pinned[:12]} and its folder has "
                                      f"1 newer commit(s), newest {newest[:12]}"}])
        self.assertEqual({row["id"]: row["stale"] for row in summary["modules"]},
                         {"alpha": None, "beta": rows["beta"]["stale"]})
