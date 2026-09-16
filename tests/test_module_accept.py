"""``module accept``: one person's verdict appended to a module's evidence ledger.

The route is the write half of the ``player-accepted`` row specified in docs/evidence-ledger.md.
Nothing here builds, installs or reaches a game: what is under test is the append, the validation
that guards it, and the refusals that leave the file exactly as it was.
"""
import contextlib
import io
import json
import os
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from plutonium_agent_toolkit.cli import entry
from plutonium_agent_toolkit.dev import ledger
from tests.test_compositions import CompositionFixture
from tests.test_dev_routes import invoke

PACKAGE = "a" * 64
RECORD_SHA = "b" * 64
OTHER_PACKAGE = "c" * 64


class AcceptFixture(CompositionFixture):
    def accept(self, directory, *arguments, outcome="accepted", record="receipts/2026-09-15-verdict.json",
               package=PACKAGE, base="stock", foundation="bo2-stock", map_id="zm_transit"):
        return invoke(["module", "accept", str(directory), "--outcome", outcome, "--base", base,
                       "--foundation", foundation, "--map", map_id, "--package", package,
                       "--record", record, *arguments, "--output", self.out()])

    def book(self, directory):
        return json.loads((Path(directory) / "evidence.json").read_text(encoding="utf-8"))

    def seeded(self, directory, subject=None):
        """A ledger that already holds one row, as a module that was qualified would have."""
        path = Path(directory) / "evidence.json"
        path.write_text(json.dumps({
            "schema": 1, "subject": {"id": subject or directory.name},
            "rows": [{"type": "built-alone", "offline_verified": True,
                      "scope": {"base": "stock", "foundation": "bo2-stock", "maps": ["zm_transit"]},
                      "receipt": {"path": "jobs/build-01/receipt.json", "sha256": "1" * 64},
                      "package_sha256": PACKAGE}],
        }, indent=2) + "\n", encoding="utf-8")
        return path


class AcceptTests(AcceptFixture):
    def test_the_ledger_is_created_when_the_module_has_none(self):
        directory = self.module("alpha")
        code, row = self.accept(directory)
        self.assertEqual(code, 0, row)
        book = self.book(directory)
        self.assertEqual(book["schema"], 1)
        self.assertEqual(book["subject"]["id"], "alpha")
        self.assertEqual(len(book["rows"]), 1)
        written = book["rows"][0]
        self.assertEqual(written["type"], "player-accepted")
        self.assertEqual(written["outcome"], "accepted")
        self.assertEqual(written["package_sha256"], PACKAGE)
        self.assertEqual(written["record"], {"path": "receipts/2026-09-15-verdict.json"})
        self.assertEqual(written["scope"], {"base": "stock", "foundation": "bo2-stock", "maps": ["zm_transit"]})
        self.assertEqual(row["result"]["rows"], 1)
        self.assertTrue(row["result"]["created"])

    def test_the_row_is_appended_and_the_rows_already_there_are_untouched(self):
        directory = self.module("alpha")
        self.seeded(directory)
        before = self.book(directory)["rows"][0]
        code, row = self.accept(directory)
        self.assertEqual(code, 0, row)
        book = self.book(directory)
        self.assertEqual(len(book["rows"]), 2)
        self.assertEqual(book["rows"][0], before)
        self.assertEqual(book["rows"][1]["type"], "player-accepted")
        self.assertFalse(row["result"]["created"])

    def test_a_second_verdict_is_a_second_row_and_never_an_edit_of_the_first(self):
        directory = self.module("alpha")
        code, _ = self.accept(directory, "--quote", "guns are good now after testing")
        self.assertEqual(code, 0)
        first = self.book(directory)["rows"][0]
        code, row = self.accept(directory, outcome="rejected", package=OTHER_PACKAGE,
                                record="receipts/2026-09-16-verdict.json")
        self.assertEqual(code, 0, row)
        rows = self.book(directory)["rows"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], first)
        self.assertEqual(rows[1]["outcome"], "rejected")
        self.assertEqual(rows[1]["package_sha256"], OTHER_PACKAGE)
        self.assertEqual(row["result"]["rows"], 2)

    def test_every_optional_field_lands_on_the_row_as_given(self):
        directory = self.module("alpha")
        code, row = self.accept(directory, "--record-sha256", RECORD_SHA, "--reporter", "Halo",
                                "--quote", "guns are good now after testing",
                                "--not-covered", "co-op", "--not-covered", "other maps",
                                "--note", "Scope as given: the bare foundation and the rebuilt trio.",
                                "--at", "2026-09-15T23:04:51Z")
        self.assertEqual(code, 0, row)
        written = self.book(directory)["rows"][0]
        self.assertEqual(written["record"], {"path": "receipts/2026-09-15-verdict.json", "sha256": RECORD_SHA})
        self.assertEqual(written["reporter"], "Halo")
        self.assertEqual(written["quote"], "guns are good now after testing")
        self.assertEqual(written["not_covered"], ["co-op", "other maps"])
        self.assertEqual(written["at"], "2026-09-15T23:04:51Z")
        self.assertIn("bare foundation", written["note"])

    def test_the_row_the_route_reports_is_the_row_it_wrote(self):
        directory = self.module("alpha")
        code, row = self.accept(directory, "--reporter", "Halo")
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["row"], self.book(directory)["rows"][0])
        self.assertEqual(Path(row["result"]["ledger"]), Path(directory) / "evidence.json")


