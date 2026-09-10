"""Stand-in for OAT Unlinker. --list prints the inventory; --output-folder D extracts rawfiles."""
import base64
import json
import sys
from pathlib import Path

args = sys.argv[1:]
ff = Path(args[-1])
try:
    data = json.loads(ff.read_text())
except ValueError:
    print("Failed to load fastfile", ff)
    sys.exit(1)
if "--list" in args:
    for rel in data["rawfiles"]:
        print("rawfile", rel)
    sys.exit(0)
out = Path(args[args.index("--output-folder") + 1])
for rel, blob in data["rawfiles"].items():
    p = out / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(base64.b64decode(blob))
print("Extracted", len(data["rawfiles"]))
