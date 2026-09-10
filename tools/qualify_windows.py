#!/usr/bin/env python3
"""Run the native Windows qualification tiers and write sanitized receipts.

    python tools/qualify_windows.py --tier offline  --output docs/receipts/qualify
    python tools/qualify_windows.py --tier backends --output docs/receipts/qualify
    python tools/qualify_windows.py --tier game     --output docs/receipts/qualify --collect

Tiers 1 and 2 run commands themselves. Tier 3 never touches the game; with --collect it
reads the toolkit's state files after the human-authorized commands were run by hand and
folds them into a receipt. Every receipt is redacted: the Windows username, machine name
and absolute paths under the user profile are replaced before writing.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from plutonium_agent_toolkit import __version__  # noqa: E402

PAT = [sys.executable, "-m", "plutonium_agent_toolkit"]


# ----- redaction --------------------------------------------------------------------------

def redactor(extra_paths=()):
    user = getpass.getuser()
    host = socket.gethostname()
    profile = os.environ.get("USERPROFILE", "")
    patterns = []
    # Known private locations first (toolkit home, work directory), in every slash style.
    for label, raw in extra_paths:
        for variant in {raw, raw.replace("\\", "/"), raw.replace("\\", "\\\\")}:
            if variant:
                patterns.append((re.compile(re.escape(variant), re.I), f"<{label}>"))
    if profile:
        patterns.append((re.compile(re.escape(profile), re.I), "<userprofile>"))
        patterns.append((re.compile(re.escape(profile.replace("\\", "\\\\")), re.I), "<userprofile>"))
        patterns.append((re.compile(re.escape(profile.replace("\\", "/")), re.I), "<userprofile>"))
    if user:
        patterns.append((re.compile(r"(?i)(?<![A-Za-z0-9])" + re.escape(user) + r"(?![A-Za-z0-9])"), "<user>"))
    if host:
        patterns.append((re.compile(r"(?i)(?<![A-Za-z0-9])" + re.escape(host) + r"(?![A-Za-z0-9])"), "<host>"))
    # request/load/job IDs are private; git SHAs (40 hex) are not and must survive intact.
    patterns.append((re.compile(r"(?<![0-9a-f])[a-f0-9]{32}(?![0-9a-f])"), "<id>"))

    def redact(value):
        if isinstance(value, str):
            for pattern, replacement in patterns:
                value = pattern.sub(replacement, value)
            return value
        if isinstance(value, list):
            return [redact(v) for v in value]
        if isinstance(value, dict):
            return {redact(k): redact(v) for k, v in value.items()}
        return value
    return redact


# ----- running commands --------------------------------------------------------------------

NESTED_ENV = "PAT_QUALIFY_NESTED"


def child_env():
    """Children import the checked-out source even if `pip install -e .` was skipped.

    NESTED_ENV tells tests/test_qualify_tool.py not to launch this script again from
    inside the unit-test step; without it the offline tier would recurse forever."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env[NESTED_ENV] = "1"
    return env


def run(argv, timeout=900, cwd=None):
    started = time.monotonic()
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=child_env())
    elapsed = round(time.monotonic() - started, 3)
    try:
        payload = json.loads(proc.stdout) if proc.stdout.strip() else None
    except ValueError:
        payload = None
    return {"argv": argv[len(PAT):] if argv[:len(PAT)] == PAT else argv, "exit_code": proc.returncode,
            "elapsed_seconds": elapsed, "json": payload,
            "stdout_head": None if payload is not None else proc.stdout[:2000],
            "stderr_head": proc.stderr[:2000] if proc.stderr else ""}


def step(receipt, name, argv, expect_ok=True, timeout=900, cwd=None):
    row = run(argv, timeout=timeout, cwd=cwd)
    ok = (row["exit_code"] == 0 and bool(row["json"]) and row["json"].get("ok") is True) if expect_ok \
        else (row["exit_code"] != 0 and bool(row["json"]) and row["json"].get("ok") is False)
    row.update(name=name, passed=ok, expected="success" if expect_ok else "structured failure")
    receipt["steps"].append(row)
    print(("PASS " if ok else "FAIL ") + name, flush=True)
    return row


def environment():
    info = {"toolkit_version": __version__, "python": sys.version.split()[0], "platform": platform.platform(),
            "machine": platform.machine(), "native_windows": os.name == "nt",
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        info["windows_build"] = platform.win32_ver()[1]
    except Exception:  # noqa: BLE001
        pass
    try:
        info["git_head"] = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
        info["git_dirty"] = bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=ROOT).stdout.strip())
    except OSError:
        pass
    return info