class AcceptRefusalTests(AcceptFixture):
    def test_an_outcome_the_ledger_does_not_know_is_refused_and_nothing_is_written(self):
        directory = self.module("alpha")
        code, row = self.accept(directory, outcome="maybe")
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("accepted", row["message"])
        self.assertFalse((Path(directory) / "evidence.json").exists())

    def test_a_record_path_that_climbs_out_of_the_workspace_is_refused(self):
        directory = self.module("alpha")
        code, row = self.accept(directory, record="../outside/verdict.json")
        self.assertEqual(code, 1, row)
        self.assertFalse((Path(directory) / "evidence.json").exists())

    def test_an_absolute_record_path_is_refused(self):
        directory = self.module("alpha")
        code, row = self.accept(directory, record="/srv/records/verdict.json")
        self.assertEqual(code, 1, row)
        self.assertFalse((Path(directory) / "evidence.json").exists())

    def test_a_refusal_leaves_an_existing_ledger_byte_for_byte_as_it_was(self):
        directory = self.module("alpha")
        path = self.seeded(directory)
        before = path.read_bytes()
        code, row = self.accept(directory, record="../outside/verdict.json")
        self.assertEqual(code, 1, row)
        self.assertEqual(path.read_bytes(), before)

    def test_a_package_that_is_not_a_sha256_is_refused(self):
        directory = self.module("alpha")
        code, row = self.accept(directory, package="not-a-hash")
        self.assertEqual(code, 1, row)
        self.assertFalse((Path(directory) / "evidence.json").exists())

    def test_a_directory_with_no_declaration_is_refused(self):
        empty = self.root / "modules" / "nothing"
        empty.mkdir(parents=True)
        code, row = self.accept(empty)
        self.assertEqual(code, 1, row)
        self.assertFalse((empty / "evidence.json").exists())

    def test_a_ledger_whose_subject_is_another_module_is_refused(self):
        directory = self.module("alpha")
        path = self.seeded(directory, subject="beta")
        before = path.read_bytes()
        code, row = self.accept(directory)
        self.assertEqual(code, 1, row)
        self.assertEqual(path.read_bytes(), before)


