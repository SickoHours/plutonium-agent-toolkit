"""``work start|step|ask|answer|status``: a person's ask, an agent's spine, the questions between."""
import contextlib
import hashlib
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from plutonium_agent_toolkit.cli import entry
from plutonium_agent_toolkit.core.discovery import find


def invoke(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = entry(argv)
    return code, json.loads(buf.getvalue())


class WorkFixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.ws = self.root / "ws"
        (self.ws / "modules" / "gums").mkdir(parents=True)
        (self.ws / "modules" / "gums" / "module.json").write_text('{"id": "gums"}')
        (self.ws / "jobs").mkdir()
        self.n = 0
        self.saved = os.environ.get("PAT_HOME")
        os.environ["PAT_HOME"] = str(self.root / "home")
        self.addCleanup(self._restore)

    def _restore(self):
        if self.saved is None:
            os.environ.pop("PAT_HOME", None)
        else:
            os.environ["PAT_HOME"] = self.saved

    def out(self):
        self.n += 1
        return str(self.ws / "jobs" / f"work-{self.n:03d}")

    def start(self, *extra, target="dlc5-beta2/zm_sumpf/zclassic"):
        out = self.out()
        code, row = invoke(["work", "start", str(self.ws), "--title", "Gums on Sumpf", "--want", "the gum machine on Sumpf",
                            "--target", target, *extra, "--output", out, "--json"])
        return code, row, Path(out)

    def request(self, **over):
        data = {"question": "Which base?", "step": "placement",
                "options": [{"key": "stock", "label": "BO2 stock", "implies": "TranZit first"},
                            {"key": "b2", "label": "DLC5 Beta 2"}], "default": "b2"}
        data.update(over)
        path = self.root / f"request-{self.n}-{len(os.listdir(self.root))}.json"
        path.write_text(json.dumps(data))
        return str(path)

    @staticmethod
    def sha(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class StartTests(WorkFixture):
    def test_form_door_writes_the_order_and_a_receipt(self):
        code, row, work = self.start("--by", "Halo")
        self.assertEqual(code, 0, row)
        order = json.loads((work / "work.json").read_text(encoding="utf-8"))
        self.assertEqual(order["door"], "form")
        self.assertIsNone(order["subject"])
        self.assertEqual(order["donor"], {"kind": "none", "ref": None})
        self.assertEqual(order["want"], "the gum machine on Sumpf")
        self.assertEqual(order["target"], "dlc5-beta2/zm_sumpf/zclassic")
        self.assertRegex(order["id"], r"^[a-f0-9]{16}$")
        receipt = json.loads((work / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "succeeded")
        self.assertIn("work.json", receipt["outputs"])
        self.assertEqual(row["result"]["order"], order)
        self.assertIn("pat work step", row["result"]["next"])

    def test_shelf_door_names_a_subject_that_exists(self):
        code, row, work = self.start("--subject", "modules/gums", "--donor", "Reawakened v3.5", "--donor-kind", "release")
        self.assertEqual(code, 0, row)
        order = row["result"]["order"]
        self.assertEqual(order["door"], "shelf")
        self.assertEqual(order["subject"], "modules/gums")
        self.assertEqual(order["donor"], {"kind": "release", "ref": "Reawakened v3.5"})
        code, row, work = self.start("--subject", "modules/nothing")
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "input_missing")
        self.assertFalse((work / "work.json").exists())
        self.assertEqual(json.loads((work / "receipt.json").read_text())["status"], "failed")

    def test_a_donor_path_defaults_to_kind_path_and_a_subject_must_stay_inside(self):
        code, row, _ = self.start("--donor", "donors/gums-t5")
        self.assertEqual(row["result"]["order"]["donor"], {"kind": "path", "ref": "donors/gums-t5"})
        code, row, _ = self.start("--subject", "../outside")
        self.assertEqual(row["error_code"], "input_invalid")
        code, row, _ = self.start("--subject", str(self.ws / "modules" / "gums"))
        self.assertEqual(row["error_code"], "input_invalid")

    def test_a_target_that_is_not_a_key_and_a_missing_workspace_are_refused(self):
        code, row, _ = self.start(target="zm_sumpf")
        self.assertEqual(code, 2)
        self.assertEqual(row["error_code"], "invalid_arguments")
        out = self.out()
        code, row = invoke(["work", "start", str(self.root / "nowhere"), "--title", "t", "--want", "w",
                            "--target", "dlc5-beta2/zm_sumpf/zclassic", "--output", out, "--json"])
        self.assertEqual(row["error_code"], "input_missing")

    def test_the_output_directory_is_never_reused(self):
        code, row, work = self.start()
        code, row = invoke(["work", "start", str(self.ws), "--title", "t", "--want", "w",
                            "--target", "dlc5-beta2/zm_sumpf/zclassic", "--output", str(work), "--json"])
        self.assertEqual(row["error_code"], "output_exists")


class StepTests(WorkFixture):
    def test_a_row_without_a_receipt_is_narrated_and_one_with_is_hashed(self):
        _, _, work = self.start()
        code, row = invoke(["work", "step", str(work), "--step", "placement", "--outcome", "started", "--json"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["evidence"], "narrated")
        self.assertEqual(row["result"]["index"], 0)
        code, row = invoke(["work", "step", str(work / "work.json"), "--step", "placement", "--outcome", "done",
                            "--note", "one module, built alone", "--receipt", "jobs/work-001/receipt.json",
                            "--workspace", str(self.ws), "--json"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["evidence"], "receipted")
        self.assertEqual(row["result"]["row"]["receipt"], {"path": "jobs/work-001/receipt.json", "sha256": self.sha(work / "receipt.json")})
        spine = json.loads((work / "spine.json").read_text(encoding="utf-8"))
        self.assertEqual([r["outcome"] for r in spine["rows"]], ["started", "done"])
        self.assertEqual(spine["rows"][1]["note"], "one module, built alone")

    def test_a_receipt_that_is_not_there_and_an_absolute_one_without_a_workspace_are_refused(self):
        _, _, work = self.start()
        code, row = invoke(["work", "step", str(work), "--step", "build", "--outcome", "done",
                            "--receipt", "jobs/nothing/receipt.json", "--workspace", str(self.ws), "--json"])
        self.assertEqual(row["error_code"], "input_missing")
        self.assertFalse((work / "spine.json").exists())
        code, row = invoke(["work", "step", str(work), "--step", "build", "--outcome", "done",
                            "--receipt", str(work / "receipt.json"), "--json"])
        self.assertEqual(row["error_code"], "input_invalid")
        code, row = invoke(["work", "step", str(work), "--step", "build", "--outcome", "done",
                            "--receipt", str(work / "receipt.json"), "--workspace", str(self.ws), "--json"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["row"]["receipt"]["path"], "jobs/work-001/receipt.json")

    def test_an_unknown_step_is_a_usage_error_and_no_work_json_is_refused(self):
        _, _, work = self.start()
        code, row = invoke(["work", "step", str(work), "--step", "dream", "--outcome", "done", "--json"])
        self.assertEqual((code, row["error_code"]), (2, "invalid_arguments"))
        self.assertFalse((work / "spine.json").exists())
        code, row = invoke(["work", "step", str(self.ws), "--step", "build", "--outcome", "done", "--json"])
        self.assertEqual(row["error_code"], "input_missing")

    def test_two_rows_appended_at_once_both_land(self):
        _, _, work = self.start()
        results = []

        def append(outcome):
            results.append(invoke(["work", "step", str(work), "--step", "build", "--outcome", outcome, "--json"]))

        threads = [threading.Thread(target=append, args=(o,)) for o in ("started", "done")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertTrue(all(code == 0 for code, _ in results), results)
        spine = json.loads((work / "spine.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(r["outcome"] for r in spine["rows"]), ["done", "started"])


class DecisionTests(WorkFixture):
    def test_ask_then_answer_once_from_a_named_surface(self):
        _, _, work = self.start()
        code, row = invoke(["work", "ask", str(work), "--request", self.request(), "--json"])
        self.assertEqual(code, 0, row)
        request = row["result"]["request"]
        self.assertIsNone(request["answer"])
        self.assertEqual([o["key"] for o in request["options"]], ["stock", "b2"])
        self.assertEqual(request["default"], "b2")
        code, row = invoke(["work", "ask", str(work), "--request", self.request(question="And the map?"), "--json"])
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn(request["id"], row["message"])
        code, row = invoke(["work", "answer", str(work), "--request-id", request["id"], "--choice", "nope", "--by", "app", "--json"])
        self.assertEqual(row["error_code"], "input_invalid")
        code, row = invoke(["work", "answer", str(work), "--request-id", request["id"], "--choice", "b2", "--by", "app",
                            "--note", "Halo picked it in the panel", "--json"])
        self.assertEqual(code, 0, row)
        answer = row["result"]["request"]["answer"]
        self.assertEqual((answer["choice"], answer["via"], answer["note"]), ("b2", "app", "Halo picked it in the panel"))
        self.assertEqual(row["result"]["pending"], 0)
        code, row = invoke(["work", "answer", str(work), "--request-id", request["id"], "--choice", "stock", "--by", "host", "--json"])
        self.assertEqual(row["error_code"], "input_invalid")
        decisions = json.loads((work / "decisions.json").read_text(encoding="utf-8"))
        self.assertEqual(decisions["requests"][0]["answer"]["choice"], "b2")
        code, row = invoke(["work", "answer", str(work), "--request-id", "0000000000000000", "--choice", "b2", "--by", "app", "--json"])
        self.assertEqual(row["error_code"], "input_missing")
        code, row = invoke(["work", "ask", str(work), "--request", self.request(question="And the map?"), "--json"])
        self.assertEqual(code, 0, row)

    def test_a_malformed_request_is_refused_with_its_pointer(self):
        _, _, work = self.start()
        cases = [({"options": [{"key": "only", "label": "One"}]}, "/options"),
                 ({"options": [{"key": "a", "label": "A"}, {"key": "a", "label": "B"}]}, "/options/1/key"),
                 ({"options": [{"key": "Bad Key", "label": "A"}, {"key": "b", "label": "B"}]}, "/options/0/key"),
                 ({"default": "nope"}, "/default"),
                 ({"step": "dream"}, "/step"),
                 ({"question": ""}, "/question"),
                 ({"extra": 1}, "/")]
        for over, pointer in cases:
            with self.subTest(pointer=pointer):
                code, row = invoke(["work", "ask", str(work), "--request", self.request(**over), "--json"])
                self.assertEqual(row["error_code"], "input_invalid", row)
                self.assertEqual(row["details"]["field"], pointer, row)
        self.assertFalse((work / "decisions.json").exists())


class StatusTests(WorkFixture):
    def test_status_leads_with_what_waits_on_the_person(self):
        _, _, work = self.start()
        code, row = invoke(["work", "status", str(work), "--json"])
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertEqual(result["protocol"], "pat.work-status/1")
        self.assertFalse(result["waiting_on_person"])
        self.assertEqual((result["current_step"], result["next_step"], result["spine"]), (None, "placement", []))
        invoke(["work", "step", str(work), "--step", "placement", "--outcome", "done", "--json"])
        invoke(["work", "step", str(work), "--step", "donor", "--outcome", "skipped", "--note", "no donor; prior art searched", "--json"])
        invoke(["work", "step", str(work), "--step", "build", "--outcome", "started", "--json"])
        invoke(["work", "ask", str(work), "--request", self.request(step="build"), "--json"])
        code, row = invoke(["work", "status", str(work), "--json"])
        result = row["result"]
        self.assertTrue(result["waiting_on_person"])
        self.assertEqual(len(result["pending"]), 1)
        self.assertEqual(result["current_step"], "build")
        self.assertEqual(result["next_step"], "donor", "a skipped step is not done; the reader says so rather than hiding it")
        self.assertEqual(result["last"]["step"], "build")
        self.assertEqual(result["evidence"], {"receipted": 0, "narrated": 3, "receipt-missing": 0, "receipt-drifted": 0})

    def test_status_rehashes_every_cited_receipt(self):
        _, _, work = self.start()
        other = self.ws / "jobs" / "build-001"
        other.mkdir()
        (other / "receipt.json").write_text('{"status": "succeeded"}')
        invoke(["work", "step", str(work), "--step", "build", "--outcome", "done",
                "--receipt", "jobs/build-001/receipt.json", "--workspace", str(self.ws), "--json"])
        invoke(["work", "step", str(work), "--step", "verify", "--outcome", "done",
                "--receipt", "jobs/work-001/receipt.json", "--workspace", str(self.ws), "--json"])
        code, row = invoke(["work", "status", str(work), "--workspace", str(self.ws), "--json"])
        rows = row["result"]["spine"]
        self.assertEqual([r["evidence"] for r in rows], ["receipted", "receipted"])
        self.assertEqual(rows[0]["receipt"]["status"], "succeeded")
        (other / "receipt.json").write_text('{"status": "failed"}')
        code, row = invoke(["work", "status", str(work), "--workspace", str(self.ws), "--json"])
        rows = row["result"]["spine"]
        self.assertEqual(rows[0]["evidence"], "receipt-drifted")
        self.assertEqual(rows[0]["receipt"]["status"], "failed")
        self.assertEqual(rows[0]["receipt"]["current_sha256"], self.sha(other / "receipt.json"))
        (other / "receipt.json").unlink()
        code, row = invoke(["work", "status", str(work), "--workspace", str(self.ws), "--json"])
        self.assertEqual(row["result"]["spine"][0]["evidence"], "receipt-missing")
        self.assertEqual(row["result"]["evidence"]["receipt-missing"], 1)
        code, row = invoke(["work", "status", str(work), "--workspace", str(self.root / "nowhere"), "--json"])
        self.assertEqual(row["error_code"], "input_missing")

    def test_a_directory_with_no_work_json_and_a_bad_order_are_refused(self):
        code, row = invoke(["work", "status", str(self.ws), "--json"])
        self.assertEqual(row["error_code"], "input_missing")
        _, _, work = self.start()
        (work / "work.json").write_text('{"schema": 1, "id": "x"}')
        code, row = invoke(["work", "status", str(work), "--json"])
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertEqual(row["details"]["field"], "/id")


class DiscoveryTests(unittest.TestCase):
    def test_the_routes_are_registered_with_their_effects(self):
        expected = {"start": "writes-output", "step": "writes-record", "ask": "writes-record",
                    "answer": "writes-record", "status": "inert"}
        for action, effect in expected.items():
            route = find("work", action)
            self.assertEqual(route.effect, effect, action)
            self.assertEqual(route.status, "implemented", action)
            self.assertIn("docs/work-orders.md", route.notes, action)
        self.assertEqual(find("work", "status").result_protocol, "pat.work-status/1")
        code, row = invoke(["describe", "work", "status", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(row["result"]["id"], "work.status")


if __name__ == "__main__":
    unittest.main()
