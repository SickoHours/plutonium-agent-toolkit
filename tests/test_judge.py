"""``pat judge`` with the hosted API replaced by a fake. No network, no game, no key.

Every test that reaches ``eval`` substitutes ``judge._send``; a test that forgets to would fail
by trying to reach api.typesafe.ai, so the substitution is the contract this file relies on.
The shipped ``crash-triage`` set is used end to end; the corner cases of section 3.1 use small
synthetic sets so they do not move when the shipped set does.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from plutonium_agent_toolkit.cli import entry
from plutonium_agent_toolkit.core.errors import Failure
from plutonium_agent_toolkit.dev import judge

ROOT = Path(__file__).resolve().parents[1]
KEY = "test-key-never-real"


def invoke(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = entry(argv)
    return code, json.loads(buf.getvalue()), buf.getvalue()


def small_set(**over) -> dict:
    data = {
        "schema": 1, "id": "fixture", "title": "A fixture set", "model": "jev-latest",
        "state": {"fields": {"crash_text": "The crash text", "console_before_crash": "Console lines"},
                  "max_bytes": 4096, "redact": True},
        "questions": {
            "culprit_kind": {"type": "choice", "instructions": "What kind of thing caused it?",
                             "criteria": {"script_logic": "A script read an undefined value",
                                          "hard_limit": "The engine hit a fixed capacity"}},
            "catalog_gap": {"type": "noul", "instructions": "Is there a message no catalog row matches?",
                            "criteria": {"true": "A message in words, unmatched", "false": "A row matches, or there is no message"}},
        },
        "policy": {"act": 0.85, "ask": 0.5},
    }
    data.update(over)
    return data


def case(case_id="c1", crash="line one\nline two", console="(not available)", absent=("console_before_crash",), expected=None):
    return {"id": case_id, "state": {"crash_text": crash, "console_before_crash": console},
            "absent": list(absent), "expected": expected if expected is not None else {}}


def answer_noul(value):
    return {"type": "noul", "noul": value}


def answer_choice(choice, probabilities):
    return {"type": "choice", "choice": choice, "confidence": max(probabilities.values()),
            "probabilities": probabilities}


class FakeApi:
    """Stands in for ``judge._send``: records what was sent, replies from a per-case script."""

    def __init__(self, reply):
        self.reply = reply
        self.sent = []

    def __call__(self, body, key, timeout):
        request = json.loads(body)
        self.sent.append({"body": body, "key": key, "timeout": timeout, "request": request})
        payload = self.reply(request, len(self.sent) - 1)
        return 200, json.dumps(payload).encode("utf-8")


class Temp(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self._key = os.environ.get(judge.KEY_ENV)
        os.environ[judge.KEY_ENV] = KEY
        self.addCleanup(self._restore_key)

    def _restore_key(self):
        if self._key is None:
            os.environ.pop(judge.KEY_ENV, None)
        else:
            os.environ[judge.KEY_ENV] = self._key

    def patch_api(self, reply):
        api = FakeApi(reply)
        original = judge._send
        judge._send = api
        self.addCleanup(lambda: setattr(judge, "_send", original))
        return api

    def cases_file(self, cases, set_id="crash-triage", name="cases.json") -> Path:
        path = self.dir / name
        path.write_text(json.dumps({"schema": 1, "set": set_id, "cases": cases}), encoding="utf-8")
        return path


# ----- the inert routes -------------------------------------------------------------------

class ListAndShowTests(Temp):
    def test_list_names_every_shipped_set_with_its_id_and_title(self):
        code, row, _ = invoke(["judge", "list"])
        self.assertEqual(code, 0)
        rows = row["result"]["sets"]
        on_disk = sorted(p.stem for p in (ROOT / "src/plutonium_agent_toolkit/knowledge/judge").glob("*.json"))
        self.assertEqual([r["id"] for r in rows], on_disk)
        for entry_row in rows:
            self.assertTrue(entry_row["title"].strip())
            self.assertEqual(entry_row["file"], entry_row["id"] + ".json")

    def test_show_prints_the_set_as_it_ships(self):
        code, row, _ = invoke(["judge", "show", "crash-triage"])
        self.assertEqual(code, 0)
        shipped = json.loads((ROOT / "src/plutonium_agent_toolkit/knowledge/judge/crash-triage.json").read_text(encoding="utf-8"))
        self.assertEqual(row["result"]["set"], shipped)

    def test_an_unknown_set_says_which_sets_exist(self):
        code, row, _ = invoke(["judge", "show", "not-a-set"])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "input_missing")
        self.assertIn("crash-triage", row["hint"])

    def test_the_shipped_set_passes_its_own_validator(self):
        data, path = judge.load_set("crash-triage")
        self.assertEqual(data["id"], "crash-triage")
        self.assertEqual(path.name, "crash-triage.json")


# ----- section 3.1: criteria built at run time ---------------------------------------------

class CriteriaTests(Temp):
    def test_knowledge_form_offers_every_catalog_row_plus_the_no_match_option(self):
        question = {"type": "choice", "instructions": "which row",
                    "criteria_from": {"knowledge": "crash-signatures.json", "key": "id",
                                      "describe": "{cause} (log pattern: {regex})",
                                      "plus": {"none": "No catalog row describes this failure"}}}
        criteria, how = judge.materialize_criteria(question, {"crash_text": "x"}, "signature")
        rows = judge.knowledge.load("crash-signatures.json")["rows"]
        self.assertEqual(len(criteria), len(rows) + 1)
        self.assertEqual(how, {"form": "knowledge", "source": "crash-signatures.json", "built": len(rows), "plus": ["none"]})
        first = rows[0]
        self.assertEqual(criteria[first["id"]], f"{first['cause']} (log pattern: {first['regex']})")
        self.assertEqual(criteria["none"], "No catalog row describes this failure")

    def test_knowledge_form_refuses_a_describe_naming_a_field_the_row_lacks(self):
        question = {"type": "choice", "instructions": "which row",
                    "criteria_from": {"knowledge": "crash-signatures.json", "key": "id", "describe": "{nope}"}}
        with self.assertRaises(Failure) as caught:
            judge.materialize_criteria(question, {}, "signature")
        self.assertEqual(caught.exception.code, "input_invalid")

    def test_state_lines_numbers_the_field_and_skips_blank_lines(self):
        question = {"type": "choice", "instructions": "which line",
                    "criteria_from": {"state_lines": "crash_text", "plus": {"none": "No single line justifies the answer"}}}
        state = {"crash_text": "first\n\n   \nfourth"}
        criteria, how = judge.materialize_criteria(question, state, "evidence_line")
        self.assertEqual(criteria, {"1": "first", "4": "fourth", "none": "No single line justifies the answer"})
        self.assertEqual(how["form"], "state_lines")
        self.assertEqual(how["built"], 2)

    def test_state_regex_offers_each_named_script_once_in_the_order_seen(self):
        question = {"type": "choice", "instructions": "who owns it",
                    "criteria_from": {"state_regex": r"[a-z0-9_/]+::[a-z0-9_]+|maps/mp/[a-z0-9_/]+",
                                      "fields": ["crash_text", "console_before_crash"],
                                      "plus": {"none_named": "No script is named"}}}
        state = {"crash_text": "last gsc pos 0x1 maps/mp/zombies/_zm_weap::watch\nagain maps/mp/zombies/_zm_weap::watch",
                 "console_before_crash": "loaded maps/mp/_visionset_mgr::monitor"}
        criteria, how = judge.materialize_criteria(question, state, "owner_script")
        self.assertEqual(list(criteria), ["maps/mp/zombies/_zm_weap::watch", "maps/mp/_visionset_mgr::monitor", "none_named"])
        self.assertIn("crash_text line 1", criteria["maps/mp/zombies/_zm_weap::watch"])
        self.assertIn("console_before_crash line 1", criteria["maps/mp/_visionset_mgr::monitor"])
        self.assertEqual(how["built"], 2)

    def test_a_state_that_names_nothing_leaves_the_question_unasked_rather_than_a_choice_of_one(self):
        question = {"type": "choice", "instructions": "who owns it",
                    "criteria_from": {"state_regex": r"maps/mp/[a-z_/]+", "fields": ["crash_text"],
                                      "plus": {"none_named": "No script is named"}}}
        criteria, how = judge.materialize_criteria(question, {"crash_text": "no script here"}, "owner_script")
        self.assertIsNone(criteria)
        self.assertIn("no-match option", how["not_asked"])

    def test_the_api_rules_for_each_criteria_type_are_checked_before_anything_is_sent(self):
        with self.assertRaises(Failure):                      # a noul needs both texts
            judge._check_criteria({"true": "yes"}, "noul", "q")
        with self.assertRaises(Failure):                      # a score needs two ordered levels
            judge._check_criteria(["only one"], "score", "q")
        with self.assertRaises(Failure):                      # a choice needs two options
            judge._check_criteria({"one": "only"}, "choice", "q")
        self.assertEqual(judge._check_criteria(["low", "high"], "score", "q"), ["low", "high"])


# ----- state: absent, redacted, bounded -----------------------------------------------------

class StateTests(Temp):
    def test_an_absent_field_is_sent_as_not_available_and_recorded(self):
        data = judge.validate_set(small_set(), "fixture")
        state, notes = judge.materialize_state(data, {"id": "c", "state": {"crash_text": "boom"}, "absent": ["console_before_crash"]})
        self.assertEqual(state["console_before_crash"], "(not available)")
        self.assertEqual(notes["absent"], ["console_before_crash"])

    def test_a_field_missing_or_empty_counts_as_absent_even_when_the_case_forgot_to_say_so(self):
        data = judge.validate_set(small_set(), "fixture")
        state, notes = judge.materialize_state(data, {"id": "c", "state": {"crash_text": "boom", "console_before_crash": "   "}})
        self.assertEqual(state["console_before_crash"], "(not available)")
        self.assertEqual(notes["absent"], ["console_before_crash"])

    def test_every_line_the_private_pattern_matches_is_replaced_whole(self):
        data = judge.validate_set(small_set(), "fixture")
        text = ("Exception Code: 0xC0000005\n"
                "connecting to 203.0.113.9 with ticket ABCDEF\n"
                "Authorization: Bearer sk-not-a-real-key\n"
                "sv_password hunter2\n"
                "last gsc error message 'cannot cast undefined to bool'")
        state, notes = judge.materialize_state(data, {"id": "c", "state": {"crash_text": text}, "absent": ["console_before_crash"]})
        self.assertEqual(state["crash_text"].splitlines(),
                         ["Exception Code: 0xC0000005", "(redacted)", "(redacted)", "(redacted)",
                          "last gsc error message 'cannot cast undefined to bool'"])
        self.assertEqual(notes["redacted_lines"], {"crash_text": 3})
        for secret in ("ABCDEF", "sk-not-a-real-key", "hunter2", "203.0.113.9"):
            self.assertNotIn(secret, json.dumps(state))

    def test_a_set_that_does_not_ask_for_redaction_gets_none(self):
        data = judge.validate_set(small_set(state={"fields": {"crash_text": "The crash text"}, "max_bytes": 4096, "redact": False}))
        state, notes = judge.materialize_state(data, {"id": "c", "state": {"crash_text": "connect with ticket X"}})
        self.assertEqual(state["crash_text"], "connect with ticket X")
        self.assertEqual(notes["redacted_lines"], {})

    def test_state_over_max_bytes_is_cut_from_the_end_and_the_cut_is_recorded(self):
        data = judge.validate_set(small_set(state={"fields": {"crash_text": "The crash text", "console_before_crash": "Console"},
                                                   "max_bytes": 300, "redact": True}))
        long_console = "\n".join(f"line {n}" for n in range(200))
        state, notes = judge.materialize_state(data, {"id": "c", "state": {"crash_text": "head of the crash", "console_before_crash": long_console}})
        self.assertLessEqual(judge.encoded_length(state), 300)
        self.assertEqual(state["crash_text"], "head of the crash")           # the short field is untouched
        self.assertTrue(state["console_before_crash"].startswith("line 0"))  # the head is what is kept
        self.assertTrue(state["console_before_crash"].endswith("(truncated)"))
        self.assertEqual(notes["truncated"]["console_before_crash"]["characters"], len(long_console))
        self.assertLess(notes["truncated"]["console_before_crash"]["kept_characters"], len(long_console))

    def test_only_the_declared_fields_are_sent_and_the_rest_are_recorded(self):
        data = judge.validate_set(small_set(), "fixture")
        state, notes = judge.materialize_state(data, {"id": "c", "state": {"crash_text": "boom", "secret_notes": "not declared"}})
        self.assertEqual(sorted(state), ["console_before_crash", "crash_text"])
        self.assertEqual(notes["ignored_fields"], ["secret_notes"])


# ----- scoring, section 5 --------------------------------------------------------------------

class ScoringTests(Temp):
    def rows(self):
        return [
            {"case": "agreeing", "expected": {"culprit_kind": "script_logic", "catalog_gap": False},
             "answers": {"culprit_kind": judge.read_answer("culprit_kind", "choice",
                                                           answer_choice("script_logic", {"script_logic": 0.9, "hard_limit": 0.07, "x": 0.03}), "agreeing"),
                         "catalog_gap": judge.read_answer("catalog_gap", "noul", answer_noul(0.02), "agreeing")},
             "usage": {"input_tokens": 100, "output_tokens": 10}},
            {"case": "confident-and-wrong", "expected": {"culprit_kind": "hard_limit", "catalog_gap": True},
             "answers": {"culprit_kind": judge.read_answer("culprit_kind", "choice",
                                                           answer_choice("script_logic", {"script_logic": 0.99, "hard_limit": 0.01}), "confident-and-wrong"),
                         "catalog_gap": judge.read_answer("catalog_gap", "noul", answer_noul(0.4), "confident-and-wrong")},
             "usage": {"input_tokens": 120, "output_tokens": 12}},
            {"case": "unlabeled", "expected": {},
             "answers": {"culprit_kind": judge.read_answer("culprit_kind", "choice",
                                                           answer_choice("hard_limit", {"hard_limit": 0.6, "script_logic": 0.4}), "unlabeled"),
                         "catalog_gap": judge.read_answer("catalog_gap", "noul", answer_noul(0.55), "unlabeled")},
             "usage": {"input_tokens": 90, "output_tokens": 9}},
        ]

    def test_counts_means_and_confident_and_wrong_per_question(self):
        scores = judge.score_run(judge.validate_set(small_set(), "fixture"), "jev-1.13.0", self.rows())
        choice = scores["questions"]["culprit_kind"]
        self.assertEqual((choice["cases"], choice["labeled"], choice["agree"], choice["disagree"], choice["unknown"]), (3, 2, 1, 1, 1))
        self.assertEqual(choice["mean_confidence_agree"], 0.9)
        self.assertEqual(choice["mean_confidence_disagree"], 0.99)
        self.assertEqual(choice["confident_and_wrong"], 1)                  # 0.99 is above policy.act 0.85
        self.assertEqual(scores["totals"]["confident_and_wrong"], 1)
        self.assertEqual(scores["usage"], {"requests": 3, "input_tokens": 310, "output_tokens": 31})

    def test_an_unlabeled_question_is_unknown_not_wrong(self):
        scores = judge.score_run(judge.validate_set(small_set(), "fixture"), "jev-1.13.0", self.rows())
        row = [r for r in scores["questions"]["culprit_kind"]["rows"] if r["case"] == "unlabeled"][0]
        self.assertEqual(row["verdict"], "unknown")
        self.assertIsNone(row["expected"])
        self.assertEqual(scores["questions"]["culprit_kind"]["unknown"], 1)

    def test_a_noul_agrees_on_the_side_of_one_half_and_reports_the_probability_of_that_side(self):
        scores = judge.score_run(judge.validate_set(small_set(), "fixture"), "jev-1.13.0", self.rows())
        by_case = {r["case"]: r for r in scores["questions"]["catalog_gap"]["rows"]}
        self.assertEqual((by_case["agreeing"]["answer"], by_case["agreeing"]["verdict"]), (False, "agree"))
        self.assertEqual(by_case["agreeing"]["confidence"], 0.98)           # answered false, so 1 - noul
        self.assertEqual(by_case["agreeing"]["noul"], 0.02)
        self.assertEqual((by_case["confident-and-wrong"]["answer"], by_case["confident-and-wrong"]["verdict"]), (False, "disagree"))
        self.assertEqual(scores["questions"]["catalog_gap"]["confident_and_wrong"], 0)   # 0.6 is below act

    def test_each_case_row_carries_the_top_three_probabilities(self):
        scores = judge.score_run(judge.validate_set(small_set(), "fixture"), "jev-1.13.0", self.rows())
        row = [r for r in scores["questions"]["culprit_kind"]["rows"] if r["case"] == "agreeing"][0]
        self.assertEqual(row["top"], [{"option": "script_logic", "probability": 0.9},
                                      {"option": "hard_limit", "probability": 0.07},
                                      {"option": "x", "probability": 0.03}])

    def test_a_label_of_the_wrong_kind_is_refused_instead_of_scored(self):
        rows = self.rows()
        rows[0]["expected"]["catalog_gap"] = "yes"
        with self.assertRaises(Failure) as caught:
            judge.score_run(judge.validate_set(small_set(), "fixture"), "jev-1.13.0", rows)
        self.assertEqual(caught.exception.code, "input_invalid")

    def test_an_answer_of_another_type_than_the_question_is_refused(self):
        with self.assertRaises(Failure):
            judge.read_answer("catalog_gap", "noul", answer_choice("x", {"x": 1.0}), "c")


# ----- the job --------------------------------------------------------------------------------

def one_reply(request, index):
    """An answer for every question the request actually carries."""
    answers = {}
    for qid, question in request["questions"].items():
        if question["type"] == "noul":
            answers[qid] = answer_noul(0.1)
        elif question["type"] == "choice":
            options = list(question["criteria"])
            answers[qid] = answer_choice(options[0], {options[0]: 0.8, options[1]: 0.2})
    return {"model": "jev-1.13.0", "answers": answers, "usage": {"input_tokens": 1000, "output_tokens": 20}}


class EvalJobTests(Temp):
    def test_dry_run_writes_the_requests_sends_nothing_and_scores_nothing(self):
        api = self.patch_api(one_reply)
        cases = self.cases_file([case("c1", crash="last gsc pos 0x1 maps/mp/_visionset_mgr::monitor")])
        out = self.dir / "run"
        code, row, _ = invoke(["judge", "eval", "crash-triage", "--cases", str(cases), "--output", str(out), "--dry-run"])
        self.assertEqual(code, 0, row)
        self.assertEqual(api.sent, [])
        self.assertTrue((out / "request-c1.json").is_file())
        self.assertFalse((out / "response-c1.json").exists())
        self.assertFalse((out / "scores.json").exists())
        self.assertTrue(row["result"]["dry_run"])
        self.assertNotIn("scores", row["result"])

    def test_a_dry_run_needs_no_key(self):
        os.environ.pop(judge.KEY_ENV, None)
        cases = self.cases_file([case("c1")])
        code, row, _ = invoke(["judge", "eval", "crash-triage", "--cases", str(cases), "--output", str(self.dir / "run"), "--dry-run"])
        self.assertEqual(code, 0, row)

    def test_a_missing_key_is_its_own_stable_code_and_nothing_is_written_or_sent(self):
        api = self.patch_api(one_reply)
        os.environ.pop(judge.KEY_ENV, None)
        cases = self.cases_file([case("c1")])
        out = self.dir / "run"
        code, row, text = invoke(["judge", "eval", "crash-triage", "--cases", str(cases), "--output", str(out)])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "judge_key_missing")
        self.assertEqual(api.sent, [])
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["receipt.json"])
        self.assertIn(judge.KEY_ENV, text)

    def test_an_existing_output_directory_is_refused(self):
        self.patch_api(one_reply)
        cases = self.cases_file([case("c1")])
        out = self.dir / "run"
        out.mkdir()
        code, row, _ = invoke(["judge", "eval", "crash-triage", "--cases", str(cases), "--output", str(out)])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "output_exists")
        self.assertEqual(list(out.iterdir()), [])

    def test_a_cases_file_for_another_set_is_refused(self):
        self.patch_api(one_reply)
        cases = self.cases_file([case("c1")], set_id="another-set")
        code, row, _ = invoke(["judge", "eval", "crash-triage", "--cases", str(cases), "--output", str(self.dir / "run")])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "input_invalid")

    def test_a_real_run_writes_the_exact_bytes_it_sent_the_reply_and_the_scores(self):
        api = self.patch_api(one_reply)
        cases = self.cases_file([
            case("c1", crash="last gsc error message 'cannot cast undefined to bool'\nlast gsc pos 0x1 maps/mp/_visionset_mgr::monitor",
                 expected={"culprit_kind": "script_logic", "catalog_gap": False}),
            case("c2", crash="last com error message 'G_Spawn: no free entities'\nlast gsc pos 0x2 ::forge_probe_run",
                 expected={"culprit_kind": "hard_limit"}),
        ])
        out = self.dir / "run"
        code, row, text = invoke(["judge", "eval", "crash-triage", "--cases", str(cases), "--output", str(out), "--model", "jev-latest", "--timeout", "30"])
        self.assertEqual(code, 0, row)
        self.assertEqual(len(api.sent), 2)
        # The file holds the bytes that went out, byte for byte, and it was written before the send.
        for index, case_id in enumerate(("c1", "c2")):
            self.assertEqual((out / f"request-{case_id}.json").read_bytes(), api.sent[index]["body"])
            self.assertEqual(json.loads((out / f"response-{case_id}.json").read_text())["model"], "jev-1.13.0")
        self.assertEqual({row_["key"] for row_ in api.sent}, {KEY})
        self.assertEqual({row_["timeout"] for row_ in api.sent}, {30})
        scores = json.loads((out / "scores.json").read_text())
        self.assertEqual(scores["set"], "crash-triage")
        self.assertEqual(scores["model"], "jev-1.13.0")
        self.assertEqual(scores["cases"], 2)
        self.assertEqual(sorted(scores["questions"]), ["culprit_kind", "evidence_line", "has_message_in_words", "owner_script", "signature"])
        self.assertEqual(row["result"]["scores"], scores)
        self.assertTrue((out / "judge.log").is_file())

    def test_a_question_the_state_cannot_offer_options_for_is_not_asked_and_not_counted_wrong(self):
        api = self.patch_api(one_reply)
        cases = self.cases_file([case("c2", crash="last com error message 'G_Spawn: no free entities'\nlast gsc pos 0x2 ::forge_probe_run")])
        out = self.dir / "run"
        code, row, _ = invoke(["judge", "eval", "crash-triage", "--cases", str(cases), "--output", str(out)])
        self.assertEqual(code, 0, row)
        self.assertNotIn("owner_script", api.sent[0]["request"]["questions"])
        owner = json.loads((out / "scores.json").read_text())["questions"]["owner_script"]
        self.assertEqual((owner["not_asked"], owner["labeled"], owner["disagree"]), (1, 0, 0))
        self.assertEqual(owner["rows"][0]["verdict"], "not-asked")

    def test_neither_the_key_nor_the_state_ever_reaches_stdout(self):
        self.patch_api(one_reply)
        secret_line = "connecting with ticket SUPERSECRET"
        cases = self.cases_file([case("c1", crash=f"Exception Code: 0xC0000005\n{secret_line}\nlast gsc pos 0x1 maps/mp/_visionset_mgr::monitor")])
        out = self.dir / "run"
        code, row, text = invoke(["judge", "eval", "crash-triage", "--cases", str(cases), "--output", str(out)])
        self.assertEqual(code, 0, row)
        for forbidden in (KEY, "SUPERSECRET", "Exception Code"):
            self.assertNotIn(forbidden, text)
        # Nor does the redacted line reach the request, the log or the receipt.
        for path in out.iterdir():
            self.assertNotIn("SUPERSECRET", path.read_text(encoding="utf-8"), path.name)
            self.assertNotIn(KEY, path.read_text(encoding="utf-8"), path.name)

    def test_the_receipt_hashes_the_set_and_the_cases_file_it_read(self):
        self.patch_api(one_reply)
        cases = self.cases_file([case("c1")])
        out = self.dir / "run"
        code, row, _ = invoke(["judge", "eval", "crash-triage", "--cases", str(cases), "--output", str(out)])
        self.assertEqual(code, 0, row)
        receipt = json.loads((out / "receipt.json").read_text())
        self.assertEqual(receipt["status"], "succeeded")
        self.assertIn(str(cases.resolve()), receipt["inputs"])
        self.assertIn(str(judge.set_path("crash-triage")), receipt["inputs"])

    def test_an_http_refusal_fails_the_job_with_its_own_code_and_keeps_the_evidence(self):
        def refuse(body, key, timeout):
            return 401, b'{"error":"unauthorized"}'

        original = judge._send
        judge._send = refuse
        self.addCleanup(lambda: setattr(judge, "_send", original))
        cases = self.cases_file([case("c1")])
        out = self.dir / "run"
        code, row, _ = invoke(["judge", "eval", "crash-triage", "--cases", str(cases), "--output", str(out)])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "judge_key_missing")
        self.assertTrue((out / "request-c1.json").is_file())
        self.assertEqual(json.loads((out / "receipt.json").read_text())["status"], "failed")


class TransportTests(Temp):
    def test_the_request_carries_the_bearer_the_json_body_and_no_redirect_is_followed(self):
        seen = {}

        class FakeResponse:
            status = 200

            def read(self, *args):
                return b'{"model":"jev-1.13.0","answers":{},"usage":{}}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class FakeOpener:
            def open(self, request, timeout=None):
                seen["url"] = request.full_url
                seen["method"] = request.get_method()
                seen["headers"] = dict(request.header_items())
                seen["body"] = request.data
                seen["timeout"] = timeout
                return FakeResponse()

        original = judge._opener
        judge._opener = lambda: FakeOpener()
        self.addCleanup(lambda: setattr(judge, "_opener", original))
        status, payload = judge._send(b'{"model":"jev-latest"}', KEY, 30)
        self.assertEqual((status, seen["url"], seen["method"], seen["timeout"]), (200, judge.API_URL, "POST", 30))
        self.assertEqual(seen["headers"]["Authorization"], f"Bearer {KEY}")
        self.assertEqual(seen["headers"]["Content-type"], "application/json")
        self.assertEqual(seen["body"], b'{"model":"jev-latest"}')
        self.assertIn(b"jev-1.13.0", payload)
        self.assertIsNone(judge._NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://elsewhere.example"))

    def test_the_endpoint_is_the_documented_https_one(self):
        self.assertEqual(judge.API_URL, "https://api.typesafe.ai/v1/systemone")


class RouteTests(Temp):
    def test_every_judge_route_is_registered_and_describable(self):
        for action in ("list", "show", "eval"):
            code, row, _ = invoke(["describe", "judge", action])
            self.assertEqual(code, 0)
            self.assertEqual(row["result"]["id"], f"judge.{action}")
            self.assertEqual(row["result"]["status"], "implemented")
        code, row, _ = invoke(["describe", "judge", "eval"])
        self.assertEqual(row["result"]["effect"], "writes-output")
        self.assertIn("TYPESAFE_API_KEY", row["result"]["notes"])

    def test_the_docs_say_the_route_is_opt_in_and_sends_state_to_a_hosted_api(self):
        text = (ROOT / "docs/JUDGE.md").read_text(encoding="utf-8")
        for claim in ("opt-in", "api.typesafe.ai", "redact"):
            self.assertIn(claim, text.lower())
        self.assertIn("contributors/JUDGE.md", text)


if __name__ == "__main__":
    unittest.main()


class StructuredState(unittest.TestCase):
    def test_object_and_list_fields_are_sent_as_json_text(self):
        from plutonium_agent_toolkit.dev import judge
        question_set = {"state": {"fields": {"declaration": "x", "file_list": "y", "readme_head": "z"}, "max_bytes": 4096, "redact": True}}
        case = {"state": {"declaration": {"title": "Juggernog", "maps": ["zm_factory"]}, "file_list": ["README.md", "module.json"], "readme_head": "# Juggernog"}}
        state, notes = judge.materialize_state(question_set, case)
        self.assertIn('"title": "Juggernog"', state["declaration"])
        self.assertIn('"module.json"', state["file_list"])
        self.assertEqual(notes["absent"], [])