class AcceptWriteTests(AcceptFixture):
    """The file the verdict is written to: what is refused before it is opened, what survives a
    write that fails, and what happens when two verdicts are recorded at the same moment."""

    def test_a_symlinked_ledger_is_refused_and_its_target_is_not_written_through(self):
        directory = self.module("alpha")
        victim = self.root / "victim.json"
        victim.write_text('{"not": "a ledger"}\n', encoding="utf-8")
        try:
            (Path(directory) / "evidence.json").symlink_to(victim)
        except (OSError, NotImplementedError) as exc:       # Windows without the privilege
            self.skipTest(f"this host cannot create a symlink: {exc}")
        code, row = self.accept(directory)
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("not a regular file", row["message"])
        self.assertEqual(victim.read_text(encoding="utf-8"), '{"not": "a ledger"}\n',
                         "the link's target is not written through")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "a FIFO needs a POSIX host")
    def test_a_fifo_in_the_ledger_s_place_is_refused_without_ever_opening_it(self):
        directory = self.module("alpha")
        os.mkfifo(Path(directory) / "evidence.json")
        outcome = {}

        def run():
            try:
                outcome["result"] = self.accept(directory)
            except BaseException as exc:                    # an open() here would never return
                outcome["error"] = exc

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(60)
        self.assertFalse(worker.is_alive(), "the route opened the FIFO and blocked on it")
        self.assertNotIn("error", outcome, outcome.get("error"))
        code, row = outcome["result"]
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")

    def test_a_ledger_past_the_size_limit_is_refused_rather_than_parsed(self):
        directory = self.module("alpha")
        path = Path(directory) / "evidence.json"
        # Valid JSON, and larger than a ledger may be: the size is refused from the file's stat,
        # so nothing the module directory holds is parsed into memory to find that out.
        path.write_text(json.dumps({"schema": 1, "subject": {"id": "alpha"}, "rows": []}, indent=2)
                        + " " * ledger.MAX_BYTES, encoding="utf-8")
        before = path.read_bytes()
        code, row = self.accept(directory)
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_limit")
        self.assertEqual(path.read_bytes(), before)

    def test_a_write_that_fails_part_way_leaves_the_verdicts_already_there(self):
        directory = self.module("alpha")
        path = self.seeded(directory)
        before = path.read_bytes()
        with mock.patch("plutonium_agent_toolkit.dev.ledger.os.fsync",
                        side_effect=OSError(28, "No space left on device")):
            code, row = self.accept(directory)
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "operation_failed")
        self.assertEqual(path.read_bytes(), before, "the ledger that was there is byte for byte as it was")
        self.assertEqual([p.name for p in Path(directory).iterdir() if p.name.endswith(".tmp")], [],
                         "the temporary file the failed write left is removed")

    def test_a_date_that_is_not_on_the_calendar_is_refused(self):
        directory = self.module("alpha")
        code, row = self.accept(directory, "--at", "2026-99-99")
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertFalse((Path(directory) / "evidence.json").exists())
        code, row = self.accept(directory, "--at", "2026-02-28")
        self.assertEqual(code, 0, row)

    def test_two_verdicts_recorded_at_once_are_two_rows_and_neither_is_lost(self):
        directory = self.module("alpha")
        path = self.seeded(directory)
        reading = threading.Event()
        real_read = ledger.read

        def slow_read(target):
            # The book is read first and held for a quarter second: that is the window in which a
            # second invocation, if nothing serialised it, would read the same book and then
            # overwrite this one's row with its own.
            book = real_read(target)
            reading.set()
            time.sleep(0.25)
            return book

        codes = []

        def accept(record, output):
            codes.append(entry(["module", "accept", str(directory), "--outcome", "accepted",
                                "--base", "stock", "--foundation", "bo2-stock", "--map", "zm_transit",
                                "--package", PACKAGE, "--record", record, "--output", output]))

        first_out, second_out = self.out(), self.out()
        # One redirect around both threads: two of them would otherwise swap sys.stdout under
        # each other. The receipts are the files, and the file is what this asserts on.
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(ledger, "read", slow_read):
            first = threading.Thread(target=accept, args=("receipts/one.json", first_out))
            first.start()
            self.assertTrue(reading.wait(30), "the first verdict never read the ledger")
            second = threading.Thread(target=accept, args=("receipts/two.json", second_out))
            second.start()
            first.join(60)
            second.join(60)
        self.assertEqual(codes, [0, 0], "both verdicts are recorded")
        book = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual([row["type"] for row in book["rows"]],
                         ["built-alone", "player-accepted", "player-accepted"])
        self.assertEqual(sorted(row["record"]["path"] for row in book["rows"][1:]),
                         ["receipts/one.json", "receipts/two.json"],
                         "the second verdict appended to the row the first one wrote")


