"""Stand-in for blender --background ... --python worker -- request.json.
Reads the request, writes model-result.json and the destination file. Input containing FAIL writes nothing."""
import json
import sys
from pathlib import Path

request = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text())
src = Path(request["input"])
if b"FAIL" in src.read_bytes():
    print("Error: fixture import failure")
    sys.exit(1)
before = {"totals": {"objects": 1, "meshes": 1, "vertices": 8, "bones": 1, "missing_images": 0}, "objects": [{"name": "cube", "type": "MESH"}]}
result = {"before": before, "after": before, "action": request["action"]}
if "destination" in request:
    Path(request["destination"]).write_bytes(b"MODEL" * 4)
    result["file"] = request["destination"]
if request["action"] == "rename-bones":
    result["renamed"] = request["mapping"]
Path(request["result"]).write_text(json.dumps(result))