def new_receipt(tier):
    return {"schema_version": 1, "tier": tier, "environment": environment(), "steps": [], "notes": []}


def finish(receipt, output: Path, name: str, redact):
    receipt["passed"] = all(s["passed"] for s in receipt["steps"])
    receipt["summary"] = {"steps": len(receipt["steps"]), "passed": sum(s["passed"] for s in receipt["steps"]),
                          "failed": [s["name"] for s in receipt["steps"] if not s["passed"]]}
    output.mkdir(parents=True, exist_ok=True)
    path = output / name
    path.write_text(json.dumps(redact(receipt), indent=2) + "\n", encoding="utf-8")
    print(f"\n{'PASSED' if receipt['passed'] else 'FAILED'}: {receipt['summary']['passed']}/{receipt['summary']['steps']} steps -> {path}")
    return receipt["passed"]


# ----- tiers ------------------------------------------------------------------------------

def tier_offline(receipt, home: Path, work: Path):
    env_note = f"PAT_HOME={home}"
    receipt["notes"].append(env_note)
    tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], capture_output=True, text=True, cwd=ROOT, env=child_env())
    receipt["steps"].append({"name": "unit tests", "argv": ["python", "-m", "unittest", "discover", "-s", "tests"],
                             "exit_code": tests.returncode, "passed": tests.returncode == 0,
                             "stderr_head": tests.stderr[-2000:], "expected": "success"})
    print(("PASS " if tests.returncode == 0 else "FAIL ") + "unit tests", flush=True)
    step(receipt, "version", PAT + ["version", "--json"])
    step(receipt, "manifest", PAT + ["manifest", "--json"])
    step(receipt, "describe game load-map", PAT + ["describe", "game", "load-map", "--json"])
    step(receipt, "doctor before configure", PAT + ["doctor", "--json"])
    storage = work / "fake-storage" / "t6"
    (storage / "mods").mkdir(parents=True)
    step(receipt, "configure fake storage", PAT + ["configure", "--plutonium-storage-t6", str(storage), "--json"])
    step(receipt, "game mods on empty storage", PAT + ["game", "mods", "--json"])
    step(receipt, "dev setup --plan", PAT + ["dev", "setup", "--plan", "--json"])
    step(receipt, "project plan hello-zm", PAT + ["project", "plan", str(ROOT / "examples/hello-zm/project.json"),
                                                  "--output", str(work / "plan-hello"), "--json"])
    step(receipt, "output_exists refusal", PAT + ["project", "plan", str(ROOT / "examples/hello-zm/project.json"),
                                                   "--output", str(work / "plan-hello"), "--json"], expect_ok=False)
    step(receipt, "planned route refuses", PAT + ["capture", "start"], expect_ok=False)
    step(receipt, "private scan", [sys.executable, str(ROOT / "tools/private_scan.py")])
    step(receipt, "release check", [sys.executable, str(ROOT / "tools/release_check.py")])


def tier_backends(receipt, home: Path, work: Path):
    step(receipt, "dev setup gsc oat", PAT + ["dev", "setup", "--only", "gsc", "oat", "--json"], timeout=1800)
    step(receipt, "doctor after setup", PAT + ["doctor", "--json"])
    step(receipt, "dev setup rerun verifies", PAT + ["dev", "setup", "--only", "gsc", "oat", "--json"], timeout=600)
    recipe = ROOT / "examples/hello-zm/project.json"
    step(receipt, "project plan hello-zm", PAT + ["project", "plan", str(recipe), "--output", str(work / "plan"), "--json"])
    build = step(receipt, "project build hello-zm (real gsc-tool + OAT)", PAT + ["project", "build", str(recipe), "--output", str(work / "build"), "--json"], timeout=600)
    if build["passed"]:
        result = build["json"]["result"]
        mod_ff = Path(result["output"]) / result["mod_ff"]
        receipt["notes"].append({"mod_ff_sha256": hashlib.sha256(mod_ff.read_bytes()).hexdigest(),
                                 "mod_ff_bytes": mod_ff.stat().st_size, "rawfiles_verified": result["rawfiles_verified"]})
        step(receipt, "project verify --inputs", PAT + ["project", "verify", str(Path(result["output"]) / "receipt.json"),
                                                        "--inputs", "--output", str(work / "verify"), "--json"])
        step(receipt, "ff inspect mod.ff", PAT + ["ff", "inspect", str(mod_ff), "--output", str(work / "inspect"), "--json"])
        step(receipt, "ff extract rawfiles", PAT + ["ff", "extract", str(mod_ff), "--types", "rawfile",
                                                    "--output", str(work / "extract"), "--json"])
        # Keep the built mod where Tier 3 can find it.
        staged = work / "hello_zm-mod.ff"
        shutil.copyfile(mod_ff, staged)
        receipt["notes"].append({"tier3_mod_ff": str(staged)})
    bad = work / "bad.gsc"
    bad.write_text("main()\n{\n    this is not gsc ;;; \n}\n", encoding="utf-8")
    step(receipt, "gsc compile broken script fails structurally", PAT + ["gsc", "compile", str(bad), "--output", str(work / "bad-compile"), "--json"], expect_ok=False)
    good = work / "good.gsc"
    good.write_text("main()\n{\n    level thread noop();\n}\n\nnoop()\n{\n    wait 1;\n}\n", encoding="utf-8")
    step(receipt, "gsc compile minimal script", PAT + ["gsc", "compile", str(good), "--output", str(work / "good-compile"), "--json"])


