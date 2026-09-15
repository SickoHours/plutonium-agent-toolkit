"""Stand-in for a workspace adapter builder: <recipe.json> --output <dir>.
Writes build.json (status succeeded), stage/mod.ff as the JSON the fake unlinker reads, a bank
beside it and the recipe's loose scripts under stage/scripts/. A recipe whose module is
'broken' reports status failed; one named 'silent' exits 0 with nothing."""
import base64
import json
import sys
from pathlib import Path

args = sys.argv[1:]
recipe = Path(args[0])
out = Path(args[args.index("--output") + 1])
data = json.loads(recipe.read_text())
out.mkdir(parents=True)
if data.get("module") == "silent":
    sys.exit(0)
if data.get("module") == "broken":
    (out / "build.json").write_text(json.dumps({"status": "failed", "error": "fixture"}))
    sys.exit(0)
stage = out / "stage"
stage.mkdir()
# A real builder owns its output directory and may write its own readback there.
(out / "readback").mkdir()
(out / "readback" / "builder-listing.txt").write_text("builder-owned\n")
weapons = data.get("weapons") or ([data["weapon"]] if data.get("weapon") else [])
assets = [f"weapon,{w}" for w in weapons]
bank = (data.get("soundbank") or {}).get("name")
if bank:
    assets.append(f"soundbank,{bank}")
    (stage / f"{bank}.sabl").write_bytes(b"BANK " + bank.encode())
for k in data.get("localize", {}):
    assets.append(f"localize,{k}")
for x in (data.get("assets") or {}).get("xmodel", []):
    assets.append(f"xmodel,{x}")
rawfiles = {}
for r in data.get("rawfiles", []):
    rawfiles[r] = base64.b64encode(b"RAW " + r.encode()).decode()
scripts = data.get("loose_scripts") or ([data["loose_script"]] if data.get("loose_script") else [])
for s in scripts:
    dest = stage / s["target"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"COMPILED:" + (recipe.parent / s["source"]).read_bytes())
(stage / "mod.ff").write_text(json.dumps({"zone": "mod", "rawfiles": rawfiles, "assets": assets, "referenced": []}))
(out / "build.json").write_text(json.dumps({"status": "succeeded", "mod_ff_sha256": "fixture"}))
print("built", data.get("module"))
