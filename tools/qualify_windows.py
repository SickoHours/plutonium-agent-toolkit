#!/usr/bin/env python3
"""Run the native Windows qualification tiers and write sanitized receipts.

    python tools/qualify_windows.py --tier offline  --output docs/receipts
    python tools/qualify_windows.py --tier backends --output docs/receipts
    python tools/qualify_windows.py --tier game     --output docs/receipts --collect
    python tools/qualify_windows.py --redact-existing docs/receipts/<version>/<receipt>.json

Tiers 1 and 2 run commands themselves. Tier 3 never touches the game; with --collect it
reads the toolkit's state files after the human-authorized commands were run by hand and
folds them into a receipt. Every receipt is redacted before writing: any drive-letter Users
path for any account, the Windows username, machine name, toolkit home, work directory and
32-hex request/load/job IDs are replaced, and private-scan hit excerpts are dropped.
--redact-existing reapplies the current rules to a committed receipt in place.
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

# Any drive letter, any account, either slash style, single or JSON-escaped separators. This
# does not depend on USERPROFILE, so a truncated excerpt such as C:\Users\m, another account's
# profile or another drive's Users folder cannot survive (maintainer finding on the first
# qualification pull request). The account segment runs to the next separator, quote or line
# end, so names containing spaces ("Jane Doe") are covered too; over-redacting prose that
# follows a bare path is the safe direction.
USERS_PATH = re.compile(r"(?i)[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}[^\\/\"\r\n\t]*")


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
    patterns.append((USERS_PATH, "<userprofile>"))
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
    shown = argv[len(PAT):] if argv[:len(PAT)] == PAT else argv
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=child_env())
    except subprocess.TimeoutExpired as exc:
        return {"argv": shown, "exit_code": 124, "elapsed_seconds": round(time.monotonic() - started, 3), "json": None,
                "stdout_head": str(exc.stdout or "")[:2000], "stderr_head": f"timed out after {timeout}s; " + str(exc.stderr or "")[:1800]}
    except OSError as exc:
        return {"argv": shown, "exit_code": 127, "elapsed_seconds": round(time.monotonic() - started, 3), "json": None,
                "stdout_head": None, "stderr_head": f"could not start: {exc}"}
    elapsed = round(time.monotonic() - started, 3)
    try:
        payload = json.loads(proc.stdout) if proc.stdout.strip() else None
    except ValueError:
        payload = None
    return {"argv": shown, "exit_code": proc.returncode,
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


def supersede(path: Path) -> Path | None:
    """Move an existing receipt aside instead of overwriting it.

    A rerun after a fix must keep the failed attempt (docs/contributors/RECORDING-A-RECEIPT.md)."""
    if not path.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    aside = path.with_name(f"{path.stem}.superseded-{stamp}{path.suffix}")
    n = 1
    while aside.exists():
        n += 1
        aside = path.with_name(f"{path.stem}.superseded-{stamp}-{n}{path.suffix}")
    path.rename(aside)
    return aside


def strip_excerpts(value):
    """Drop ``excerpt`` from embedded private_scan hits: it quotes the offending text itself.

    ``file``, ``line`` and ``pattern`` are enough for a receipt."""
    if isinstance(value, list):
        return [strip_excerpts(v) for v in value]
    if isinstance(value, dict):
        if "excerpt" in value and "pattern" in value and "file" in value:
            value = {k: v for k, v in value.items() if k != "excerpt"}
        return {k: strip_excerpts(v) for k, v in value.items()}
    return value


def sanitize(receipt, redact):
    """Everything a receipt goes through before it is written or rewritten."""
    return redact(strip_excerpts(receipt))


def redact_existing(path: Path, redact) -> bool:
    """Reapply the current redaction rules to a committed receipt in place.

    Returns True if the file changed. A note records the rewrite; an already-clean file is left
    untouched so the operation is idempotent."""
    original = path.read_text(encoding="utf-8")
    data = json.loads(original)
    cleaned = sanitize(data, redact)
    if cleaned == data:
        return False
    cleaned.setdefault("notes", []).append({"re_redacted": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                            "by": "tools/qualify_windows.py --redact-existing"})
    path.write_text(json.dumps(cleaned, indent=2) + "\n", encoding="utf-8")
    return True


def finish(receipt, output: Path, name: str, redact):
    receipt["passed"] = all(s["passed"] for s in receipt["steps"])
    receipt["summary"] = {"steps": len(receipt["steps"]), "passed": sum(s["passed"] for s in receipt["steps"]),
                          "failed": [s["name"] for s in receipt["steps"] if not s["passed"]]}
    output.mkdir(parents=True, exist_ok=True)
    path = output / name
    previous = supersede(path)
    if previous:
        receipt["notes"].append({"superseded": previous.name})
    path.write_text(json.dumps(sanitize(receipt, redact), indent=2) + "\n", encoding="utf-8")
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
        # Stage the built mod at a durable, documented location for Tier 3 step 3h.
        staged_dir = home / "qualify" / "hello_zm"
        staged_dir.mkdir(parents=True, exist_ok=True)
        staged = staged_dir / "mod.ff"
        shutil.copyfile(mod_ff, staged)
        receipt["notes"].append({"tier3_mod_ff": "<pat-home>/qualify/hello_zm/mod.ff"})
        print(f"\nTier 3 step 3h uses this file:\n  pat game install-mod \"{staged}\" hello_zm --json", flush=True)
    bad = work / "bad.gsc"
    bad.write_text("main()\n{\n    this is not gsc ;;; \n}\n", encoding="utf-8")
    step(receipt, "gsc compile broken script fails structurally", PAT + ["gsc", "compile", str(bad), "--output", str(work / "bad-compile"), "--json"], expect_ok=False)
    good = work / "good.gsc"
    good.write_text("main()\n{\n    level thread noop();\n}\n\nnoop()\n{\n    wait 1;\n}\n", encoding="utf-8")
    step(receipt, "gsc compile minimal script", PAT + ["gsc", "compile", str(good), "--output", str(work / "good-compile"), "--json"])


BEGIN_MARKER = "qualify-tier3-begin.json"


def tier_game_begin(home: Path) -> None:
    """Record when the human-authorized Tier 3 run starts so stale state files cannot count."""
    marker = home / "game" / BEGIN_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"began": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                  "began_unix": time.time()}) + "\n", encoding="utf-8")
    print(f"Tier 3 begun at {marker.read_text().strip()}. Run the commands in docs/WINDOWS-QUALIFICATION.md, then rerun with --collect.")


def _fresh(path: Path, began_unix: float) -> bool:
    return path.stat().st_mtime >= began_unix - 1


def tier_game_collect(receipt, home: Path, notes: str | None):
    state = home / "game"
    marker = state / BEGIN_MARKER
    if not marker.is_file():
        raise SystemExit("Run `--tier game --begin` before the Tier 3 commands; no begin marker found, so freshness cannot be established.")
    began = json.loads(marker.read_text(encoding="utf-8"))["began_unix"]
    receipt["notes"].append({"tier3_began_unix": began})

    def load(name):
        path = state / name
        if not path.is_file():
            return None, "missing"
        if not _fresh(path, began):
            return None, "stale: written before this Tier 3 run began"
        try:
            return json.loads(path.read_text(encoding="utf-8")), None
        except ValueError:
            return None, "unreadable JSON"

    checks = {
        "last-launch.json": lambda d: d.get("launch_requested") is True and d.get("game_detected") is True,
        "last-load.json": lambda d: d.get("status") == "engine-state-verified",
        "last-load-check.json": lambda d: d.get("verified") is True and d.get("state_matches") is True,
        "last-result.json": lambda d: d.get("ok") is True,
    }
    for name, check in checks.items():
        data, problem = load(name)
        if problem:
            receipt["steps"].append({"name": name, "passed": False, "expected": "fresh, successful state", "stderr_head": problem})
            continue
        passed = bool(check(data))
        receipt["steps"].append({"name": name, "passed": passed, "json": data,
                                 "expected": "fresh, successful state",
                                 **({} if passed else {"stderr_head": "state file present but does not record success"})})
    installs = sorted((state / "installs").glob("hello_zm-*.json")) if (state / "installs").is_dir() else []
    fresh_installs = [p for p in installs if _fresh(p, began)]
    receipt["steps"].append({"name": "install-mod hello_zm receipt", "passed": bool(fresh_installs),
                             "json": json.loads(fresh_installs[-1].read_text(encoding="utf-8")) if fresh_installs else None,
                             "expected": "fresh install receipt", **({} if fresh_installs else {"stderr_head": "no fresh hello_zm install receipt"})})
    receipt["human_observations"] = {
        "launcher_prompt_shown": None, "game_window_took_focus": None, "main_menu_reached": None,
        "town_spawn_playable": None, "hello_zm_line_visible_after_spawn": None, "quit_exited_cleanly": None,
        "plutonium_build": None, "notes": notes or "Fill these in from what you saw on screen; null means not observed."}
    receipt["notes"].append("Tier 3 commands were run by hand with per-command human authorization. Only state files written after the begin marker count, and each must record success. The human observations are required for level `game`; automated state alone is not a playable spawn.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tier", choices=["offline", "backends", "game"])
    ap.add_argument("--output", type=Path, help="Directory for receipts, e.g. docs/receipts")
    ap.add_argument("--begin", action="store_true", help="Tier game: write the begin marker before the human-authorized commands")
    ap.add_argument("--collect", action="store_true", help="Tier game: fold saved state into a receipt; runs nothing")
    ap.add_argument("--notes", help="Tier game: free-text human observations to include")
    ap.add_argument("--allow-non-windows", action="store_true", help="For testing this script only; receipts are marked non-native")
    ap.add_argument("--redact-existing", type=Path, metavar="FILE",
                    help="Reapply the current redaction rules to a committed receipt in place; runs nothing, works on any platform")
    args = ap.parse_args()
    home = Path(os.environ.get("PAT_HOME") or (Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "PlutoniumAgentToolkit"))
    if args.redact_existing:
        changed = redact_existing(args.redact_existing, redactor(extra_paths=[("pat-home", str(home)), ("repo", str(ROOT))]))
        print(f"{'re-redacted' if changed else 'already clean'}: {args.redact_existing}")
        return 0
    if not args.tier:
        ap.error("--tier is required unless --redact-existing is given")
    if not args.output and not (args.begin and args.tier == "game"):
        # Only `--tier game --begin` writes nothing but the marker under PAT_HOME
        # (docs/WINDOWS-QUALIFICATION.md); every other tier writes a receipt and needs --output.
        ap.error("--output is required unless `--tier game --begin` or --redact-existing is given")
    if os.name != "nt" and not args.allow_non_windows:
        print("This script qualifies native Windows. Run it there.", file=sys.stderr)
        return 2
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
            if args.begin:
                tier_game_begin(home)
                return 0
            if not args.collect:
                print("Tier game runs nothing automatically. Use --begin, run the commands in docs/WINDOWS-QUALIFICATION.md with human authorization, then rerun with --collect.", file=sys.stderr)
                return 2
            tier_game_collect(receipt, home, args.notes)
    finally:
        pass  # the work directory is left for inspection; it holds nothing private
    name = {"offline": "tier1-offline.json", "backends": "tier2-backends.json", "game": "tier3-game.json"}[args.tier]
    return 0 if finish(receipt, args.output / __version__, name, redact) else 1


if __name__ == "__main__":
    sys.exit(main())
