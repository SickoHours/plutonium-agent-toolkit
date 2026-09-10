#!/usr/bin/env python3
"""Verify that every statement of the version agrees before a tag or release.

Checks: package ``__version__``, ``pyproject.toml`` version, top CHANGELOG entry,
``docs/SUPPORT.md`` header, optional ``--tag`` (SemVer form of the PEP 440
version) and that the CHANGELOG has an ``Unreleased`` section. Exit 1 with a JSON
report on any disagreement. This catches the "installed says 0.9.1, changelog
says 0.9.0" drift the toolkit's history already produced once.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from plutonium_agent_toolkit import __version__  # noqa: E402


def pep440_to_semver(version: str) -> str:
    m = re.fullmatch(r"(\d+\.\d+\.\d+)(?:(a|b|rc)(\d+))?", version)
    if not m:
        raise ValueError(f"Unsupported version form: {version}")
    base, kind, n = m.groups()
    if not kind:
        return f"v{base}"
    label = {"a": "alpha", "b": "beta", "rc": "rc"}[kind]
    return f"v{base}-{label}.{n}"


def check(tag: str | None) -> dict:
    problems = []
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pv = pyproject["project"]["version"]
    if pv != __version__:
        problems.append(f"pyproject version {pv} != package __version__ {__version__}")

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(r"^## \[Unreleased\]", changelog, re.M):
        problems.append("CHANGELOG.md lacks an ## [Unreleased] section")
    released = re.findall(r"^## \[(\d[^\]]*)\]", changelog, re.M)
    top = released[0] if released else None
    if top and top != __version__:
        problems.append(f"CHANGELOG top released entry {top} != package version {__version__}")

    support = (ROOT / "docs" / "SUPPORT.md").read_text(encoding="utf-8")
    if f"`{__version__}`" not in support.splitlines()[0]:
        problems.append(f"docs/SUPPORT.md first line does not name version {__version__}")

    expected_tag = pep440_to_semver(__version__)
    if tag and tag != expected_tag:
        problems.append(f"tag {tag} != expected {expected_tag}")

    return {"ok": not problems, "version": __version__, "expected_tag": expected_tag,
            "changelog_top": top, "problems": problems}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag")
    report = check(ap.parse_args().tag)
    print(json.dumps(report, indent=2))
    sys.exit(0 if report["ok"] else 1)
