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
raw = {}
for line in lines:
    if line.startswith("rawfile,"):
        rel = line.split(",", 1)[1]
        raw[rel] = base64.b64encode((base / "raw" / rel).read_bytes()).decode()
out.mkdir(parents=True, exist_ok=True)
payload = {"zone": zone, "rawfiles": raw}
if any(line.strip() == "> fixture_readback_fail" for line in lines):
    payload["readback_fail"] = True
(out / f"{zone}.ff").write_text(json.dumps(payload))
print("Linked", zone, len(raw), "rawfiles")
