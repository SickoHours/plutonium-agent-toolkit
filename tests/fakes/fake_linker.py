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
assets = []
loaded = {}
for i, a in enumerate(args):
    if a == "-l":
        try:
            dep = json.loads(Path(args[i + 1]).read_text())
        except (ValueError, OSError):
            print("ERROR: could not load", args[i + 1])
            continue
        for row in dep.get("assets", []):
            loaded[row] = True
        for rel, blob in dep.get("rawfiles", {}).items():
            loaded["rawfile," + rel] = blob
for line in lines:
    if line.startswith("> name,"):
        name = line.split(",", 1)[1].strip()
    if line.startswith("rawfile,"):
        rel = line.split(",", 1)[1]
        local = base / "raw" / rel
        if local.is_file():
            raw[rel] = base64.b64encode(local.read_bytes()).decode()
        elif line in loaded:
            raw[rel] = loaded[line]
        else:
            print("ERROR: Could not find asset rawfile", rel)
    elif line.strip() == "localize,mod":
        strings_file = base / "raw" / "english" / "localizedstrings" / "mod.str"
        if strings_file.is_file():
            for text_line in strings_file.read_text().splitlines():
                if text_line.startswith("REFERENCE "):
                    assets.append("localize," + text_line.split(" ", 1)[1].strip())
        else:
            print("ERROR: Could not find asset localize mod")
    elif "," in line and not line.startswith((">", "//")) and line.strip():
        # a non-rawfile root: must come from a loaded package, like the real linker copying assets out of -l zones
        if line.strip() in loaded:
            assets.append(line.strip())
        else:
            print("ERROR: Could not find asset", line.strip())
out.mkdir(parents=True, exist_ok=True)
payload = {"zone": name, "rawfiles": raw, "assets": assets}
if any(line.strip() == "> fixture_readback_fail" for line in lines):
    payload["readback_fail"] = True
(out / f"{name}.ff").write_text(json.dumps(payload))
if any(line.strip() == "> fixture_linker_error" for line in lines):
    # The real Linker can report an error and still exit zero with a package on disk.
    print("ERROR: Could not find asset material 'missing_mtl'")
print("Linked", name, len(raw), "rawfiles")
