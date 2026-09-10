"""The JSON result envelope every command prints to stdout.

Callers keep the whole stdout document and the process exit status. The two
together are the receipt of that invocation. Nothing else is authoritative.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone

from .. import SCHEMA_VERSION, __version__
from .errors import EXIT_OK, Failure


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def request_id() -> str:
    return uuid.uuid4().hex


def success(command: str, result: dict | None = None, **extra) -> dict:
    row = {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "toolkit_version": __version__,
        "command": command,
        "request_id": request_id(),
        "at": now(),
    }
    if result is not None:
        row["result"] = result
    row.update(extra)
    return row


def failure(command: str, error: Failure) -> dict:
    row = error.to_dict()
    row.update(schema_version=SCHEMA_VERSION, toolkit_version=__version__,
               command=command, request_id=request_id(), at=now())
    return row


def emit(row: dict, stream=None) -> int:
    """Print one JSON document and return the exit status it implies."""
    stream = stream or sys.stdout
    json.dump(row, stream, indent=2, sort_keys=False, allow_nan=False, ensure_ascii=False)
    stream.write("\n")
    stream.flush()
    if row.get("ok"):
        return EXIT_OK
    return Failure(row.get("error_code", "failure"), row.get("message", "")).exit_status()