def tier_game_collect(receipt, home: Path, notes: str | None):
    state = home / "game"
    for name in ("last-launch.json", "last-load.json", "last-load-check.json", "last-result.json"):
        path = state / name
        if path.is_file():
            try:
                receipt["steps"].append({"name": name, "passed": True, "json": json.loads(path.read_text(encoding="utf-8")),
                                         "expected": "state file present"})
            except ValueError:
                receipt["steps"].append({"name": name, "passed": False, "expected": "valid JSON", "stderr_head": "unreadable"})
        else:
            receipt["steps"].append({"name": name, "passed": False, "expected": "state file present", "stderr_head": "missing"})
    receipt["human_observations"] = {
        "launcher_prompt_shown": None, "game_window_took_focus": None, "main_menu_reached": None,
        "town_spawn_playable": None, "hello_zm_line_visible_after_spawn": None, "quit_exited_cleanly": None,
        "plutonium_build": None, "notes": notes or "Fill these in from what you saw on screen; null means not observed."}
    receipt["notes"].append("Tier 3 commands were run by hand with per-command human authorization; this file collects their saved state and the human's observations.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tier", choices=["offline", "backends", "game"], required=True)
    ap.add_argument("--output", type=Path, required=True, help="Directory for receipts, e.g. docs/receipts/qualify")
    ap.add_argument("--collect", action="store_true", help="Tier game: fold saved state into a receipt; runs nothing")
    ap.add_argument("--notes", help="Tier game: free-text human observations to include")
    ap.add_argument("--allow-non-windows", action="store_true", help="For testing this script only; receipts are marked non-native")
    args = ap.parse_args()
    if os.name != "nt" and not args.allow_non_windows:
        print("This script qualifies native Windows. Run it there.", file=sys.stderr)
        return 2
    home = Path(os.environ.get("PAT_HOME") or (Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "PlutoniumAgentToolkit"))
    os.environ["PAT_HOME"] = str(home)
    work = Path(tempfile.mkdtemp(prefix=f"pat-qualify-{args.tier}-"))
    redact = redactor(extra_paths=[("pat-home", str(home)), ("work", str(work)), ("repo", str(ROOT))])
    receipt = new_receipt(args.tier)
    receipt["environment"]["pat_home_isolated"] = home != Path(os.environ.get("LOCALAPPDATA", "")) / "PlutoniumAgentToolkit"
    receipt["notes"].append(f"work directory {work}")
    try:
        if args.tier == "offline":
            tier_offline(receipt, home, work)
        elif args.tier == "backends":
            tier_backends(receipt, home, work)
        else:
            if not args.collect:
                print("Tier game runs nothing automatically. Run the commands in docs/WINDOWS-QUALIFICATION.md with human authorization, then rerun with --collect.", file=sys.stderr)
                return 2
            tier_game_collect(receipt, home, args.notes)
    finally:
        pass  # the work directory is left for inspection; it holds nothing private
    name = {"offline": "tier1-offline.json", "backends": "tier2-backends.json", "game": "tier3-game.json"}[args.tier]
    return 0 if finish(receipt, args.output / __version__, name, redact) else 1


if __name__ == "__main__":
    sys.exit(main())
