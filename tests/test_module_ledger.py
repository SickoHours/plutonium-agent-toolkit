"""The evidence ledger: rows validated, six facts derived per scope with unknown kept unknown,
and a registry migration proposal that writes nothing. Fixtures copy the shapes of real
workspace rows (a stock TranZit weapon accepted solo, a Beta 2 recut with sealed pack
history, an overlay with a parent) with synthetic ids, hashes and paths."""
import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plutonium_agent_toolkit import cli
from plutonium_agent_toolkit.dev import ledger

SHA_A = "3" * 64
SHA_B = "9" * 64
SHA_P = "e" * 64
RECORD = {"path": "modules/example/docs/ACCEPTED.json", "sha256": "d" * 64}
RECEIPT = {"path": ".local/example-20260911/build-02/build.json", "sha256": "1" * 64}
SCOPE = {"base": "stock", "foundation": "bo2-stock", "map": "zm_transit"}
LEDGER = {
    "schema": 1, "subject": {"id": "example"},
    "rows": [
        {"type": "lineage", "game": "t5", "map": "zm_prototype", "source": "Chronicles Reawakened v3.5 ZIP",
         "note": "Donor perk registration consumed on this T5 map; no T6 verification."},
        {"type": "extracted-from-release", "release": "Chronicles Reawakened v3.5 (Kosmoes) T5 conversion",
         "use": "converted to T6 once by tools/reawakened_guns.py on 2026-09-08", "scope": {"base": "stock", "maps": ["zm_transit"]}},
        {"type": "built-alone", "receipt": RECEIPT, "scope": SCOPE, "offline_verified": True, "package_sha256": SHA_A,
         "at": "2026-09-11"},
        {"type": "game-tested", "run": "e41427497d1d46c4abdd743204e2b997", "result": "passed", "scope": {**SCOPE, "mode": "solo", "players": 1},
         "installed": True, "launched": True, "loaded_and_playable": True, "package_sha256": SHA_A},
        {"type": "player-accepted", "outcome": "accepted", "reporter": "Halo", "at": "2026-09-12T02:55:00Z",
         "quote": "I just loaded in. Everything is good.", "record": RECORD, "package_sha256": SHA_A,
         "scope": {**SCOPE, "mode": "solo", "players": 1, "profile": "stock_example_test"},
         "not_covered": ["co-op", "other maps", "measured performance"]},
        {"type": "accepted-in-pack", "pack": "dlc5-enhanced", "record": {"path": "archive/t6/dlc5-enhanced/docs/EXAMPLE_ACCEPTED.json", "sha256": "7" * 64},
         "scope": {"foundation": "dlc5-beta1", "map": "zm_factory"}, "package_sha256": SHA_P, "at": "2026-09-09",
         "verdict": "Working 100%. It has officially been ported."},
        {"type": "agent-reviewed", "outcome": "noted", "scope": {"base": "stock", "maps": ["*"]},
         "record": {"path": "modules/example/docs/TEST.md"}, "note": "Standalone payload selected by roots from the accepted donor."},
        {"type": "authored", "scope": {"foundation": "dlc5-beta2", "map": "zm_sumpf"}, "parent": {"id": "example", "package_sha256": SHA_A},
         "changes": ["Sumpf-only entrypoints calling parent activate functions."]},
    ],
}


