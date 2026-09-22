"""Structural checks of compiler output; not runtime or external-symbol validation."""
from __future__ import annotations

from pathlib import Path

from ..core.errors import BACKEND_FAILED, Failure

T6_PC_MAGIC = bytes.fromhex("804753430d0a0006")
T6_PC_HEADER_SIZE = 64
T6_STRING_ADDRESS_MAX = 0xFFFF


def check_t6_string_pool(path: Path) -> dict:
    """Check header-v1 pool *starts*, including offsets which wrap to valid strings.

    xensik/gsc-tool arc assembler writes string references as u16. Its header-v1
    string pool follows the 64-byte header and ends at include_offset (u32 at12).
    A final string can extend beyond 65535 if its starting address still fits.
    This is deliberately not a full script validator or a pool-end working budget.
    """
    data = path.read_bytes()
    details = {"check": "t6-string-pool", "artifact": path.name}
    if len(data) < T6_PC_HEADER_SIZE or data[:8] != T6_PC_MAGIC:
        raise Failure(BACKEND_FAILED, "Compiler output is not a T6 PC header-v1 script", **details)
    pool_end = int.from_bytes(data[12:16], "little")
    if not T6_PC_HEADER_SIZE <= pool_end <= len(data):
        raise Failure(BACKEND_FAILED, "Invalid T6 string-pool boundary", pool_end=pool_end, **details)
    offset, count, maximum = T6_PC_HEADER_SIZE, 0, None
    while offset < pool_end:
        if offset > T6_STRING_ADDRESS_MAX:
            raise Failure(BACKEND_FAILED, "T6 string-pool address exceeds its 16-bit reference",
                          "Shorten or split script text and rebuild; successful compilation or disassembly alone is insufficient.",
                          string_start=offset, address_limit=T6_STRING_ADDRESS_MAX, pool_end=pool_end, **details)
        end = data.find(b"\0", offset, pool_end)
        if end < 0:
            raise Failure(BACKEND_FAILED, "Unterminated string in T6 compiler output", string_start=offset, **details)
        maximum, count, offset = offset, count + 1, end + 1
    return {"check": "t6-string-pool", "pool_start": T6_PC_HEADER_SIZE, "pool_end": pool_end,
            "string_count": count, "maximum_string_start": maximum,
            "address_limit": T6_STRING_ADDRESS_MAX}
