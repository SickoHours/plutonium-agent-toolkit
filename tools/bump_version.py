#!/usr/bin/env python3
"""Move the toolkit to a new version in every place the release check reads.

    python tools/bump_version.py 0.1.0b1            # alpha -> beta
    python tools/bump_version.py 0.1.0b1 --date 2026-09-12

Updates ``src/plutonium_agent_toolkit/__init__.py``, ``pyproject.toml``, the first line of
``docs/SUPPORT.md`` and promotes ``## [Unreleased]`` in ``CHANGELOG.md`` to the new version
with today's date, leaving a fresh empty ``Unreleased`` section. Refuses if the Unreleased
section is empty (nothing to release) or if the working tree already has uncommitted changes
to those files. Run ``python tools/release_check.py`` afterwards; commit; then tag with the
SemVer form the release check prints.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["src/plutonium_agent_toolkit/__init__.py", "pyproject.toml", "docs/SUPPORT.md", "CHANGELOG.md"]
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?$")


def current_version() -> str:
    text = (ROOT / "src/plutonium_agent_toolkit/__init__.py").read_text(encoding="utf-8")
    return re.search(r'^__version__ = "([^"]+)"', text, re.M).group(1)


def dirty_targets() -> list[str]:
    out = subprocess.run(["git", "status", "--porcelain", "--", *FILES], capture_output=True, text=True, cwd=ROOT).stdout
    return [line[3:] for line in out.splitlines()]


def bump(new: str, day: str) -> dict:
    if not VERSION_RE.match(new):
        raise SystemExit(f"Version must be PEP 440 like 0.1.0b1 or 1.0.0, got {new!r}")
    old = current_version()
    if new == old:
        raise SystemExit(f"Already at {old}")
    dirty = dirty_targets()
    if dirty:
        raise SystemExit(f"Commit or stash changes to these files first: {dirty}")

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(r"^## \[Unreleased\]\n(.*?)(?=^## \[|\Z)", changelog, re.M | re.S)
    if not m or not m.group(1).strip():
        raise SystemExit("CHANGELOG.md has no Unreleased entries; nothing to release")
    promoted = changelog.replace("## [Unreleased]\n", f"## [Unreleased]\n\n## [{new}] - {day}\n", 1)
    (ROOT / "CHANGELOG.md").write_text(promoted, encoding="utf-8")

    init = ROOT / "src/plutonium_agent_toolkit/__init__.py"
    init.write_text(init.read_text(encoding="utf-8").replace(f'__version__ = "{old}"', f'__version__ = "{new}"'), encoding="utf-8")
    py = ROOT / "pyproject.toml"
    py.write_text(re.sub(r'^version = "[^"]+"', f'version = "{new}"', py.read_text(encoding="utf-8"), count=1, flags=re.M), encoding="utf-8")
    support = ROOT / "docs/SUPPORT.md"
    lines = support.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[0] = lines[0].replace(f"`{old}`", f"`{new}`")
    support.write_text("".join(lines), encoding="utf-8")
    sys.path.insert(0, str(ROOT / "tools"))
    from release_check import pep440_to_semver  # noqa: E402

    return {"old": old, "new": new, "date": day, "tag": pep440_to_semver(new), "files": FILES}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version")
    ap.add_argument("--date", default=date.today().isoformat())
    args = ap.parse_args()
    result = bump(args.version, args.date)
    print(f"{result['old']} -> {result['new']} ({result['date']}); tag as {result['tag']}")
    print("Next: python tools/release_check.py && git add -A && git commit -m 'release: " + result["new"] + "'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
