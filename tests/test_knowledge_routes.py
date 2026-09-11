"""``pat knowledge`` against the data shipped in the package. No backend, network or game."""
import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from plutonium_agent_toolkit.cli import entry
from plutonium_agent_toolkit.dev import knowledge

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "src" / "plutonium_agent_toolkit" / "knowledge"
# The maintainer's machine must not leak through generated data: home paths, private trees, thread
# ids, build hashes, the private command names.
PRIVATE = re.compile(r"/home/[a-z]|\.local/|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|"
                     r"\b[0-9a-f]{64}\b|halo-(?:modding|plutonium)-dev|t6/dlc5-")


def invoke(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = entry(argv)
    return code, json.loads(buf.getvalue())


class DataTests(unittest.TestCase):
    def test_four_files_ship_with_schema_one_and_no_private_material(self):
        for name in knowledge.FILES:
            path = DATA / name
            self.assertTrue(path.is_file(), name)
            text = path.read_text(encoding="utf-8")
            self.assertEqual(json.loads(text)["schema"], 1, name)
            hit = PRIVATE.search(text)
            self.assertIsNone(hit, f"{name}: {hit and hit.group(0)}")
            self.assertLess(path.stat().st_size, 400_000, f"{name} is over the size bound")

    def test_builtins_have_both_vms_with_witnessed_rows(self):
        data = json.loads((DATA / "builtins.json").read_text(encoding="utf-8"))
        for vm in ("server", "client"):
            self.assertGreater(len(data[vm]), 100, vm)
            self.assertEqual(data["counts"][vm], len(data[vm]))
            for name, row in data[vm].items():
                self.assertEqual(name, name.lower(), name)
                self.assertIsInstance(row["argcs"], list, name)
                self.assertIn(row["origin"], {"native-call-site", "plutonium"} | {o for o in [row["origin"]] if o.startswith("plugin:")}, name)
                if row["origin"] == "native-call-site":
                    self.assertGreater(row["witnesses"], 0, name)
                    self.assertTrue(row["witness"].endswith((".gsc", ".csc")), name)

    def test_signatures_compile_and_carry_class_cause_fix(self):
        rows = json.loads((DATA / "crash-signatures.json").read_text(encoding="utf-8"))["rows"]
        ids = [r["id"] for r in rows]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(ids), len(set(ids)))
        for row in rows:
            re.compile(row["regex"])
            self.assertFalse(row["regex"].startswith(r"\["), f"{row['id']}: no timestamp prefix in a signature")
            for key in ("class", "cause", "fix", "source"):
                self.assertTrue(row[key], f"{row['id']} lacks {key}")
        self.assertIn("client-field-set-out-of-space", ids)
        self.assertIn("unresolved-external", ids)

    def test_limits_and_occupancy_agree(self):
        limits = json.loads((DATA / "engine-limits.json").read_text(encoding="utf-8"))["rows"]
        occupancy = json.loads((DATA / "occupancy.json").read_text(encoding="utf-8"))
        engine = [r for r in limits if r["kind"] == "engine"]
        self.assertTrue(engine)
        self.assertTrue(any(r["count_source"] for r in engine), "at least one limit is counted from disk")
        for map_id, row in occupancy["maps"].items():
            self.assertEqual(set(row["limits"]), {r["id"] for r in engine}, map_id)
            for limit in engine:
                cell = row["limits"][limit["id"]]
                self.assertEqual(cell["limit"], limit["bound"], f"{map_id}: {limit['id']}")
                if limit["count_source"] is None:
                    self.assertIsNone(cell["count"], f"{map_id}: {limit['id']} has no countable source")
            self.assertEqual(row["limits"]["sound-assets"]["count"], row["assets"].get("soundbank"), map_id)
            self.assertNotIn("loadfx", row, "names stay private; only counts travel")
            self.assertNotIn("weapon_names", row)


