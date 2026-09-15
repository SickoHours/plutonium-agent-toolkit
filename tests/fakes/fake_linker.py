"""Stand-in for OAT Linker: --no-color --base-folder B --output-folder O [-l dep]... zone
Packs every 'rawfile,<path>' in B/zone_source/<zone>.zone from B/raw into O/<zone>.ff as JSON.

Two behaviours of the real Linker are modelled because the composer depends on them:

* every asset it roots is logged as `Loaded <type> "<name>" (src: <zone>)`, naming the loaded zone
  the copy came from (`disk` for the project's own files), and
* an `ignore,<project>` row reads `zone_source/assetlist/<project>.csv` and turns every `type,name`
  in it into an ignored name: a reference (`,<name>`) is written instead of a copy, and the name is
  never taken from a loaded zone. A dep package's `pulls` list stands in for a material closure -
  the names a loaded zone drags in on its own, which is exactly where donor shadowing happens.
"""
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
referenced = []
loaded = {}
source_of = {}
pulls = []
for i, a in enumerate(args):
    if a == "-l":
        try:
            dep = json.loads(Path(args[i + 1]).read_text())
        except (ValueError, OSError):
            print("ERROR: could not load", args[i + 1])
            continue
        dep_zone = dep.get("zone") or Path(args[i + 1]).stem
        for row in dep.get("assets", []):
            loaded[row] = True
            source_of.setdefault(row, dep_zone)
        for row in dep.get("pulls", []):
            pulls.append((row, dep_zone))
        for rel, blob in dep.get("rawfiles", {}).items():
            loaded["rawfile," + rel] = blob
            source_of.setdefault("rawfile," + rel, dep_zone)
ignored = set()
for line in lines:
    if line.startswith("ignore,"):
        listing = base / "zone_source" / "assetlist" / (line.split(",", 1)[1].strip() + ".csv")
        if not listing.is_file():
            print("ERROR: Failed to read asset listing for ignoring assets of project", line)
            continue
        for row in listing.read_text().splitlines():
            if "," in row:
                row_kind, row_name = row.split(",", 1)
                ignored.add((row_kind.strip(), row_name.strip().strip('"').replace('""', '"')))


def root(kind, name, src):
    """Emit one asset the way the Linker does: an ignored name becomes a reference, never a copy."""
    if (kind, name) in ignored:
        row = f"{kind},{name}"
        if row not in referenced:
            referenced.append(row)
        return
    assets.append(f"{kind},{name}")
    print(f'Loaded {kind} "{name}" (src: {src})')

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
    elif line.startswith("ignore,"):
        continue
    elif line.startswith("image,"):
        # The real Linker reads an image from raw/images/<name>.iwi when it is there
        # ("Loaded image ... (src: disk)") and falls back to a loaded zone's copy otherwise.
        # `name` is the zone's own name from `> name,X`; never shadow it with an asset's.
        asset_name = line.split(",", 1)[1].strip()
        local = base / "raw" / "images" / (asset_name + ".iwi")
        if local.is_file():
            root("image", asset_name, "disk")
        elif line.strip() in loaded:
            root("image", asset_name, source_of.get(line.strip(), "unknown"))
        else:
            print("ERROR: Could not find asset", line.strip())
    elif "," in line and not line.startswith((">", "//")) and line.strip():
        # a non-rawfile root: must come from a loaded package, like the real linker copying assets out of -l zones
        if line.strip() in loaded:
            asset_kind, asset_name = line.strip().split(",", 1)
            root(asset_kind, asset_name, source_of.get(line.strip(), "unknown"))
        else:
            print("ERROR: Could not find asset", line.strip())
# A loaded zone's own closure: names nothing in this zone asked for by hand, which is how a donor
# zone's copy of a base-owned image ends up in the pack when nothing excludes it.
for row, dep_zone in pulls:
    if "," not in row or row in assets:
        continue
    asset_kind, asset_name = row.split(",", 1)
    root(asset_kind, asset_name, dep_zone)
out.mkdir(parents=True, exist_ok=True)
payload = {"zone": name, "rawfiles": raw, "assets": assets, "referenced": referenced}
if any(line.strip() == "> fixture_readback_fail" for line in lines):
    payload["readback_fail"] = True
(out / f"{name}.ff").write_text(json.dumps(payload))
if any(line.strip() == "> fixture_linker_error" for line in lines):
    # The real Linker can report an error and still exit zero with a package on disk.
    print("ERROR: Could not find asset material 'missing_mtl'")
print("Linked", name, len(raw), "rawfiles")
