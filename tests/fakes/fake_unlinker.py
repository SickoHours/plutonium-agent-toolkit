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
# A real T6 fastfile is bound to its file name: the zone name keys the compressed streams, so a
# renamed copy fails to inflate (native Tier 3 finding: hello_zm.ff copied to mod.ff hung the
# client). Reproduce it so no test can pass by renaming.
if data.get("zone") and ff.stem != data["zone"]:
    print("ERROR: inflate of stream 0 failed with error code -3: invalid code lengths set")
    sys.exit(1)
if data.get("readback_fail"):
    print("error loading fixture asset; continuing")
    sys.exit(0)
game = data.get("game", "T6")
print(f'Loaded zone "{data.get("zone", ff.stem)}" ({game})')
if "--list" in args:
    print("Content:")
    for rel in data["rawfiles"]:
        print("rawfile,", rel)
    for row in data.get("assets", []):
        kind, name = row.split(",", 1)
        print(f"{kind}, {name}")
    for row in data.get("referenced", []):
        kind, name = row.split(",", 1)
        print(f"{kind}, ,{name}")
    sys.exit(0)
out = Path(args[args.index("--output-folder") + 1])
types = args[args.index("--include-assets") + 1].split(",") if "--include-assets" in args else None
# Real Unlinker dumps only the types it has a dumper for: a requested type with none is written as
# nothing, exit zero, no diagnostic. Model that, so a test cannot pass by extracting rawfiles for a
# caller who asked for something else.
if types is not None and "rawfile" not in types and "localize" not in types:
    print("Extracted 0")
    sys.exit(0)
if types == ["localize"]:
    rows = data.get("strings", {})
    if rows:
        p = out / "english" / "localizedstrings" / "mod.str"
        p.parent.mkdir(parents=True, exist_ok=True)
        body = "".join(f"REFERENCE {k}\nLANG_ENGLISH {json.dumps(v)}\n\n" for k, v in rows.items())
        p.write_text('VERSION "1"\nCONFIG ""\nFILENOTES ""\n\n' + body + "ENDMARKER\n")
    print("Extracted", len(rows))
    sys.exit(0)
for rel, blob in data["rawfiles"].items():
    p = out / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(base64.b64decode(blob))
print("Extracted", len(data["rawfiles"]))