class RouteTests(unittest.TestCase):
    def test_routes_are_registered_inert_and_described(self):
        code, row = invoke(["manifest"])
        self.assertEqual(code, 0)
        rows = {r["id"]: r for r in row["result"]["routes"]}
        for action in ("builtin", "signature", "limits"):
            route = rows[f"knowledge.{action}"]
            self.assertEqual(route["effect"], "inert", action)
            self.assertEqual(route["status"], "implemented", action)
            self.assertTrue(route["available_here"], action)
        code, row = invoke(["describe", "knowledge", "builtin"])
        self.assertEqual(code, 0)
        self.assertEqual(row["result"]["argv"], ["pat", "knowledge", "builtin"])

    def test_builtin_answers_the_two_recorded_load_failures(self):
        code, row = invoke(["knowledge", "builtin", "setanimknob", "--json"])
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertEqual(result["verdict"], "builtin")
        self.assertEqual(sorted(result["rows"]), ["client"], "a client-only method: the Arnie startup failure")
        self.assertEqual(result["rows"]["client"]["argcs"], [4])
        code, row = invoke(["knowledge", "builtin", "SetAnimKnob", "--vm", "server"])
        self.assertEqual(code, 0)
        self.assertEqual(row["result"]["verdict"], "unknown")
        self.assertEqual(row["result"]["also_on"], ["client"])
        code, row = invoke(["knowledge", "builtin", "precachemodel"])
        self.assertEqual(sorted(row["result"]["rows"]), ["server"], "server-only: the Margwa client load failure")
        code, row = invoke(["knowledge", "builtin", "setclientfield"])
        self.assertEqual(row["result"]["verdict"], "unknown", "a script export, not a builtin: include maps/mp/_utility")
        code, row = invoke(["knowledge", "builtin", "replacefunc"])
        self.assertEqual(row["result"]["rows"]["server"]["origin"], "plutonium")

    def test_builtin_refuses_a_bad_name_or_vm_as_usage(self):
        code, row = invoke(["knowledge", "builtin", "not a name"])
        self.assertEqual(code, 2)
        self.assertEqual(row["error_code"], "invalid_arguments")
        code, row = invoke(["knowledge", "builtin", "spawn", "--vm", "both"])
        self.assertEqual(code, 2)

    def test_signature_matches_a_slice_and_a_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "slice.log"
            log.write_text("[21:14:02] gamename: T6\n"
                           "[21:14:03] Trying to assign 1 bits for netfield bench_riser_glow but Client Field Set actor is out of space.\n"
                           "[21:14:04] Unresolved external: setanimknob with 4 parameters\n"
                           "[21:14:05] weapon not found: foo\n", encoding="utf-8")
            code, row = invoke(["knowledge", "signature", "--log", str(log), "--json"])
            self.assertEqual(code, 0, row)
            result = row["result"]
            self.assertEqual(result["lines_read"], 4)
            self.assertEqual([m["id"] for m in result["matches"]], ["client-field-set-out-of-space", "unresolved-external"])
            self.assertEqual(result["matches"][0]["line"], 2)
            self.assertFalse(result["matches"][0]["text"].startswith("["), "the timestamp prefix is stripped")
            self.assertEqual(result["classes"], {"pool-exhausted": 1, "script-error": 1})
            code, row = invoke(["knowledge", "signature", "--log", str(Path(tmp) / "missing.log")])
            self.assertEqual(code, 1)
            self.assertEqual(row["error_code"], "input_missing")
        code, row = invoke(["knowledge", "signature", "--text", "Exceeded limit of 32 'sound' assets"])
        self.assertEqual(code, 0)
        self.assertEqual(row["result"]["matches"][0]["id"], "exceeded-asset-limit")
        code, row = invoke(["knowledge", "signature", "--text", "nothing known here"])
        self.assertEqual(code, 0)
        self.assertEqual(row["result"]["matches"], [])
        code, row = invoke(["knowledge", "signature"])
        self.assertEqual(code, 2)
        code, row = invoke(["knowledge", "signature", "--text", "x", "--log", "y"])
        self.assertEqual(code, 2)

    def test_limits_list_and_per_map(self):
        code, row = invoke(["knowledge", "limits"])
        self.assertEqual(code, 0, row)
        ids = [r["id"] for r in row["result"]["limits"]]
        self.assertIn("projectile-fx-registrations", ids)
        self.assertIn("zm_transit", row["result"]["maps"])
        code, row = invoke(["knowledge", "limits", "--map", "zm_transit"])
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertEqual(result["map"], "zm_transit")
        fx = result["limits"]["projectile-fx-registrations"]
        self.assertEqual(fx["limit"], 40)
        self.assertIsInstance(fx["count"], int)
        self.assertLessEqual(fx["count"], 40)
        self.assertIsNone(result["limits"]["assembled-model-bones-dobj"]["count"], "nothing on disk counts bones")
        self.assertIn("actor", result["clientfield_bits"])
        code, row = invoke(["knowledge", "limits", "--map", "zm_nowhere"])
        self.assertEqual(code, 2)
        self.assertIn("Known maps", row["hint"])
        code, row = invoke(["knowledge", "limits", "--map", "Bad Map"])
        self.assertEqual(code, 2)


class DocsAndBenchmarkTests(unittest.TestCase):
    def test_knowledge_pages_point_at_the_data(self):
        for page, needle in (("gsc.md", "pat knowledge builtin"), ("engine-limits.md", "pat knowledge limits"),
                             ("crashes.md", "pat knowledge signature")):
            text = (ROOT / "docs" / "knowledge" / page).read_text(encoding="utf-8")
            self.assertIn(needle, text, page)
            self.assertLessEqual(len(text.splitlines()), 150, page)

    def test_benchmark_tasks_need_the_data(self):
        tasks = {t["id"]: t for t in json.loads((ROOT / "tools/benchmark/tasks.json").read_text(encoding="utf-8"))["tasks"]}
        wrong_vm = tasks["bench-05-builtin-wrong-vm"]
        fixture = (ROOT / "tools/benchmark/fixtures/bench-05/face_glow.gsc").read_text(encoding="utf-8")
        self.assertIn("setanimknob", fixture)
        self.assertEqual(wrong_vm["expect"]["artifact_excludes"], ["setanimknob"])
        data = json.loads((DATA / "builtins.json").read_text(encoding="utf-8"))
        self.assertNotIn("setanimknob", data["server"], "the fixture's call must be absent from the server VM in the shipped data")
        self.assertIn("setanimknob", data["client"])
        classify = tasks["bench-06-classify-then-fix"]
        slice_text = (ROOT / "tools/benchmark/fixtures/bench-06/console_slice.log").read_text(encoding="utf-8")
        result = knowledge.signature(text=slice_text)
        self.assertEqual([m["id"] for m in result["matches"]], ["client-field-set-out-of-space"])
        script = (ROOT / "tools/benchmark/fixtures/bench-06/riser_glow.gsc").read_text(encoding="utf-8")
        self.assertIn('"actor", "bench_riser_glow"', script)
        self.assertEqual(classify["expect"]["artifact_excludes"], ["bench_riser_glow"])
        for task in (wrong_vm, classify):
            self.assertTrue((ROOT / "tools" / "benchmark" / task["prompt"]).is_file(), task["prompt"])


if __name__ == "__main__":
    unittest.main()
