"""Which source this toolkit is running from, when that is knowable.

An editable install runs the package straight out of a git checkout, so the commit and
the working tree's cleanliness are facts about the code executing right now. A wheel
installed into site-packages carries no such fact, and guessing one would be worse than
saying nothing: both fields are then ``None``.

Nothing here raises. git may be absent, the checkout may be unreadable, the call may
hang on a network-mounted repository -- every one of those is "unknown", not a failure
of the command the caller actually ran. It reads only: ``rev-parse`` and ``status``,
never a fetch, a write or a config change.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

# The editable layout this recognizes, and the only one: <checkout>/src/plutonium_agent_toolkit.
# An installed copy that happens to sit inside some unrelated repository is not this package's
# source, and reporting that repository's commit would be a false claim about this code.
_PACKAGE = Path(__file__).resolve().parent.parent
_TIMEOUT = 10

UNKNOWN: dict[str, str | bool | None] = {"source_commit": None, "dirty": None}


def _git(root: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                              timeout=_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def identity(package: Path | None = None) -> dict[str, str | bool | None]:
    """``{"source_commit": <40 hex or None>, "dirty": <bool or None>}`` for this install."""
    try:
        directory = Path(package) if package is not None else _PACKAGE
        top = _git(directory, "rev-parse", "--show-toplevel")
        if top is None:
            return dict(UNKNOWN)
        checkout = Path(top.strip())
        if directory.resolve() != (checkout / "src" / directory.name).resolve():
            return dict(UNKNOWN)
        head = _git(checkout, "rev-parse", "HEAD")
        if head is None:
            return dict(UNKNOWN)
        commit = head.strip()
        if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
            return dict(UNKNOWN)
        changes = _git(checkout, "status", "--porcelain")
        return {"source_commit": commit, "dirty": None if changes is None else bool(changes.strip())}
    except Exception:  # noqa: BLE001 -- reporting provenance may never break the route reporting it
        return dict(UNKNOWN)
