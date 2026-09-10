#!/usr/bin/env python3
"""Refuse commits that carry private material from the authoring environment.

Scans tracked text files for personal paths, usernames, machine names, private
thread/run identifiers, tokens and raw evidence. Exit 1 with a JSON report on
any hit. Add legitimate exceptions to ALLOW with a reason; never widen a pattern
to make a hit disappear.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATTERNS = {
    "personal_home": re.compile(r"/home/[a-z][a-z0-9_-]*/|Z:\\\\home\\\\|C:\\\\Users\\\\(?!<)[A-Za-z]"),
    "authoring_desktop": re.compile(r"\bomarchy\b|\bhyprland\b|\bhyprctl\b", re.I),
    "private_thread_or_run_id": re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    "raw_console_log": re.compile(r"^\[\d{2}:\d{2}:\d{2}\] .*(?:script (?:runtime |compile )?error|fatal error)", re.M | re.I),
    "old_internal_command_names": re.compile(r"\bhalo-(?:modding|plutonium)-dev\b|\bhalo_modding\b"),
}
ALLOW = {
    # path: reason
    "tools/private_scan.py": "defines the patterns",
    "PROVENANCE.md": "records upstream private commit SHAs (40-hex, not UUIDs) and old command names for lineage",
}
TEXT_SUFFIXES = {".py", ".md", ".json", ".toml", ".yml", ".yaml", ".txt", ".cmd", ".ps1", ".gsc", ".csc", ".cfg", ".ini", ""}


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                             cwd=ROOT, check=True, capture_output=True).stdout
        names = [n for n in out.decode().split("\0") if n]
    except (subprocess.SubprocessError, OSError):
        names = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]
    return [ROOT / n for n in names]


def scan() -> dict:
    hits = []
    for path in tracked_files():
        rel = path.relative_to(ROOT).as_posix()
        if path.suffix not in TEXT_SUFFIXES or not path.is_file():
            continue
        if rel in ALLOW:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                hits.append({"file": rel, "line": line, "pattern": name, "excerpt": match.group(0)[:60]})
    return {"ok": not hits, "hits": hits, "allow": ALLOW, "files_scanned": len(tracked_files())}


if __name__ == "__main__":
    report = scan()
    print(json.dumps(report, indent=2))
    sys.exit(0 if report["ok"] else 1)
