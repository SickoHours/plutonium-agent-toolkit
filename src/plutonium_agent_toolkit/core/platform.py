"""Platform gating. This release supports native Windows x64 only.

Discovery (``manifest``, ``describe``, ``doctor``, ``version``) runs anywhere so
contributors on other systems can read contracts and run unit tests. Every
command that touches backends, the game or the display requires Windows and
fails with ``unsupported_platform`` before doing anything else.
"""
from __future__ import annotations

import os
import platform
import sys

from .errors import UNSUPPORTED_PLATFORM, Failure

SUPPORTED = ("Windows",)


def system() -> str:
    return platform.system()


def is_windows() -> bool:
    return os.name == "nt"


def is_wine() -> bool:
    """Best-effort detection so receipts never present Wine as native Windows."""
    if not is_windows():
        return False
    try:
        import ctypes

        ntdll = ctypes.WinDLL("ntdll")  # type: ignore[attr-defined]
        return hasattr(ntdll, "wine_get_version")
    except (OSError, AttributeError):
        return False


def describe() -> dict:
    return {
        "system": system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "native_windows": is_windows() and not is_wine(),
        "compatibility_layer": "wine" if is_wine() else None,
        "supported": is_windows(),
    }


def require_windows(operation: str) -> None:
    if not is_windows():
        raise Failure(
            UNSUPPORTED_PLATFORM,
            f"{operation} requires native Windows; this host reports {system()}.",
            "Discovery and unit tests run anywhere. Backend, game and capture operations run on Windows only in this release.",
        )