def invoke(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.entry(argv)
    return code, json.loads(out.getvalue())


def values(facts):
    return {key: row["value"] for key, row in facts.items()}


class LedgerValidationTests(unittest.TestCase):
    def test_real_shaped_ledger_validates_and_normalizes_map_to_maps(self):
        normalized, diagnostics = ledger.validate(LEDGER)
        self.assertEqual(diagnostics, [])
        self.assertEqual([r["type"] for r in normalized["rows"]], [r["type"] for r in LEDGER["rows"]])
        self.assertEqual(normalized["rows"][2]["scope"]["maps"], ["zm_transit"])
        self.assertEqual(normalized["rows"][0], {**LEDGER["rows"][0]})

    def check_row(self, row, field, fragment=None):
        _, diagnostics = ledger.validate({**LEDGER, "rows": [row]})
        self.assertEqual(len(diagnostics), 1, row)
        self.assertEqual(diagnostics[0]["field"], field, diagnostics)
        self.assertEqual(diagnostics[0]["error_code"], "input_invalid")
        if fragment:
            self.assertIn(fragment, diagnostics[0]["message"])

    def test_each_defect_is_one_diagnostic_with_a_pointer(self):
        built = LEDGER["rows"][2]
        tested = LEDGER["rows"][3]
        accepted = LEDGER["rows"][4]
        self.check_row({**built, "type": "built"}, "/rows/0/type")
        self.check_row({k: v for k, v in built.items() if k != "receipt"}, "/rows/0/receipt", "receipt")
        self.check_row({**built, "extra": 1}, "/rows/0/extra")
        self.check_row({**built, "offline_verified": "yes"}, "/rows/0/offline_verified", "leave it out when unknown")
        self.check_row({**built, "scope": {"base": "stock", "map": "zm_transit"}}, "/rows/0/scope/foundation", "foundation")
        self.check_row({**built, "scope": {"maps": ["zm_transit"]}}, "/rows/0/scope", "base token")
        self.check_row({**built, "scope": {**SCOPE, "maps": ["zm_transit"]}}, "/rows/0/scope", "exactly one of map")
        self.check_row({**built, "scope": {"base": "stock", "foundation": "bo2-stock", "maps": []}}, "/rows/0/scope/maps")
        self.check_row({**built, "scope": None}, "/rows/0/scope", "missing")
        self.check_row({**built, "receipt": {"path": "/abs/build.json"}}, "/rows/0/receipt/path")
        self.check_row({**built, "receipt": {"path": "../outside/build.json"}}, "/rows/0/receipt/path", "never climbs")
        self.check_row({**built, "receipt": {"path": "a\\b.json"}}, "/rows/0/receipt/path")
        self.check_row({**built, "receipt": {"path": "x.json", "sha256": "abc"}}, "/rows/0/receipt/sha256")
        self.check_row({**built, "package_sha256": "da5976b1"}, "/rows/0/package_sha256")
        self.check_row({**built, "at": "yesterday"}, "/rows/0/at")
        self.check_row({**tested, "result": "ok"}, "/rows/0/result")
        self.check_row({**tested, "run": "a run"}, "/rows/0/run")
        self.check_row({**tested, "captured": "clip.mp4"}, "/rows/0/captured")
        self.check_row({**accepted, "outcome": "passed"}, "/rows/0/outcome")
        self.check_row({k: v for k, v in accepted.items() if k != "record"}, "/rows/0/record", "record")
        self.check_row({**accepted, "supersedes": "short"}, "/rows/0/supersedes")
        self.check_row({"type": "lineage", "game": "t6", "map": "zm_transit", "source": "x"}, "/rows/0", "T4/T5")
        self.check_row({"type": "accepted-in-pack", "pack": "p", "scope": SCOPE}, "/rows/0/record", "record")
        self.check_row({"type": "extracted-from-release", "release": "r", "use": "u", "scope": SCOPE, "commit": "zz"}, "/rows/0/commit")
        self.check_row({"type": "authored", "scope": SCOPE, "parent": {"id": "Bad Id"}}, "/rows/0/parent/id")
        self.check_row("not a row", "/rows/0")

    def test_bad_rows_are_dropped_and_good_rows_kept(self):
        rows = [LEDGER["rows"][2], {"type": "nope"}, LEDGER["rows"][4]]
        normalized, diagnostics = ledger.validate({**LEDGER, "rows": rows})
        self.assertEqual([r["type"] for r in normalized["rows"]], ["built-alone", "player-accepted"])
        self.assertEqual([d["field"] for d in diagnostics], ["/rows/1/type"])

    def test_header_defects_yield_no_ledger(self):
        for data, field in [({"schema": 2, "subject": {"id": "x"}, "rows": []}, "/schema"),
                            ({"schema": 1, "subject": {"id": "Bad"}, "rows": []}, "/subject/id"),
                            ({"schema": 1, "subject": {"id": "x"}, "rows": {}}, "/rows"),
                            ({"schema": 1, "subject": {"id": "x"}}, "/rows"),
                            ([], "/")]:
            normalized, diagnostics = ledger.validate(data)
            self.assertIsNone(normalized, data)
            self.assertEqual(diagnostics[0]["field"], field, data)

    def test_diagnostics_are_bounded(self):
        _, diagnostics = ledger.validate({**LEDGER, "rows": [{"type": "nope"}] * 100})
        self.assertEqual(len(diagnostics), ledger.MAX_DIAGNOSTICS)


class LedgerFactsTests(unittest.TestCase):
    def setUp(self):
        self.normalized, _ = ledger.validate(LEDGER)

    def test_six_facts_come_only_from_matching_rows_and_stay_separate(self):
        derived = ledger.facts(self.normalized, base="stock", map_id="zm_transit")
        self.assertEqual(values(derived["facts"]), {"offline_verified": True, "installed": True, "launched": True,
                                                    "loaded_and_playable": True, "captured": None, "player_accepted": True})
        self.assertEqual(derived["facts"]["offline_verified"]["rows"], [2])
        self.assertEqual(derived["facts"]["player_accepted"]["rows"], [4])
        self.assertEqual(derived["facts"]["installed"]["rows"], [3])

    def test_unknown_stays_unknown_when_no_row_of_the_type_matches(self):
        derived = ledger.facts(self.normalized, base="stock", map_id="zm_buried")
        self.assertEqual(values(derived["facts"]), dict.fromkeys(ledger.FACTS))

    def test_nothing_is_inferred_from_a_pack_that_used_the_module(self):
        # The Beta 1 Der Riese pack acceptance is a row, visible in history and scopes, and
        # feeds none of the six facts for that scope.
        derived = ledger.facts(self.normalized, foundation="dlc5-beta1", map_id="zm_factory")
        self.assertEqual(values(derived["facts"]), dict.fromkeys(ledger.FACTS))
        self.assertEqual(derived["history"]["accepted-in-pack"], 1)
        self.assertNotIn(("dlc5-beta1", "zm_factory"), [(s["scope"]["foundation"], s["scope"]["map"]) for s in derived["scopes"]])

    def test_a_rejection_is_false_not_unknown_and_any_accepted_row_wins(self):
        rejected = {**LEDGER["rows"][4], "outcome": "rejected", "package_sha256": SHA_B}
        normalized, _ = ledger.validate({**LEDGER, "rows": [rejected]})
        derived = ledger.facts(normalized, base="stock", map_id="zm_transit")
        self.assertIs(derived["facts"]["player_accepted"]["value"], False)
        self.assertIsNone(derived["facts"]["offline_verified"]["value"])
        derived = ledger.facts(normalized, base="stock", map_id="zm_transit", package=SHA_A)
        self.assertIsNone(derived["facts"]["player_accepted"]["value"], "the rejected row is about another package")
        normalized, _ = ledger.validate({**LEDGER, "rows": [rejected, LEDGER["rows"][4]]})
        self.assertIs(ledger.facts(normalized, base="stock")["facts"]["player_accepted"]["value"], True)

    def test_a_failed_offline_build_states_false(self):
        normalized, _ = ledger.validate({**LEDGER, "rows": [{**LEDGER["rows"][2], "offline_verified": False}]})
        self.assertIs(ledger.facts(normalized)["facts"]["offline_verified"]["value"], False)

    def test_wildcard_and_query_keys_scope_the_match(self):
        derived = ledger.facts(self.normalized, base="stock", map_id="zm_transit", package=SHA_B)
        self.assertEqual(values(derived["facts"]), dict.fromkeys(ledger.FACTS), "another package has no rows")
        derived = ledger.facts(self.normalized, foundation="bo2-stock")
        self.assertIs(derived["facts"]["player_accepted"]["value"], True)
        derived = ledger.facts(self.normalized, foundation="dlc5-beta2")
        self.assertEqual(values(derived["facts"]), dict.fromkeys(ledger.FACTS), "the overlay row is authorship, not a fact")
        wildcard = {**LEDGER["rows"][2], "scope": {"base": "stock", "foundation": "bo2-stock", "maps": ["*"]}}
        normalized, _ = ledger.validate({**LEDGER, "rows": [wildcard]})
        self.assertIs(ledger.facts(normalized, base="stock", map_id="zm_buried")["facts"]["offline_verified"]["value"], True)
        self.assertIsNone(ledger.facts(normalized, base="b2", map_id="zm_buried")["facts"]["offline_verified"]["value"])

    def test_a_survival_location_never_collapses_into_its_map(self):
        diner = {**LEDGER["rows"][2], "scope": {"base": "stock", "foundation": "bo2-stock", "map": "zm_transit", "location": "diner"}}
        normalized, diagnostics = ledger.validate({**LEDGER, "rows": [diner]})
        self.assertEqual(diagnostics, [])
        self.assertEqual(normalized["rows"][0]["scope"], {"base": "stock", "foundation": "bo2-stock", "maps": ["zm_transit"], "location": "diner"})
        self.assertIsNone(ledger.facts(normalized, base="stock", map_id="zm_transit")["facts"]["offline_verified"]["value"],
                          "a Diner row is not a Green Run row")
        self.assertIs(ledger.facts(normalized, base="stock", map_id="zm_transit", location="diner")["facts"]["offline_verified"]["value"], True)
        self.assertIsNone(ledger.facts(normalized, base="stock", map_id="zm_transit", location="cell_block")["facts"]["offline_verified"]["value"])
        both, _ = ledger.validate({**LEDGER, "rows": [diner, LEDGER["rows"][2]]})
        self.assertIsNone(ledger.facts(both, base="stock", map_id="zm_transit", location="diner")["facts"]["installed"]["value"])
        self.assertEqual(ledger.facts(both, base="stock", map_id="zm_transit", location="diner")["facts"]["offline_verified"]["rows"], [0])
        self.assertEqual(ledger.facts(both, base="stock", map_id="zm_transit")["facts"]["offline_verified"]["rows"], [1])
        scopes = [(s["scope"]["map"], s["scope"]["location"]) for s in ledger.facts(both)["scopes"]]
        self.assertEqual(set(scopes), {("zm_transit", None), ("zm_transit", "diner")})
        for scope, field in [({"base": "stock", "foundation": "bo2-stock", "maps": ["zm_transit", "zm_buried"], "location": "diner"}, "/rows/0/scope/location"),
                             ({"base": "stock", "foundation": "bo2-stock", "maps": ["*"], "location": "diner"}, "/rows/0/scope/location"),
                             ({"base": "stock", "foundation": "bo2-stock", "map": "zm_transit", "location": "Diner!"}, "/rows/0/scope/location")]:
            _, diagnostics = ledger.validate({**LEDGER, "rows": [{**diner, "scope": scope}]})
            self.assertEqual(diagnostics[0]["field"], field, scope)

    def test_per_scope_listing_carries_each_scope_separately(self):
        derived = ledger.facts(self.normalized)
        scopes = {(s["scope"]["base"], s["scope"]["foundation"], s["scope"]["map"]): values(s["facts"]) for s in derived["scopes"]}
        self.assertEqual(set(scopes), {("stock", "bo2-stock", "zm_transit")})
        self.assertEqual(scopes[("stock", "bo2-stock", "zm_transit")]["captured"], None)
        self.assertEqual(scopes[("stock", "bo2-stock", "zm_transit")]["player_accepted"], True)
        self.assertEqual(derived["history"], {"lineage": 1, "authored": 1, "accepted-in-pack": 1, "extracted-from-release": 1,
                                              "agent-reviewed": 1, "shipped": 0})


class LedgerCliTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.env = patch.dict(os.environ, {"PAT_HOME": str(self.root / "pat-home")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.module = self.root / "modules" / "example"
        self.write("modules/example/module.json", {"schema": 1, "id": "example", "version": "0.1.0", "bases": ["stock"],
                                                   "maps": ["zm_transit"], "recipe": "recipe.json",
                                                   "lineage": [{"game": "t5", "map": "zm_prototype", "source": "Chronicles Reawakened v3.5 ZIP"}]})

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) if not isinstance(value, str) else value, encoding="utf-8")
        return path

    def test_inspect_without_a_ledger_reports_none(self):
        code, row = invoke(["module", "inspect", str(self.module / "module.json"), "--json"])
        self.assertEqual(code, 0, row)
        self.assertNotIn("ledger", row["result"])

    def test_inspect_reports_a_valid_ledger(self):
        path = self.write("modules/example/evidence.json", LEDGER)
        code, row = invoke(["module", "inspect", str(self.module / "module.json"), "--json"])
        self.assertEqual(code, 0, row)
        summary = row["result"]["ledger"]
        self.assertEqual(summary["validation"], "valid")
        self.assertEqual(summary["rows"], len(LEDGER["rows"]))
        self.assertEqual(summary["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(summary["types"], sorted({r["type"] for r in LEDGER["rows"]}))
        self.assertEqual(summary["diagnostics"], [])
        self.assertEqual(row["result"]["validation"], "metadata-valid")

    def test_inspect_keeps_ledger_defects_as_diagnostics_not_errors(self):
        self.write("modules/example/evidence.json", {**LEDGER, "subject": {"id": "other"}, "rows": [{"type": "nope"}]})
        code, row = invoke(["module", "inspect", str(self.module / "module.json"), "--json"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["validation"], "metadata-valid")
        summary = row["result"]["ledger"]
        self.assertEqual(summary["validation"], "invalid")
        self.assertEqual([d["field"] for d in summary["diagnostics"]], ["/subject/id", "/rows/0/type"])
        self.write("modules/example/evidence.json", "{not json")
        code, row = invoke(["module", "inspect", str(self.module / "module.json"), "--json"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["ledger"]["validation"], "invalid")
        self.assertEqual(row["result"]["ledger"]["diagnostics"][0]["error_code"], "input_invalid")
        link = self.module / "evidence.json"
        link.unlink()
        link.symlink_to(self.write("elsewhere.json", LEDGER))
        code, row = invoke(["module", "inspect", str(self.module / "module.json"), "--json"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["ledger"]["diagnostics"][0]["error_code"], "input_missing")

    def test_state_ledger_reports_per_fact_per_scope(self):
        self.write("modules/example/evidence.json", LEDGER)
        code, row = invoke(["module", "state", "--ledger", str(self.module), "--base", "stock", "--map", "zm_transit", "--json"])
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertEqual(result["protocol"], "pat.module-ledger/1")
        self.assertEqual(result["validation"], "valid")
        self.assertEqual(result["subject"], "example")
        self.assertEqual(values(result["facts"]), {"offline_verified": True, "installed": True, "launched": True,
                                                   "loaded_and_playable": True, "captured": None, "player_accepted": True})
        self.assertEqual(result["reasons"], [])
        code, row = invoke(["module", "state", "--ledger", str(self.module / "evidence.json"), "--map", "zm_buried", "--json"])
        self.assertEqual(code, 0, row)
        self.assertEqual(values(row["result"]["facts"]), dict.fromkeys(ledger.FACTS))
        self.assertEqual(row["result"]["query"], {"base": None, "foundation": None, "map": "zm_buried", "location": None, "package": None})
        code, row = invoke(["module", "state", "--ledger", str(self.module), "--map", "zm_transit", "--location", "diner", "--json"])
        self.assertEqual(code, 0, row)
        self.assertEqual(values(row["result"]["facts"]), dict.fromkeys(ledger.FACTS), "no row is scoped to the Diner")
        code, row = invoke(["module", "state", "--ledger", str(self.module), "--location", "diner", "--json"])
        self.assertEqual(code, 2, row)

    def test_state_ledger_counts_only_valid_rows_and_says_so(self):
        self.write("modules/example/evidence.json", {**LEDGER, "rows": [LEDGER["rows"][2], {"type": "player-accepted"}]})
        code, row = invoke(["module", "state", "--ledger", str(self.module), "--json"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["validation"], "invalid")
        self.assertIs(row["result"]["facts"]["offline_verified"]["value"], True)
        self.assertIsNone(row["result"]["facts"]["player_accepted"]["value"])
        self.assertEqual(len(row["result"]["diagnostics"]), 1)
        self.assertIn("not counted", row["result"]["reasons"][0])
        self.write("modules/example/evidence.json", {"schema": 3})
        code, row = invoke(["module", "state", "--ledger", str(self.module), "--json"])
        self.assertEqual(code, 0, row)
        self.assertEqual(values(row["result"]["facts"]), dict.fromkeys(ledger.FACTS))
        self.assertIn("header is invalid", row["result"]["reasons"][0])

    def test_state_ledger_refuses_missing_and_composition_flags(self):
        code, row = invoke(["module", "state", "--ledger", str(self.module), "--json"])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_missing")
        self.write("modules/example/evidence.json", LEDGER)
        code, row = invoke(["module", "state", "--ledger", str(self.module), "--verify", "x.json", "--json"])
        self.assertEqual(code, 2, row)
        self.assertEqual(row["error_code"], "invalid_arguments")

    def test_state_still_requires_exactly_one_subject(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.entry(["module", "state", "--json"])
        self.assertEqual(code, 2)

    def test_routes_are_registered_inert_and_implemented(self):
        code, row = invoke(["manifest"])
        by_id = {r["id"]: r for r in row["result"]["routes"]}
        self.assertEqual(by_id["module.ledger-from-registry"]["effect"], "inert")
        self.assertEqual(by_id["module.ledger-from-registry"]["status"], "implemented")
        self.assertEqual(by_id["module.state"]["effect"], "inert")


class LedgerProposalTests(unittest.TestCase):
    """A workspace laid out like the private one, with the row shapes copied and every id,
    hash and path synthetic. The registry ids differ from the directory names on purpose,
    as they do for the recut modules."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.env = patch.dict(os.environ, {"PAT_HOME": str(self.root / "pat-home")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.write("workspace.json", {})
        self.write("foundations/bo2-stock.json", {"id": "bo2-stock", "profile_prefix": "stock", "maps": {"zm_transit": {}}})
        self.write("foundations/dlc5-beta2.json", {"id": "dlc5-beta2", "profile_prefix": "b2", "maps": {"zm_factory": {}, "zm_sumpf": {}}})
        self.write("modules/rw_gun/module.json", {"schema": 1, "id": "rw_gun", "version": "0.1.0", "bases": ["stock"], "maps": ["zm_transit"],
                                                  "recipe": "recipe.json",
                                                  "lineage": [{"game": "t5", "map": "zm_prototype", "source": "Chronicles Reawakened v3.5 ZIP", "note": "No T6 verification."}]})
        self.write("modules/rw_gun/docs/TEST.md", "# rw_gun\n\nbuild-02 receipt `.local/rw-gun/build-02/build.json`.\n")
        self.write("modules/rw_gun/docs/ACCEPTED.json", {
            "schema": 1, "subject": {"kind": "module", "id": "rw_gun"},
            "verdicts": [
                {"outcome": "rejected", "reporter": "Halo", "at": "2026-09-11T00:00:00Z", "quote": "felt like a one-second lag",
                 "scope": {"base": "stock", "foundation": "bo2-stock", "map": "zm_transit", "mode": "solo", "players": 1, "profile": "stock_rw_gun_test"},
                 "build": {"mod_ff_sha256": "da5976b1", "receipt": "build-01"}, "not_covered": []},
                {"outcome": "accepted", "reporter": "Halo", "at": "2026-09-12T02:55:00Z", "quote": "I just loaded in. Everything is good.",
                 "scope": {"base": "stock", "foundation": "bo2-stock", "map": "zm_transit", "mode": "solo", "players": 1, "profile": "stock_rw_gun_test"},
                 "build": {"mod_ff_sha256": SHA_A, "receipt": "build-02"}, "installation": {"run": "e41427497d1d46c4abdd743204e2b997"},
                 "not_covered": ["co-op", "other maps"]}]})
        self.write("modules/recut/module.json", {"schema": 1, "id": "recut", "version": "0.1.0", "bases": ["b2"], "maps": ["zm_factory"], "seed": "seed.json"})
        self.write("modules/recut/docs/TEST.md", "# recut\n")
        self.write("modules/recut/docs/ACCEPTED.json", {"schema": 1, "status": "historical-evidence-only", "current_candidate_player_accepted": False})
        self.write("modules/recut/docs/LINEAGE.json", {
            "schema": 1, "kind": "legacy-recut", "module_id": "recut", "foundation": "dlc5-beta2", "map": "zm_factory",
            "artifact_sha256": SHA_B, "build_receipt": ".local/wave2-spike/recut-build-03/build.json", "offline_verified": True,
            "installed": False, "launched": False, "runtime_verified": False, "captured": False, "player_accepted": False,
            "parent": {"source": "archive/t6/legacy-pack/.local/accepted/snapshot.json", "source_commit": "11ca21959a49d79d2075d8389357a596119403ec",
                       "mod_ff_sha256": SHA_P, "evidence_base": "dlc5-beta1", "map": "zm_factory"},
            "changes": ["Select only the weapon family and required roots."]})
        self.write(".local/wave2-spike/recut-build-03/build.json", {"status": "succeeded", "ok": True, "command": "module build"})
        self.write("archive/t6/legacy-pack/docs/VERIFIED_BUILD.json", {"status": "accepted_for_requested_scope", "accepted_on": "2026-09-05",
                                                                       "source_commit": "11ca21959a49d79d2075d8389357a596119403ec",
                                                                       "scope": "Recut on DLC5 Der Riese, solo", "map": "zm_factory", "foundation": "dlc5-beta1"})
        self.write("archive/t6/legacy-pack/docs/NOTES.md", "prose\n")
        self.write("modules/overlay/module.json", {"schema": 1, "id": "overlay", "version": "0.1.0", "bases": ["b2"], "maps": ["zm_sumpf"], "recipe": "recipe.json"})
        self.write("modules/overlay/docs/LINEAGE.json", {
            "schema": 1, "kind": "map-overlay", "module_id": "overlay", "foundation": "dlc5-beta2", "map": "zm_sumpf",
            "parent": {"module_id": "recut", "version": "0.1.0", "declaration": "modules/recut/module.json", "declaration_sha256": "c" * 64,
                       "mod_ff_sha256": SHA_B},
            "changes": ["Sumpf-only entrypoints calling parent activate functions."]})
        self.write("registry/t6-modules.json", {
            "schema_version": 1,
            "evidence": {"archive/t6/legacy-pack/docs/VERIFIED_BUILD.json": {"sha256": "0" * 64}},
            "modules": [
                {"id": "rw-gun", "status": "accepted-scoped", "modular": True, "standalone_module_verified": True,
                 "dependency_audit": "Build receipt resolves every reference against the stock zones.",
                 "evidence": ["modules/rw_gun/docs/TEST.md", "modules/rw_gun/docs/ACCEPTED.json"],
                 "build_revisions": [{"id": "stock-build-02", "sha256": SHA_A, "foundation": "bo2-stock", "map": "zm_transit",
                                      "offline_verified": True, "installed": True, "runtime_verified": True, "player_accepted": True,
                                      "evidence": "modules/rw_gun/docs/TEST.md"},
                                     {"id": "pack-build-01", "modules": ["rw_gun", "other"], "sha256": "5" * 64, "foundation": "bo2-stock",
                                      "map": "zm_transit", "offline_verified": True, "installed": True, "runtime_verified": True, "player_accepted": True}]},
                {"id": "arsenal-recut", "status": "accepted-scoped", "scope": "Accepted 17-family Der Riese pool.",
                 "modular": {"directory": "modules/recut", "foundation": "dlc5-beta2", "map": "zm_factory", "declaration": "modules/recut/module.json", "state": "offline-only"},
                 "standalone_module_verified": True,
                 "evidence": ["archive/t6/legacy-pack/docs/VERIFIED_BUILD.json", "archive/t6/legacy-pack/docs/NOTES.md", "modules/recut/docs/TEST.md"],
                 "build_revisions": [{"id": "b2-factory-recut-01", "modules": ["recut"], "sha256": SHA_B, "foundation": "dlc5-beta2", "map": "zm_factory",
                                      "offline_verified": True, "installed": False, "runtime_verified": False, "player_accepted": False,
                                      "receipt": ".local/wave2-spike/recut-build-03/build.json"}]},
                {"id": "overlay", "status": "pending", "modular": {"directory": "modules/overlay", "foundation": "dlc5-beta2", "map": "zm_sumpf"},
                 "standalone_module_verified": False,
                 "build_revisions": [{"id": "b2-sumpf-overlay-01", "modules": ["overlay"], "sha256": "6" * 64, "foundation": "dlc5-beta2", "map": "zm_sumpf",
                                      "offline_verified": True, "installed": False, "runtime_verified": False, "player_accepted": False,
                                      "receipt": "/somewhere/else/build.json"}]},
            ]})
        self.before = self.snapshot()

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) if not isinstance(value, str) else value, encoding="utf-8")
        return path

    def snapshot(self):
        return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob("*") if p.is_file() and "pat-home" not in p.parts}

    def propose(self, module_id):
        code, row = invoke(["module", "ledger-from-registry", str(self.root), module_id, "--dry-run", "--json"])
        self.assertEqual(code, 0, row)
        self.assertEqual(self.snapshot(), self.before, "the proposal wrote into the workspace")
        self.assertFalse((self.root / "modules" / module_id / "evidence.json").exists())
        result = row["result"]
        self.assertEqual(result["protocol"], "pat.module-ledger-proposal/1")
        self.assertFalse(result["written"])
        self.assertEqual(result["target"], f"modules/{module_id}/evidence.json")
        return result

    def test_stock_module_proposal_from_verdicts_and_build_revisions(self):
        result = self.propose("rw_gun")
        rows = result["proposal"]["rows"]
        self.assertEqual(result["registry_row"], "rw-gun")
        self.assertEqual([r["type"] for r in rows], ["lineage", "player-accepted", "player-accepted", "built-alone", "game-tested", "agent-reviewed"])
        self.assertEqual(rows[0], {"type": "lineage", "game": "t5", "map": "zm_prototype", "source": "Chronicles Reawakened v3.5 ZIP", "note": "No T6 verification."})
        rejected, accepted = rows[1], rows[2]
        self.assertEqual(rejected["outcome"], "rejected")
        self.assertNotIn("package_sha256", rejected, "a short hash is not a package hash")
        self.assertEqual(accepted["package_sha256"], SHA_A)
        self.assertEqual(accepted["scope"], {"base": "stock", "foundation": "bo2-stock", "maps": ["zm_transit"], "mode": "solo", "players": 1, "profile": "stock_rw_gun_test"})
        self.assertEqual(accepted["record"]["path"], "modules/rw_gun/docs/ACCEPTED.json")
        self.assertEqual(accepted["record"]["sha256"], hashlib.sha256((self.root / "modules/rw_gun/docs/ACCEPTED.json").read_bytes()).hexdigest())
        built = rows[3]
        self.assertEqual(built["scope"], {"base": "stock", "foundation": "bo2-stock", "maps": ["zm_transit"]})
        self.assertIs(built["offline_verified"], True)
        self.assertEqual(built["package_sha256"], SHA_A)
        tested = rows[4]
        self.assertEqual(tested["run"], "registry:stock-build-02")
        self.assertIs(tested["installed"], True)
        self.assertIs(tested["loaded_and_playable"], True)
        self.assertNotIn("launched", tested)
        self.assertNotIn("captured", tested)
        # The accepted verdict already covers this package: no duplicate player-accepted row.
        self.assertEqual(sum(r["type"] == "player-accepted" and r.get("package_sha256") == SHA_A for r in rows), 1)
        # The composition build revision contributes nothing.
        self.assertFalse(any(r.get("package_sha256") == "5" * 64 for r in rows))
        self.assertTrue(any("pack-build-01" in n and "composition build" in n for n in result["notes"]), result["notes"])
        self.assertTrue(any("short package hash" in n for n in result["notes"]))
        self.assertTrue(any("no receipt" in n for n in result["notes"]))
        self.assertEqual(result["validation"], "valid", result["diagnostics"])
        self.assertEqual(values(result["derived"]["facts"]), {"offline_verified": True, "installed": True, "launched": None,
                                                             "loaded_and_playable": True, "captured": None, "player_accepted": True})
        self.assertEqual(result["sources"]["modules/rw_gun/docs/TEST.md"], hashlib.sha256((self.root / "modules/rw_gun/docs/TEST.md").read_bytes()).hexdigest())

    def test_recut_proposal_keeps_pack_history_as_history(self):
        result = self.propose("recut")
        rows = result["proposal"]["rows"]
        self.assertEqual(result["registry_row"], "arsenal-recut")
        self.assertEqual([r["type"] for r in rows], ["built-alone", "accepted-in-pack", "extracted-from-release", "agent-reviewed"])
        built = rows[0]
        self.assertEqual(built["receipt"], {"path": ".local/wave2-spike/recut-build-03/build.json",
                                            "sha256": hashlib.sha256((self.root / ".local/wave2-spike/recut-build-03/build.json").read_bytes()).hexdigest()})
        self.assertEqual(built["scope"], {"base": "b2", "foundation": "dlc5-beta2", "maps": ["zm_factory"]})
        pack = rows[1]
        self.assertEqual(pack["pack"], "legacy-pack")
        self.assertEqual(pack["scope"], {"foundation": "dlc5-beta1", "maps": ["zm_factory"]})
        self.assertEqual(pack["at"], "2026-09-05")
        self.assertEqual(pack["record"]["path"], "archive/t6/legacy-pack/docs/VERIFIED_BUILD.json")
        self.assertTrue(any("registry records sha256" in n for n in result["notes"]), "the registry's stale hash is reported")
        self.assertTrue(any("NOTES.md is prose" in n for n in result["notes"]))
        release = rows[2]
        self.assertEqual(release["commit"], "11ca21959a49d79d2075d8389357a596119403ec")
        self.assertEqual(release["package_sha256"], SHA_P)
        self.assertEqual(release["scope"]["foundation"], "dlc5-beta1")
        self.assertEqual(rows[3]["scope"], {"base": "b2", "foundation": "dlc5-beta2", "maps": ["zm_factory"]})
        self.assertEqual(result["validation"], "valid", result["diagnostics"])
        facts = result["derived"]["facts"]
        self.assertIs(facts["offline_verified"]["value"], True)
        self.assertIsNone(facts["player_accepted"]["value"], "the pack acceptance never becomes the module's own")
        self.assertEqual(result["derived"]["history"]["accepted-in-pack"], 1)
        self.assertTrue(any("no verdicts list" in n for n in result["notes"]))

    def test_overlay_proposal_cites_its_parent_and_flags_an_outside_receipt(self):
        result = self.propose("overlay")
        rows = result["proposal"]["rows"]
        self.assertEqual([r["type"] for r in rows], ["built-alone", "authored"])
        self.assertEqual(rows[0]["receipt"], {"path": "/somewhere/else/build.json"})
        self.assertEqual(result["validation"], "invalid")
        self.assertEqual(result["diagnostics"][0]["field"], "/rows/0/receipt/path")
        self.assertTrue(any("outside the workspace" in n for n in result["notes"]))
        authored = rows[1]
        self.assertEqual(authored["parent"]["id"], "recut")
        self.assertEqual(authored["parent"]["package_sha256"], SHA_B)
        self.assertEqual(authored["parent"]["declaration_sha256"], "c" * 64)
        self.assertEqual(authored["parent"]["record"]["path"], "modules/recut/module.json")
        self.assertEqual(authored["scope"], {"base": "b2", "foundation": "dlc5-beta2", "maps": ["zm_sumpf"]})
        self.assertEqual(authored["changes"], ["Sumpf-only entrypoints calling parent activate functions."])
        self.assertIsNotNone(result["derived"], "facts are derived from the rows that validate")
        self.assertIsNone(result["derived"]["facts"]["offline_verified"]["value"])

    def test_unknown_module_and_missing_registry_row(self):
        code, row = invoke(["module", "ledger-from-registry", str(self.root), "missing", "--json"])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_missing")
        code, row = invoke(["module", "ledger-from-registry", str(self.root), "Bad Id", "--json"])
        self.assertEqual(code, 2, row)
        self.write("modules/lonely/module.json", {"schema": 1, "id": "lonely", "version": "1", "bases": ["stock"], "maps": ["*"], "recipe": "recipe.json"})
        self.before = self.snapshot()
        result = self.propose("lonely")
        self.assertIsNone(result["registry_row"])
        self.assertEqual(result["proposal"]["rows"], [])
        self.assertTrue(any("no row for lonely" in n for n in result["notes"]))
        self.assertEqual(values(result["derived"]["facts"]), dict.fromkeys(ledger.FACTS))

    def test_existing_ledger_is_noted_and_never_overwritten(self):
        self.write("modules/rw_gun/evidence.json", LEDGER)
        self.before = self.snapshot()
        result = self.propose_existing("rw_gun")
        self.assertTrue(any("already exists" in n for n in result["notes"]))

    def propose_existing(self, module_id):
        code, row = invoke(["module", "ledger-from-registry", str(self.root), module_id, "--json"])
        self.assertEqual(code, 0, row)
        self.assertEqual(self.snapshot(), self.before)
        return row["result"]


if __name__ == "__main__":
    unittest.main()
