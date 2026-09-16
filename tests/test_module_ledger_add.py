"""``pat module ledger-add``: rows appended to a module's evidence ledger through the same
validator ``module inspect`` applies. Append-only (an existing row is never edited, a repeated
row is refused), all-or-nothing (one bad row writes nothing and every diagnostic carries its row
index and JSON Pointer), and the file's own serialisation survives, so the diff is the rows added.
Fixtures use synthetic ids, hashes and paths."""
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from plutonium_agent_toolkit import cli
from plutonium_agent_toolkit.dev import ledger

SHA_A = "3" * 64
DECLARATION = {"schema": 1, "id": "example", "version": "1", "bases": ["stock"],
               "maps": ["zm_transit"], "recipe": "recipe.json"}
SCOPE = {"base": "stock", "foundation": "bo2-stock", "map": "zm_transit"}
BUILT = {"type": "built-alone", "scope": SCOPE, "at": "2026-09-11", "offline_verified": True,
         "package_sha256": SHA_A,
         "receipt": {"path": ".local/example-20260911/build-02/build.json", "sha256": "1" * 64}}
TESTED = {"type": "game-tested", "run": "e41427497d1d46c4abdd743204e2b997", "result": "passed",
          "scope": {**SCOPE, "mode": "solo", "players": 1}, "package_sha256": SHA_A,
          "installed": True, "launched": True}
ACCEPTED = {"type": "player-accepted", "outcome": "accepted", "reporter": "Halo",
            "at": "2026-09-12T02:55:00Z", "quote": "I just loaded in. Everything is good.",
            "scope": {**SCOPE, "mode": "solo", "players": 1}, "package_sha256": SHA_A,
            "record": {"path": "modules/example/docs/ACCEPTED.json", "sha256": "d" * 64}}


