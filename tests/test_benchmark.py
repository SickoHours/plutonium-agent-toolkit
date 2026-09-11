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
            finished="2026-09-10T10:00:01+00:00", outputs=None, error=None, readback=None, inputs=None):
    directory.mkdir(parents=True, exist_ok=True)
    data = {"schema_version": 1, "job_id": "x", "command": command, "argv": ["pat", *command.split()],
            "status": status, "started": started, "updated": finished, "finished": finished,
            "outputs": outputs or {}, "inputs": inputs or {}, "steps": []}
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
                         ["bench-01-compile-error", "bench-02-build-hello", "bench-03-extract-rawfile", "bench-04-port-feature",
                          "bench-05-builtin-wrong-vm", "bench-06-classify-then-fix"])
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
        receipt(self.run / task["id"] / "job-1", "gsc compile", status="failed", error="backend_failed",
                inputs={"/repo/tools/benchmark/fixtures/bench-01/broken.gsc": "a" * 64})
        row = bench.score_task(task, self.run)
        self.assertTrue(all(row["checks"].values()), row)
        # Compiling some other broken script is not the task.
        receipt(self.run / task["id"] / "job-1", "gsc compile", status="failed", error="backend_failed",
                inputs={"/elsewhere/other.gsc": "a" * 64})
        self.assertFalse(bench.score_task(task, self.run)["checks"]["inputs"])
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
                outputs={"packages/mod.ff": "abc", "plan.json": "def"},
                inputs={"/repo/examples/hello-zm/project.json": "1" * 64, "/repo/examples/hello-zm/scripts/hello.gsc": "2" * 64})
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

    def test_extract_task_matches_output_patterns_and_input_hash(self):
        task = self.by_id["bench-03-extract-rawfile"]
        build = self.run / "bench-02-build-hello" / "build"
        receipt(build, "project build", outputs={"packages/mod.ff": "f" * 64})
        receipt(self.run / task["id"] / "job", "ff extract", outputs={"assets/scripts/zm/hello_zm.gsc": "x", "step-01.log": "y"},
                inputs={str(build / "packages" / "mod.ff"): "f" * 64})
        row = bench.score_task(task, self.run)
        self.assertTrue(row["checks"]["outputs"])
        self.assertTrue(row["checks"]["input_hash"], row["detail"])
        # Extracting a different fastfile than the one bench-02 built is not the task.
        receipt(self.run / task["id"] / "job", "ff extract", outputs={"assets/scripts/zm/hello_zm.gsc": "x"},
                inputs={"/elsewhere/packages/mod.ff": "0" * 64})
        row = bench.score_task(task, self.run)
        self.assertFalse(row["checks"]["input_hash"])
        self.assertIn("!=", row["detail"]["input_hash"])
        receipt(self.run / task["id"] / "job", "ff extract", outputs={"step-01.log": "y"})
        row = bench.score_task(task, self.run)
        self.assertFalse(row["checks"]["outputs"])
        self.assertEqual(row["detail"]["outputs_missing"], ["assets/**/*.gsc"])

    def test_port_task_reads_the_readback_not_the_prose(self):
        task = self.by_id["bench-04-port-feature"]
        base = self.run / task["id"]
        ported = {"/run/bench-04/hello-zm-ported/project.json": "1" * 64, "/run/bench-04/hello-zm-ported/scripts/hello.gsc": "2" * 64}
        receipt(base / "build", "project build", outputs={"packages/mod.ff": "x"}, inputs=ported,
                readback={"scripts/zm/hello_zm.gsc": "on_player_spawned announce_round"})
        receipt(base / "verify", "project verify", started="2026-09-10T10:00:05+00:00")
        row = bench.score_task(task, self.run)
        self.assertTrue(row["checks"]["readback"], row)
        self.assertTrue(row["checks"]["inputs"], row)
        receipt(base / "build", "project build", outputs={"packages/mod.ff": "x"},
                readback={"scripts/zm/hello_zm.gsc": "on_player_spawned only"})
        row = bench.score_task(task, self.run)
        self.assertFalse(row["checks"]["readback"])
        self.assertEqual(row["detail"]["readback_missing"], ["announce_round"])

    def test_wrong_vm_task_is_scored_on_the_compiled_artifact(self):
        task = self.by_id["bench-05-builtin-wrong-vm"]
        job = self.run / task["id"] / "job"
        import hashlib

        def compiled_receipt(body: bytes):
            compiled = job / "compiled" / "t6" / "face_glow.gsc"
            compiled.parent.mkdir(parents=True, exist_ok=True)
            compiled.write_bytes(body)
            receipt(job, "gsc compile", inputs={"/run/bench-05/face_glow.gsc": "a" * 64},
                    outputs={"compiled/t6/face_glow.gsc": hashlib.sha256(body).hexdigest()})
            return compiled

        lookup = self.run / task["id"] / "lookup"
        answer = json.dumps({"name": "setanimknob", "verdict": "builtin"}).encode()
        lookup.mkdir(parents=True, exist_ok=True)
        (lookup / "answer.json").write_bytes(answer)
        receipt(lookup, "knowledge builtin", started="2026-09-10T09:59:00+00:00", finished="2026-09-10T09:59:01+00:00",
                outputs={"answer.json": hashlib.sha256(answer).hexdigest()})
        compiled = compiled_receipt(b"\x80GSC\x00face_glow_think\x00^3face glow armed\x00iprintln\x00")
        row = bench.score_task(task, self.run)
        self.assertTrue(all(row["checks"].values()), row)
        # The call the engine cannot resolve is still in the artifact: compiling is not fixing.
        compiled_receipt(b"\x80GSC\x00face_glow_think\x00^3face glow armed\x00setanimknob\x00")
        row = bench.score_task(task, self.run)
        self.assertFalse(row["checks"]["artifacts"])
        self.assertEqual(row["detail"]["artifacts"]["present"], ["setanimknob"])
        # Gutting the feature is not a fix either.
        compiled_receipt(b"\x80GSC\x00main\x00")
        self.assertIn("face_glow_think", bench.score_task(task, self.run)["detail"]["artifacts"]["missing"])
        # An artifact replaced after the job (hash no longer the receipt's) is not the job's artifact.
        compiled_receipt(b"\x80GSC\x00face_glow_think\x00^3face glow armed\x00setanimknob\x00")
        compiled.write_bytes(b"\x80GSC\x00face_glow_think\x00^3face glow armed\x00iprintln\x00")
        row = bench.score_task(task, self.run)
        self.assertFalse(row["checks"]["artifacts"])
        self.assertEqual(row["detail"]["artifacts"]["drift"], ["compiled/t6/face_glow.gsc"])
        # No artifact at all (a failed compile) cannot pass the artifact check.
        compiled.unlink()
        self.assertFalse(bench.score_task(task, self.run)["checks"]["artifacts"])
        # A fabricated answer whose hash is not the receipt's does not count; no receipt at all does not count.
        (lookup / "answer.json").write_bytes(b'{"name": "setanimknob", "verdict": "guessed"}')
        compiled_receipt(b"\x80GSC\x00face_glow_think\x00^3face glow armed\x00iprintln\x00")
        self.assertFalse(bench.score_task(task, self.run)["checks"]["lookup"])
        import shutil
        shutil.rmtree(lookup)
        row = bench.score_task(task, self.run)
        self.assertFalse(row["checks"]["lookup"])
        self.assertFalse(row["checks"]["routes_present"])

    def test_table_row_has_one_cell_per_task_plus_totals(self):
        report = bench.score_run(self.run, bench.DEFAULT_TASKS)
        cells = bench.table_row(report).strip("| ").split(" | ")
        self.assertEqual(len(cells), 3 + len(self.tasks) + 1)
        self.assertEqual(cells[0], "fake-1")


if __name__ == "__main__":
    unittest.main()
