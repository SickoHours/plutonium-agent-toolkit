"""Stand-in for OAT Linker: --no-color --base-folder B --output-folder O [-l dep]... zone
Packs every 'rawfile,<path>' in B/zone_source/<zone>.zone from B/raw into O/<zone>.ff as JSON."""
import base64
import json
import sys
from pathlib import Path

args = sys.argv[1:]
base = Path(args[args.index("--base-folder") + 1])
out = Path(args[args.index("--output-folder") + 1])
zone = args[-1]
lines = (base / "zone_source" / f"{zone}.zone").read_text().splitlines()
# Like the real Linker, the fastfile is named after the zone's `> name,X` metadata, not the
# .zone file, and that name is the zone name baked into the output (native Tier 2/3 finding).
name = zone
raw = {}
for line in lines:
    if line.startswith("> name,"):
        name = line.split(",", 1)[1].strip()
    if line.startswith("rawfile,"):
        rel = line.split(",", 1)[1]
        raw[rel] = base64.b64encode((base / "raw" / rel).read_bytes()).decode()
out.mkdir(parents=True, exist_ok=True)
payload = {"zone": name, "rawfiles": raw}
if any(line.strip() == "> fixture_readback_fail" for line in lines):
    payload["readback_fail"] = True
(out / f"{name}.ff").write_text(json.dumps(payload))
if any(line.strip() == "> fixture_linker_error" for line in lines):
    # The real Linker can report an error and still exit zero with a package on disk.
    print("ERROR: Could not find asset material 'missing_mtl'")
print("Linked", name, len(raw), "rawfiles")
