"""Stand-in for gsc-tool: -m comp|decomp -g t6 -s pc -i server|client [-w include] input.
Writes compiled/<name> or decompiled/<name> under the current directory.
A source containing the token FAIL_COMPILE prints an error line and exits 0, like the real tool can."""
import hashlib
import sys
from pathlib import Path

args = sys.argv[1:]
mode = args[args.index("-m") + 1]
src = Path(args[-1])
text = src.read_text(encoding="utf-8", errors="replace")
if "FAIL_COMPILE" in text:
    print("error: fixture compile failure at line 1")
    sys.exit(0)
if "CRASH" in text:
    print("segfault fixture")
    sys.exit(3)
if "SPAM_LOG" in text:
    for _ in range(2000):
        print("x" * 80)
if "HIJACK_RECEIPT" in text:
    receipt = Path("receipt.json")
    receipt.unlink(missing_ok=True)
    receipt.mkdir()
out = Path("compiled" if mode == "comp" else "decompiled") / src.name
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(b"COMPILED:" + hashlib.sha256(text.encode()).hexdigest().encode())
print("compiled", src.name)
