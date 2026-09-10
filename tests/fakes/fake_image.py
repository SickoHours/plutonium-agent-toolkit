"""Stand-in for OAT ImageConverter: --no-color --t6 <file.dds|iwi>; writes the other format beside it.
An input containing EMPTY_OUT writes a zero-byte file."""
import sys
from pathlib import Path

src = Path(sys.argv[-1])
dest = src.with_suffix(".iwi" if src.suffix.lower() == ".dds" else ".dds")
dest.write_bytes(b"" if b"EMPTY_OUT" in src.read_bytes() else b"IMG" * 8)
