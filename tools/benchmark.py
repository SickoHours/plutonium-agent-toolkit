#!/usr/bin/env python3
"""Score an agent's run of the offline benchmark tasks from receipts alone.

    python tools/benchmark.py score --run <run-dir> [--tasks tools/benchmark/tasks.json]
    python tools/benchmark.py table --run <run-dir>        # Markdown row for docs/BENCHMARK.md

A run directory holds ``run.json`` (``model``, ``harness``, ``started``, ``finished``, optional
``tokens_in``/``tokens_out``, ``notes``) and one subdirectory per task ID containing the job
output directories the agent produced. Nothing the agent wrote in prose is read: every check is
answered by ``receipt.json`` files and the output files they inventory.

Per task: the required routes appear, in order, among the task's top-level invocations; the
final invocation's status (and error code, when expected) matches; the expected outputs exist in
the last succeeded receipt of the last required route; readback files contain the expected
strings; the invocation count is within budget; wall time is first ``started`` to last
``updated``. A task scores the fraction of its checks that passed. Exit 0 always.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TASKS = ROOT / "tools" / "benchmark" / "tasks.json"


def load_tasks(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or not isinstance(data.get("tasks"), list):
        raise SystemExit(f"{path}: unsupported tasks file")
    return data


def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None


def top_level_receipts(task_dir: Path) -> list[dict]:
    """Receipts of jobs the agent invoked, oldest first; nested child jobs are folded into their parent."""
    rows = []
    for path in sorted(task_dir.rglob("receipt.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if not isinstance(data, dict) or data.get("schema_version") != 1 or "command" not in data:
            continue
        # A job that project build starts for each script writes its own receipt under the parent
        # job's directory; only the outermost receipt counts as an invocation.
        ancestors = [a for a in path.parent.parents if a != task_dir and task_dir in a.parents]
        if any((a / "receipt.json").is_file() for a in ancestors):
            continue
        data["_dir"] = path.parent
        data["_mtime"] = path.stat().st_mtime
        rows.append(data)
    # Receipt timestamps have one-second resolution and several small jobs finish within one
    # second; the receipt file's mtime (written at finish) breaks the tie in real order.
    rows.sort(key=lambda r: (r.get("started") or "", r["_mtime"]))
    return rows


def _ordered(required: list[str], seen: list[str]) -> tuple[bool, bool]:
    """(all required present, present in the required order among the seen sequence)."""
    present = all(r in seen for r in required)
    position = 0
    for command in seen:
        if position < len(required) and command == required[position]:
            position += 1
    return present, position == len(required)


def _outputs_ok(receipt: dict | None, contains: list[str], match: list[str]) -> tuple[bool, list[str]]:
    if receipt is None:
        return False, contains + match
    outputs = receipt.get("outputs") or {}
    missing = [name for name in contains if name not in outputs]
    for pattern in match:
        if not any(fnmatch.fnmatch(name, pattern) for name in outputs):
            missing.append(pattern)
    return not missing, missing


def _readback_ok(receipt: dict | None, needles: list[str]) -> tuple[bool, list[str]]:
    if receipt is None:
        return False, list(needles)
    readback = Path(receipt["_dir"]) / "readback"
    blobs = [p.read_bytes() for p in readback.rglob("*") if p.is_file()] if readback.is_dir() else []
    missing = [n for n in needles if not any(n.encode() in blob for blob in blobs)]
    return not missing, missing


def _inputs_ok(receipt: dict | None, suffixes: list[str]) -> tuple[bool, list[str]]:
    """Every suffix names a file the job declared as an input (receipt inputs are absolute paths)."""
    if receipt is None:
        return False, list(suffixes)
    declared = [Path(p).as_posix() for p in (receipt.get("inputs") or {})]
    missing = [s for s in suffixes if not any(d.endswith("/" + s) or d == s for d in declared)]
    return not missing, missing


def _input_hash_ok(receipt: dict | None, rule: dict, run_dir: Path) -> tuple[bool, str]:
    """An input ending in rule.suffix must carry the hash another task's succeeded job recorded for rule.output."""
    if receipt is None:
        return False, "no receipt"
    inputs = {Path(p).as_posix(): h for p, h in (receipt.get("inputs") or {}).items()}
    actual = next((h for p, h in inputs.items() if p.endswith("/" + rule["suffix"])), None)
    if actual is None:
        return False, f"no input ending in {rule['suffix']}"
    source_dir = run_dir / rule["task"]
    expected = None
    for r in reversed(top_level_receipts(source_dir) if source_dir.is_dir() else []):
        if r.get("status") == "succeeded" and rule["output"] in (r.get("outputs") or {}):
            expected = r["outputs"][rule["output"]]
            break
    if expected is None:
        return False, f"{rule['task']} has no succeeded receipt with output {rule['output']}"
    return actual == expected, "" if actual == expected else f"input hash {actual[:12]} != {rule['task']} output {expected[:12]}"


