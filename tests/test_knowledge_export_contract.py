"""Shipped knowledge is generator output, and a commit that changes it says so.

Every file named here is written by the maintainer's T6 knowledge generator and copied into the
package; none of it is authored in this repository. That rule was broken four times before it was
written down: separate pull requests edited crash-signature ids, engine-limit notes, a
``count_source`` and two regexes straight into the shipped JSON. Each edit was right on its own
terms, and every one of them would have been reverted silently by the next regeneration, which
would then have shipped the reverted rows as fresh output.

The generator stamps ``exported_by`` and ``exported_at`` on each file it writes, so a hand edit is
visible: the rows moved and the marker did not. These tests check the marker is there and
well-formed, and — where git history is available — that the last commit touching each file changed
its marker too, which a hand edit does not.
"""
import json
import re
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path

from plutonium_agent_toolkit.dev import knowledge

# The files the generator's `export --public` writes. `stock-exports.json` ships beside them and is
# not an export product, so it carries no marker and is not covered here.
EXPORTED = ("builtins.json", "engine-limits.json", "crash-signatures.json", "occupancy.json",
            "map-scripts.json", "native-weapons.json")
GENERATOR = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}\Z")
INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
ROOT = Path(__file__).resolve().parent.parent


def git(*argv):
    """Run git in the repository, or return None when it cannot answer."""
    try:
        done = subprocess.run(("git", "-C", str(ROOT), *argv), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


class ExportedKnowledgeCarriesItsMarker(unittest.TestCase):
    def test_every_exported_file_is_covered_by_this_test(self):
        # knowledge.FILES may grow; a new export product must be listed here or say why it is not.
        self.assertEqual(set(knowledge.FILES) - set(EXPORTED), {"stock-exports.json"})
        for name in EXPORTED:
            self.assertTrue((knowledge.DATA / name).is_file(), name)

    def test_each_exported_file_carries_a_well_formed_marker(self):
        seen = set()
        for name in EXPORTED:
            doc = json.loads((knowledge.DATA / name).read_text(encoding="utf-8"))
            self.assertIsInstance(doc.get("exported_by"), str, name)
            self.assertRegex(doc["exported_by"], GENERATOR, name)
            self.assertIsInstance(doc.get("exported_at"), str, name)
            self.assertRegex(doc["exported_at"], INSTANT, name)
            stamped = datetime.strptime(doc["exported_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            self.assertLessEqual(stamped, datetime.now(timezone.utc), f"{name} is stamped in the future")
            seen.add(doc["exported_by"])
        # One generator writes all six; two names would mean one of them was typed by hand.
        self.assertEqual(len(seen), 1, seen)

    def test_stock_exports_is_not_an_export_product_and_carries_no_marker(self):
        doc = json.loads((knowledge.DATA / "stock-exports.json").read_text(encoding="utf-8"))
        self.assertNotIn("exported_by", doc)

    def test_a_change_to_an_exported_file_comes_with_a_new_marker(self):
        """A hand edit moves rows and leaves the marker alone; a re-export moves both.

        Uncommitted work is judged against ``HEAD``, so a contributor sees this before they commit.
        Otherwise the last commit that touched the file is judged against its parent.
        """
        if git("rev-parse", "--is-inside-work-tree") is None:
            self.skipTest("not a git work tree (an installed package, or git is unavailable)")
        if (git("rev-parse", "--is-shallow-repository") or "").strip() == "true":
            self.skipTest("shallow clone: the commit before a change is not in this checkout")
        for name in EXPORTED:
            rel = f"src/plutonium_agent_toolkit/knowledge/{name}"
            working = (knowledge.DATA / name).read_text(encoding="utf-8")
            at_head = git("show", f"HEAD:{rel}")
            if at_head is not None and at_head != working:
                self.check_marker_moved(rel, at_head, working, "the working tree changes")
                continue
            head = (git("log", "-1", "--format=%H", "--", rel) or "").strip()
            self.assertTrue(head, f"no commit history for {rel}")
            before = git("show", f"{head}~1:{rel}")
            if before is None:
                continue  # the commit that added the file, or a root commit: nothing to compare
            after = git("show", f"{head}:{rel}")
            self.assertIsNotNone(after, rel)
            self.check_marker_moved(rel, before, after, f"commit {head[:12]} changes")

    def check_marker_moved(self, rel, before, after, what):
        old, new = json.loads(before), json.loads(after)
        self.assertNotEqual(
            (old.get("exported_by"), old.get("exported_at")),
            (new.get("exported_by"), new.get("exported_at")),
            f"{what} {rel} without re-exporting it: the export marker is unchanged, so the rows "
            f"were edited by hand. Edit the generator's sources and re-export; see "
            f"docs/knowledge/README.md.")


if __name__ == "__main__":
    unittest.main()