def invoke(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.entry(argv)
    return code, json.loads(out.getvalue())


def values(facts):
    return {key: row["value"] for key, row in facts.items()}


class LedgerAddTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.module = self.root / "modules" / "example"
        self.module.mkdir(parents=True)
        (self.module / "module.json").write_text(json.dumps(DECLARATION, indent=2) + "\n", encoding="utf-8")
        self.ledger = self.module / "evidence.json"
        self.rows = 0

    def row_file(self, payload, name=None):
        self.rows += 1
        path = self.root / (name or f"row-{self.rows}.json")
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return str(path)

    def add(self, *row_files, target=None, code=0):
        status, row = invoke(["module", "ledger-add", str(target or self.module),
                              *[arg for f in row_files for arg in ("--row", f)], "--json"])
        self.assertEqual(status, code, row)
        return row if code else row["result"]

    def book(self):
        return json.loads(self.ledger.read_text(encoding="utf-8"))

    # ----- creating and appending ----------------------------------------------------------

    def test_creates_the_ledger_from_the_declaration_id_when_it_is_absent(self):
        result = self.add(self.row_file(BUILT))
        self.assertTrue(result["created"])
        self.assertEqual(result["subject"], "example")
        self.assertEqual((result["rows_before"], result["rows_after"], result["appended"]), (0, 1, [0]))
        self.assertEqual(result["validation"], "valid")
        self.assertEqual(result["ledger"], str(self.ledger))
        book = self.book()
        self.assertEqual(book["schema"], 1)
        self.assertEqual(book["subject"], {"id": "example"})
        self.assertEqual(book["rows"], [BUILT], "the row is written as it was given")
        self.assertEqual(result["sha256"], hashlib.sha256(self.ledger.read_bytes()).hexdigest())
        # The file this route creates is the file module inspect calls valid.
        self.assertEqual(ledger.inspect(self.ledger, "example")["validation"], "valid")

    def test_appending_keeps_every_earlier_row_and_the_file_s_own_serialisation(self):
        # A ledger written with ensure_ascii False: a diff that re-escaped the accent would hide
        # the row that was added, so the route writes the way the file already writes.
        book = {"schema": 1, "subject": {"id": "example"},
                "rows": [{**BUILT, "note": "Ported from Kosmoes' résumé of the donor."}]}
        self.ledger.write_text(json.dumps(book, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        result = self.add(self.row_file(TESTED))
        self.assertFalse(result["created"])
        self.assertEqual((result["rows_before"], result["rows_after"], result["appended"]), (1, 2, [1]))
        text = self.ledger.read_text(encoding="utf-8")
        self.assertIn("résumé", text, "the accent is not re-escaped")
        self.assertNotIn("\\u00e9", text)
        self.assertEqual(self.book()["rows"][0], book["rows"][0], "the earlier row is untouched")
        self.assertEqual(self.book()["rows"][1], TESTED)
        self.assertTrue(text.startswith('{\n  "schema": 1'), "the indent is the file's own")

    def test_an_ascii_escaping_ledger_keeps_escaping(self):
        book = {"schema": 1, "subject": {"id": "example"},
                "rows": [{**BUILT, "note": "Ported from Kosmoes' résumé of the donor."}]}
        self.ledger.write_text(json.dumps(book, indent=2) + "\n", encoding="utf-8")
        self.add(self.row_file(TESTED))
        self.assertIn("\\u00e9", self.ledger.read_text(encoding="utf-8"))

    def test_several_row_files_and_a_file_of_several_rows_append_in_the_order_given(self):
        first = self.row_file(BUILT)
        second = self.row_file([TESTED, ACCEPTED])
        result = self.add(first, second)
        self.assertEqual((result["rows_before"], result["rows_after"], result["appended"]), (0, 3, [0, 1, 2]))
        self.assertEqual([r["type"] for r in self.book()["rows"]], ["built-alone", "game-tested", "player-accepted"])
        self.assertEqual([r["source"] for r in result["rows"]], [first, second, second])
        facts = {entry["row"]: entry["scopes"][0]["facts"] for entry in result["rows"]}
        self.assertIs(values(facts[0])["offline_verified"], True)
        self.assertIs(values(facts[2])["player_accepted"], True)

    def test_the_target_may_be_the_evidence_file_itself(self):
        result = self.add(self.row_file(BUILT), target=self.ledger)
        self.assertEqual(result["ledger"], str(self.ledger))
        self.assertEqual(len(self.book()["rows"]), 1)

    # ----- the facts the appended row now answers for ---------------------------------------

    def test_a_game_tested_row_states_only_what_the_run_observed(self):
        result = self.add(self.row_file(TESTED))
        entry = result["rows"][0]
        self.assertEqual(entry["type"], "game-tested")
        self.assertEqual(entry["scopes"][0]["scope"],
                         {"base": "stock", "foundation": "bo2-stock", "map": "zm_transit", "location": None})
        facts = values(entry["scopes"][0]["facts"])
        self.assertIs(facts["installed"], True)
        self.assertIs(facts["launched"], True)
        self.assertIsNone(facts["loaded_and_playable"], "a fact the run did not observe stays unknown")
        self.assertIsNone(facts["captured"])
        self.assertIsNone(facts["offline_verified"], "no built-alone row speaks here")
        self.assertIsNone(facts["player_accepted"])

    def test_the_facts_reported_are_the_whole_ledger_s_and_a_location_keeps_its_own(self):
        self.add(self.row_file(BUILT))
        diner = {**TESTED, "scope": {**SCOPE, "location": "diner"}, "loaded_and_playable": True}
        result = self.add(self.row_file(diner))
        facts = values(result["rows"][0]["scopes"][0]["facts"])
        self.assertEqual(result["rows"][0]["scopes"][0]["scope"]["location"], "diner")
        self.assertIs(facts["loaded_and_playable"], True)
        self.assertIsNone(facts["offline_verified"],
                          "the built-alone row has no location; the Diner query does not see it")
        green_run = self.add(self.row_file({**TESTED, "run": "second-run"}))
        self.assertIs(values(green_run["rows"][0]["scopes"][0]["facts"])["offline_verified"], True)

    def test_a_lineage_row_appends_and_names_no_scope(self):
        row = {"type": "lineage", "game": "t5", "map": "zm_prototype",
               "source": "Chronicles Reawakened v3.5 ZIP", "note": "No T6 verification."}
        result = self.add(self.row_file(row))
        self.assertEqual(result["rows"][0], {"row": 0, "type": "lineage",
                                             "source": result["rows"][0]["source"], "scopes": []})

    # ----- refusals: nothing is written -----------------------------------------------------

    def unchanged(self, before):
        self.assertEqual(self.ledger.read_text(encoding="utf-8") if self.ledger.exists() else None, before)

    def test_one_bad_row_writes_nothing_and_every_diagnostic_carries_its_index_and_pointer(self):
        self.add(self.row_file(BUILT))
        before = self.ledger.read_text(encoding="utf-8")
        good = self.row_file(TESTED)
        bad = self.row_file([{**TESTED, "result": "nope"}, {**ACCEPTED, "outcome": "maybe"}])
        row = self.add(good, bad, code=1)
        self.assertEqual(row["error_code"], "input_invalid")
        diagnostics = row["details"]["diagnostics"]
        self.assertEqual([(d["field"], d["row"], d["source"]) for d in diagnostics],
                         [("/rows/2/result", 2, bad), ("/rows/3/outcome", 3, bad)])
        self.assertEqual(row["details"]["rows_before"], 1)
        self.unchanged(before)

    def test_a_row_that_is_not_an_object_or_a_file_that_is_not_json_is_refused(self):
        row = self.add(self.row_file(["not a row"]), code=1)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertEqual(row["details"]["diagnostics"][0]["field"], "/rows/0")
        path = self.root / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        row = self.add(str(path), code=1)
        self.assertEqual(row["error_code"], "input_invalid")
        row = self.add(str(self.root / "absent.json"), code=1)
        self.assertEqual(row["error_code"], "input_missing")
        self.assertFalse(self.ledger.exists())

    def test_an_exact_duplicate_of_an_existing_row_is_refused_and_not_appended_twice(self):
        self.add(self.row_file(TESTED))
        before = self.ledger.read_text(encoding="utf-8")
        again = self.row_file(TESTED)
        row = self.add(again, code=1)
        self.assertEqual(row["error_code"], "row_duplicate")
        self.assertEqual(row["details"]["duplicate_of"], 0)
        self.assertEqual(row["details"]["source"], again)
        self.unchanged(before)
        # The same row in a different shorthand is the same row: map and maps normalize together.
        shorthand = {**TESTED, "scope": {"base": "stock", "foundation": "bo2-stock",
                                         "maps": ["zm_transit"], "mode": "solo", "players": 1}}
        row = self.add(self.row_file(shorthand), code=1)
        self.assertEqual(row["error_code"], "row_duplicate")
        self.unchanged(before)
        # A row that states a further fact is a new row, not a duplicate.
        result = self.add(self.row_file({**TESTED, "loaded_and_playable": True}))
        self.assertEqual(result["appended"], [1])

    def test_two_identical_rows_in_one_invocation_are_refused(self):
        row = self.add(self.row_file(BUILT), self.row_file(BUILT, "twin.json"), code=1)
        self.assertEqual(row["error_code"], "row_duplicate")
        self.assertEqual(row["details"]["duplicate_of"], 0)
        self.assertFalse(self.ledger.exists(), "the first row is not written either")

    def test_a_ledger_whose_subject_is_another_module_is_refused(self):
        self.ledger.write_text(json.dumps({"schema": 1, "subject": {"id": "other"}, "rows": []}, indent=2) + "\n",
                               encoding="utf-8")
        before = self.ledger.read_text(encoding="utf-8")
        row = self.add(self.row_file(BUILT), code=1)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("is not the declaration's id 'example'", row["message"])
        self.assertEqual(row["details"], {"ledger": str(self.ledger), "subject": "other", "declared": "example"})
        self.unchanged(before)

    def test_a_ledger_that_does_not_validate_is_refused_before_anything_is_appended(self):
        book = {"schema": 1, "subject": {"id": "example"}, "rows": [{**BUILT, "offline_verified": "yes"}]}
        self.ledger.write_text(json.dumps(book, indent=2) + "\n", encoding="utf-8")
        before = self.ledger.read_text(encoding="utf-8")
        row = self.add(self.row_file(TESTED), code=1)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertEqual(row["details"]["diagnostics"][0]["field"], "/rows/0/offline_verified")
        self.unchanged(before)

    def test_without_a_declaration_there_is_no_subject(self):
        (self.module / "module.json").unlink()
        row = self.add(self.row_file(BUILT), code=1)
        self.assertEqual(row["error_code"], "input_missing")
        self.assertFalse(self.ledger.exists())

    def test_the_row_limit_is_the_count_after_the_write(self):
        rows = [{**BUILT, "at": f"2026-09-{day:02d}"} for day in range(1, 29)]
        book = {"schema": 1, "subject": {"id": "example"},
                "rows": (rows * 40)[:ledger.MAX_ROWS - 1]}
        self.ledger.write_text(json.dumps(book, indent=2) + "\n", encoding="utf-8")
        before = self.ledger.read_text(encoding="utf-8")
        result = self.add(self.row_file(TESTED))
        self.assertEqual(result["rows_after"], ledger.MAX_ROWS)
        row = self.add(self.row_file({**TESTED, "run": "one-too-many"}), code=1)
        self.assertEqual(row["error_code"], "input_limit")
        self.assertEqual(row["details"]["rows_before"], ledger.MAX_ROWS)
        self.assertEqual(len(self.book()["rows"]), ledger.MAX_ROWS)
        self.assertNotEqual(self.ledger.read_text(encoding="utf-8"), before)

    def test_usage_refusals(self):
        code, row = invoke(["module", "ledger-add", str(self.module), "--json"])
        self.assertEqual(code, 2, row)
        code, row = invoke(["module", "ledger-add", str(self.module / "other.json"),
                            "--row", self.row_file(BUILT), "--json"])
        self.assertEqual(code, 2, row)
        self.assertEqual(row["error_code"], "invalid_arguments")
        self.assertFalse(self.ledger.exists())


class LedgerAddRouteTests(unittest.TestCase):
    def test_the_route_is_registered_as_an_implemented_record_writer(self):
        code, row = invoke(["describe", "module", "ledger-add"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["status"], "implemented")
        self.assertEqual(row["result"]["effect"], "writes-record")
        self.assertFalse(row["result"]["requires_windows"])


if __name__ == "__main__":
    unittest.main()