def score_task(task: dict, run_dir: Path) -> dict:
    expect = task["expect"]
    task_dir = run_dir / task["id"]
    receipts = top_level_receipts(task_dir) if task_dir.is_dir() else []
    commands = [r["command"] for r in receipts]
    checks: dict[str, bool] = {}
    detail: dict[str, object] = {}

    present, ordered = _ordered(expect["routes"], commands)
    checks["routes_present"] = present
    checks["routes_ordered"] = ordered
    detail["invocations"] = commands

    final = receipts[-1] if receipts else None
    checks["final_status"] = bool(final) and final.get("status") == expect.get("final_status", "succeeded")
    if "final_error_code" in expect:
        error = (final or {}).get("error") or {}
        checks["final_error_code"] = error.get("error_code") == expect["final_error_code"]
        detail["final_error_code"] = error.get("error_code")

    last_route = expect["routes"][-1]
    anchor_route = next((r for r in expect["routes"] if r in ("project build", "ff extract", "gsc compile")), last_route)
    anchor = next((r for r in reversed(receipts) if r["command"] == anchor_route and r.get("status") == "succeeded"), None)
    if anchor is None and expect.get("final_status") == "failed":
        anchor = next((r for r in reversed(receipts) if r["command"] == anchor_route), None)
    if expect.get("outputs_contain") or expect.get("outputs_match"):
        ok, missing = _outputs_ok(anchor, expect.get("outputs_contain", []), expect.get("outputs_match", []))
        checks["outputs"] = ok
        detail["outputs_missing"] = missing
    if expect.get("readback_contains"):
        ok, missing = _readback_ok(anchor, expect["readback_contains"])
        checks["readback"] = ok
        detail["readback_missing"] = missing
    # The job must have run against the task's own inputs, not an unrelated project or file.
    scored = anchor if anchor is not None else (final if final and final["command"] == anchor_route else None)
    if expect.get("inputs_contain"):
        ok, missing = _inputs_ok(scored, expect["inputs_contain"])
        checks["inputs"] = ok
        detail["inputs_missing"] = missing
    if expect.get("input_hash_from"):
        ok, why = _input_hash_ok(scored, expect["input_hash_from"], run_dir)
        checks["input_hash"] = ok
        detail["input_hash"] = why

    budget = expect.get("max_invocations")
    if budget:
        checks["within_budget"] = 0 < len(receipts) <= budget
    starts = [t for t in (_parse(r.get("started")) for r in receipts) if t]
    ends = [t for t in (_parse(r.get("finished") or r.get("updated")) for r in receipts) if t]
    wall = round((max(ends) - min(starts)).total_seconds(), 3) if starts and ends else None
    if receipts and not wall:
        # Everything ran inside one second by the receipts' clock; use the receipt files' mtimes
        # and each job's own elapsed_seconds for a sub-second figure.
        first = min(r["_mtime"] - float(r.get("elapsed_seconds") or 0) for r in receipts)
        wall = round(max(r["_mtime"] for r in receipts) - first, 3)
    failed = [r["command"] for r in receipts if r.get("status") != "succeeded"]
    passed = sum(checks.values())
    return {"task": task["id"], "checks": checks, "passed": passed, "total": len(checks),
            "score": round(passed / len(checks), 3) if checks else 0.0,
            "invocations": len(receipts), "max_invocations": budget, "failed_invocations": failed,
            "wall_seconds": wall, "detail": detail}


def score_run(run_dir: Path, tasks_path: Path) -> dict:
    run_path = run_dir / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8")) if run_path.is_file() else {}
    tasks = load_tasks(tasks_path)["tasks"]
    rows = [score_task(t, run_dir) for t in tasks]
    total_passed = sum(r["passed"] for r in rows)
    total = sum(r["total"] for r in rows)
    return {"schema": 1, "run": {k: run.get(k) for k in ("model", "harness", "started", "finished", "tokens_in", "tokens_out", "notes")},
            "tasks": rows,
            "totals": {"passed": total_passed, "total": total, "score": round(total_passed / total, 3) if total else 0.0,
                       "invocations": sum(r["invocations"] for r in rows),
                       "wall_seconds": round(sum(r["wall_seconds"] or 0 for r in rows), 3)},
            "scoring": "receipts and inventoried output files only; no prose was read; offline evidence, not gameplay"}


def table_row(report: dict) -> str:
    run = report["run"]
    cells = [str(run.get("model") or "?"), str(run.get("harness") or "?"), (run.get("started") or "?")[:10]]
    for row in report["tasks"]:
        cells.append(f"{row['passed']}/{row['total']} ({row['invocations']} calls)")
    t = report["totals"]
    cells.append(f"{t['passed']}/{t['total']} ({t['invocations']} calls, {t['wall_seconds']} s)")
    return "| " + " | ".join(cells) + " |"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["score", "table"])
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    args = ap.parse_args()
    report = score_run(args.run, args.tasks)
    if args.action == "table":
        print(table_row(report))
    else:
        print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
