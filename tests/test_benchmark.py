"""The offline benchmark scorer, against synthetic receipts. No backend, no game."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("benchmark", ROOT / "tools" / "benchmark.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def receipt(directory: Path, command: str, status="succeeded", started="2026-09-10T10:00:00+00:00",
            finished="2026-09-10T10:00:01+00:00", outputs=None, error=None, readback=None):
    directory.mkdir(parents=True, exist_ok=True)
    data = {"schema_version": 1, "job_id": "x", "command": command, "argv": ["pat", *command.split()],
            "status": status, "started": started, "updated": finished, "finished": finished,
            "outputs": outputs or {}, "steps": []}
    if error:
        data["error"] = {"error_code": error, "message": "fake"}
    (directory / "receipt.json").write_text(json.dumps(data), encoding="utf-8")
    for rel, text in (readback or {}).items():
        target = directory / "readback" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name) / "run"
        self.run.mkdir()
        (self.run / "run.json").write_text(json.dumps({"model": "fake-1", "harness": "unittest", "started": "2026-09-10"}))
        self.tasks = bench.load_tasks(bench.DEFAULT_TASKS)["tasks"]
        self.by_id = {t["id"]: t for t in self.tasks}

    def test_tasks_file_is_well_formed_and_prompts_exist(self):
        self.assertEqual([t["id"] for t in self.tasks],
                         ["bench-01-compile-error", "bench-02-build-hello", "bench-03-extract-rawfile", "bench-04-port-feature"])
        for t in self.tasks:
            self.assertTrue((ROOT / "tools" / "benchmark" / t["prompt"]).is_file(), t["prompt"])
            self.assertTrue(t["expect"]["routes"])
            self.assertGreater(t["expect"]["max_invocations"], 0)
        self.assertTrue((ROOT / "tools/benchmark/fixtures/bench-01/broken.gsc").is_file())
        self.assertTrue((ROOT / "examples/hello-zm-two/project.json").is_file())

    def test_empty_run_scores_zero_everywhere(self):
        report = bench.score_run(self.run, bench.DEFAULT_TASKS)
        self.assertEqual(report["totals"]["passed"], 0)
        self.assertEqual(report["run"]["model"], "fake-1")
        for row in report["tasks"]:
            self.assertEqual(row["score"], 0.0)
            self.assertEqual(row["invocations"], 0)

    def test_compile_error_task_requires_a_structural_failure(self):
        task = self.by_id["bench-01-compile-error"]
        receipt(self.run / task["id"] / "job-1", "gsc compile", status="failed", error="backend_failed")
        row = bench.score_task(task, self.run)
        self.assertTrue(all(row["checks"].values()), row)
        self.assertEqual(row["score"], 1.0)
        # A "success" on a broken script is wrong, and so is the wrong error code.
        receipt(self.run / task["id"] / "job-1", "gsc compile", status="succeeded")
        row = bench.score_task(task, self.run)
        self.assertFalse(row["checks"]["final_status"])
        self.assertFalse(row["checks"]["final_error_code"])

    def test_build_task_checks_order_outputs_budget_and_nested_receipts(self):
        task = self.by_id["bench-02-build-hello"]
        base = self.run / task["id"]
        receipt(base / "01-plan", "project plan", started="2026-09-10T10:00:00+00:00", finished="2026-09-10T10:00:01+00:00")
        receipt(base / "02-build", "project build", started="2026-09-10T10:00:02+00:00", finished="2026-09-10T10:00:03+00:00",
                outputs={"packages/mod.ff": "abc", "plan.json": "def"})
        # The child compile job project build starts must not count as an invocation.
        receipt(base / "02-build" / "script-000", "gsc compile", started="2026-09-10T10:00:02+00:00")
        receipt(base / "03-verify", "project verify", started="2026-09-10T10:00:04+00:00", finished="2026-09-10T10:00:05+00:00")
        row = bench.score_task(task, self.run)
        self.assertEqual(row["invocations"], 3, row["detail"])
        self.assertTrue(all(row["checks"].values()), row)
        self.assertEqual(row["wall_seconds"], 5.0)
        # Out of order: verify before build.
        receipt(base / "03-verify", "project verify", started="2026-09-10T09:59:00+00:00")
        row = bench.score_task(task, self.run)
        self.assertTrue(row["checks"]["routes_present"])
        self.assertFalse(row["checks"]["routes_ordered"])
        # Over budget: seven invocations.
        for n in range(4):
            receipt(base / f"extra-{n}", "project plan", started=f"2026-09-10T10:01:0{n}+00:00")
        row = bench.score_task(task, self.run)
        self.assertFalse(row["checks"]["within_budget"])

    def test_extract_task_matches_output_patterns(self):
        task = self.by_id["bench-03-extract-rawfile"]
        receipt(self.run / task["id"] / "job", "ff extract", outputs={"assets/scripts/zm/hello_zm.gsc": "x", "step-01.log": "y"})
        self.assertTrue(bench.score_task(task, self.run)["checks"]["outputs"])
        receipt(self.run / task["id"] / "job", "ff extract", outputs={"step-01.log": "y"})
        row = bench.score_task(task, self.run)
        self.assertFalse(row["checks"]["outputs"])
        self.assertEqual(row["detail"]["outputs_missing"], ["assets/**/*.gsc"])

    def test_port_task_reads_the_readback_not_the_prose(self):
        task = self.by_id["bench-04-port-feature"]
        base = self.run / task["id"]
        receipt(base / "build", "project build", outputs={"packages/mod.ff": "x"},
                readback={"scripts/zm/hello_zm.gsc": "on_player_spawned announce_round"})
        receipt(base / "verify", "project verify", started="2026-09-10T10:00:05+00:00")
        row = bench.score_task(task, self.run)
        self.assertTrue(row["checks"]["readback"], row)
        receipt(base / "build", "project build", outputs={"packages/mod.ff": "x"},
                readback={"scripts/zm/hello_zm.gsc": "on_player_spawned only"})
        row = bench.score_task(task, self.run)
        self.assertFalse(row["checks"]["readback"])
        self.assertEqual(row["detail"]["readback_missing"], ["announce_round"])

    def test_table_row_has_one_cell_per_task_plus_totals(self):
        report = bench.score_run(self.run, bench.DEFAULT_TASKS)
        cells = bench.table_row(report).strip("| ").split(" | ")
        self.assertEqual(len(cells), 3 + len(self.tasks) + 1)
        self.assertEqual(cells[0], "fake-1")


if __name__ == "__main__":
    unittest.main()
