"""Stand-in for CoDLuaDecompiler: <input.lua>; writes <input>.dec.lua. NO_OUTPUT input writes nothing."""
import sys
from pathlib import Path

src = Path(sys.argv[-1])
if b"NO_OUTPUT" not in src.read_bytes():
    src.with_suffix(".dec.lua").write_text("-- decompiled\nreturn {}\n")
