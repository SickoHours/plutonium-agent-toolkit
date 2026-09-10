#!/usr/bin/env python3
"""Print the CHANGELOG section for one version, for use as GitHub Release notes.

    python tools/release_notes.py 0.1.0a1          # PEP 440 form
    python tools/release_notes.py v0.1.0-alpha.1   # tag form, converted
    python tools/release_notes.py --unreleased     # the Unreleased section

Exit 1 if the section is missing or empty, so a release cannot ship without notes.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def semver_to_pep440(tag: str) -> str:
    m = re.fullmatch(r"v?(\d+\.\d+\.\d+)(?:-(alpha|beta|rc)\.(\d+))?", tag)
    if not m:
        return tag
    base, label, n = m.groups()
    if not label:
        return base
    return base + {"alpha": "a", "beta": "b", "rc": "rc"}[label] + n


def section(version: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = re.escape(version)
    m = re.search(rf"^## \[{heading}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    if not m:
        raise SystemExit(f"CHANGELOG.md has no section for {version}")
    body = m.group(1).strip()
    if not body:
        raise SystemExit(f"CHANGELOG.md section for {version} is empty")
    return body


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version", nargs="?")
    ap.add_argument("--unreleased", action="store_true")
    args = ap.parse_args()
    if args.unreleased:
        version = "Unreleased"
    elif args.version:
        version = semver_to_pep440(args.version)
    else:
        ap.error("give a version or --unreleased")
    body = section(version)
    footer = ("\n\n---\n*Every route's evidence level is in "
              "[docs/SUPPORT.md](https://github.com/SickoHours/plutonium-agent-toolkit/blob/main/docs/SUPPORT.md). "
              "Native Windows receipts are under `docs/receipts/`. "
              "Screen recording and the autonomous test runner are deferred to a later release.*")
    print(body + (footer if version != "Unreleased" else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