class AcceptFormatTests(AcceptFixture):
    """The shelf's serialiser, shared with ``module qualify``: an append writes the rows
    unescaped, so an accent already in the file survives as itself and the diff shows the row
    that was added rather than a re-escape of every accent in the file."""

    def ledger_with_accent(self, directory, ascii_escaped):
        path = Path(directory) / "evidence.json"
        path.write_text(json.dumps({
            "schema": 1, "subject": {"id": "alpha"},
            "rows": [{"type": "agent-reviewed", "outcome": "noted", "scope": {"base": "stock", "maps": ["*"]},
                      "note": "Réimaginé donor cut"}],
        }, indent=2, ensure_ascii=ascii_escaped) + "\n", encoding="utf-8")
        return path

    def test_an_accent_already_in_the_file_is_not_re_escaped_by_an_append(self):
        directory = self.module("alpha")
        path = self.ledger_with_accent(directory, ascii_escaped=False)
        code, row = self.accept(directory)
        self.assertEqual(code, 0, row)
        text = path.read_text(encoding="utf-8")
        self.assertIn("Réimaginé", text)
        self.assertNotIn("\\u00e9", text)

    def test_an_escaped_accent_is_written_back_as_the_character_it_stands_for(self):
        """The same mechanism ``module qualify`` already uses. The bytes differ, the value does
        not: an appended ledger is written unescaped whatever the file held before."""
        directory = self.module("alpha")
        path = self.ledger_with_accent(directory, ascii_escaped=True)
        self.assertIn("\\u00e9", path.read_text(encoding="utf-8"))
        code, row = self.accept(directory)
        self.assertEqual(code, 0, row)
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("\\u00e9", text)
        self.assertEqual(json.loads(text)["rows"][0]["note"], "Réimaginé donor cut")


class AcceptWorkspaceTests(AcceptFixture):
    def test_the_workspace_says_whether_the_cited_record_resolves(self):
        directory = self.module("alpha")
        cited = self.root / "receipts" / "2026-09-15-verdict.json"
        cited.parent.mkdir(parents=True, exist_ok=True)
        cited.write_text("{}\n")
        code, row = self.accept(directory, "--workspace", str(self.root))
        self.assertEqual(code, 0, row)
        self.assertTrue(row["result"]["record_found"])

    def test_a_record_the_workspace_does_not_hold_is_reported_not_refused(self):
        directory = self.module("alpha")
        code, row = self.accept(directory, "--workspace", str(self.root))
        self.assertEqual(code, 0, row)
        self.assertFalse(row["result"]["record_found"])
        self.assertEqual(len(self.book(directory)["rows"]), 1)

    def test_without_a_workspace_the_route_says_nothing_about_the_record_file(self):
        directory = self.module("alpha")
        code, row = self.accept(directory)
        self.assertEqual(code, 0, row)
        self.assertIsNone(row["result"]["record_found"])


class AcceptFactsTests(AcceptFixture):
    def test_the_written_row_is_the_fact_module_state_then_reports(self):
        directory = self.module("alpha")
        code, row = self.accept(directory, "--reporter", "Halo")
        self.assertEqual(code, 0, row)
        code, read = invoke(["module", "state", "--ledger", str(directory), "--base", "stock",
                             "--map", "zm_transit", "--json"])
        self.assertEqual(code, 0, read)
        self.assertTrue(read["result"]["facts"]["player_accepted"]["value"])

    def test_a_rejected_verdict_reports_the_fact_false(self):
        directory = self.module("alpha")
        code, row = self.accept(directory, outcome="rejected")
        self.assertEqual(code, 0, row)
        code, read = invoke(["module", "state", "--ledger", str(directory), "--base", "stock",
                             "--map", "zm_transit", "--json"])
        self.assertEqual(code, 0, read)
        self.assertFalse(read["result"]["facts"]["player_accepted"]["value"])
