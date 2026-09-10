"""Platform gating.

The development (file-tool) routes run on Windows and Linux: they drive pinned
upstream backends as ordinary subprocesses. Only the routes that control a running
game or capture its display require native Windows, because their transport is the
Win32 console; those call :func:`require_windows` and fail with
``unsupported_platform`` before doing anything else. Discovery (``manifest``,
``describe``, ``doctor``, ``version``) runs anywhere.
"""
from __future__ import annotations

import os
import platform
import sys

from .errors import UNSUPPORTED_PLATFORM, Failure

# Hosts the development (file) tools are supported on; game control needs native Windows.
SUPPORTED = ("Windows", "Linux")
GAME_CONTROL = ("Windows",)


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
    native_windows = is_windows() and not is_wine()
    return {
        "system": system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "native_windows": native_windows,
        "compatibility_layer": "wine" if is_wine() else None,
        # Development (file) tools: Windows and Linux. macOS is untested and not claimed.
        "dev_tools_supported": system() in SUPPORTED and not is_wine(),
        # Game control and capture: native Windows only (Win32 console transport). `supported`
        # keeps its historical meaning of this flag for discovery consumers.
        "game_control_supported": native_windows,
        "supported": native_windows,
    }


def require_windows(operation: str) -> None:
    if not is_windows():
        raise Failure(
            UNSUPPORTED_PLATFORM,
            f"{operation} requires native Windows; this host reports {system()}.",
            "Development file tools run on Windows and Linux. Game control and capture use the Win32 console and need a native Windows host.",
        )
    if is_wine():
        raise Failure(
            UNSUPPORTED_PLATFORM,
            f"{operation} requires native Windows; this interpreter is running under Wine.",
            "Wine results never count as Windows qualification. Use a native Windows host.",
        )
