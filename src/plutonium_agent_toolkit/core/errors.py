"""Stable error codes and exit statuses shared by every command.

Exit statuses
    0   success within the returned scope
    1   operation, backend or environment failure
    2   invalid arguments or unknown route
    130 cancelled

Every failure carries a stable ``error_code`` string. Codes are part of the
public contract from 1.0 onward; add new codes, never repurpose old ones.
"""
from __future__ import annotations

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_CANCELLED = 130

# Argument and routing
INVALID_ARGUMENTS = "invalid_arguments"
UNKNOWN_ROUTE = "unknown_route"
# Environment and platform
UNSUPPORTED_PLATFORM = "unsupported_platform"
CONFIG_INVALID = "config_invalid"
CONFIG_MISSING = "config_missing"
# Inputs and outputs
INPUT_MISSING = "input_missing"
INPUT_INVALID = "input_invalid"
INPUT_LIMIT = "input_limit"
OUTPUT_EXISTS = "output_exists"
OUTPUT_LIMIT = "output_limit"
# Backends and jobs
BACKEND_UNAVAILABLE = "backend_unavailable"
BACKEND_FAILED = "backend_failed"
BACKEND_TIMEOUT = "backend_timeout"
BUSY = "busy"
CANCELLED = "cancelled"
# Verification
ARTIFACT_CHANGED = "artifact_changed"
INPUT_CHANGED = "input_changed"
HASH_MISMATCH = "hash_mismatch"
# Game and delivery
GAME_NOT_FOUND = "game_not_found"
GAME_AMBIGUOUS = "game_ambiguous"
DELIVERY_UNCERTAIN = "delivery_uncertain"
LOAD_UNVERIFIED = "load_unverified"
NOT_IMPLEMENTED = "not_implemented"
OPERATION_FAILED = "operation_failed"

USAGE_CODES = frozenset({INVALID_ARGUMENTS, UNKNOWN_ROUTE})


class Failure(Exception):
    """A structured, reportable failure. Never raised for programmer errors."""

    def __init__(self, code: str, message: str, hint: str = "", **details):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.details = details

    def exit_status(self) -> int:
        if self.code == CANCELLED:
            return EXIT_CANCELLED
        if self.code in USAGE_CODES:
            return EXIT_USAGE
        return EXIT_FAILURE

    def to_dict(self) -> dict:
        row = {"ok": False, "error_code": self.code, "message": self.message}
        if self.hint:
            row["hint"] = self.hint
        if self.details:
            row["details"] = self.details
        return row
