"""``model inspect|convert|transform|rename-bones|retime|preview`` through Blender.

Blender runs in background mode with factory settings and autoexec disabled.
It receives one validated JSON request file, never Python text, and runs the
bundled ``blender_worker.py``. The Cast add-on is loaded from the pinned backend
directory by explicit path; the user's Blender preferences are never touched.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from ..core import config
from ..core.errors import BACKEND_FAILED, BACKEND_UNAVAILABLE, INPUT_INVALID, Failure
from ..core.jobs import Job
from .backends import executable

FORMATS = (".blend", ".cast", ".gltf", ".glb", ".obj", ".fbx")
OUTPUTS = ("blend", "cast", "glb", "gltf", "obj", "fbx")
ACTIONS = ("inspect", "convert", "transform", "rename-bones", "retime", "preview")
WORKER = Path(__file__).with_name("blender_worker.py")


def add_parser(sub, common):
    p = sub.add_parser("model", help="Model, rig and animation operations through background Blender")
    a = p.add_subparsers(dest="action", required=True)
    for action in ACTIONS:
        q = a.add_parser(action)
        q.add_argument("input", help="Model file: " + ", ".join(FORMATS))
        q.add_argument("--rig", help="Rig model for an animation-only Cast input")
        if action not in ("inspect", "preview"):
            q.add_argument("--format", choices=OUTPUTS, default="cast")
        if action == "transform":
            q.add_argument("--scale", type=float, default=1.0)
            q.add_argument("--rotate", type=float, nargs=3, default=[0.0, 0.0, 0.0], metavar=("X", "Y", "Z"), help="Degrees applied to root objects")
        if action == "rename-bones":
            q.add_argument("--mapping", required=True, help="JSON file of old-name to new-name pairs")
        if action == "retime":
            q.add_argument("--fps", type=int, required=True)
        common(q)


def cast_addon_dir() -> str:
    path = Path(config.load()["backends_dir"]) / "cast"
    if not (path / "io_scene_cast" / "__init__.py").is_file():
        raise Failure(BACKEND_UNAVAILABLE, f"Cast add-on is not installed at {path}", "Run: pat dev setup --only cast")
    return str(path)


def execute(args, job: Job) -> dict:
    src = job.input(args.input)
    if src.suffix.lower() not in FORMATS:
        raise Failure(INPUT_INVALID, "Supported models: " + ", ".join(FORMATS))
    request = {"input": str(src), "action": args.action, "cast_addon": cast_addon_dir(),
               "result": str(job.root / "model-result.json")}
    if getattr(args, "rig", None):
        if src.suffix.lower() != ".cast":
            raise Failure(INPUT_INVALID, "--rig applies to an animation-only Cast input")
        request["rig"] = str(job.input(args.rig))
    if args.action != "inspect":
        extension = "png" if args.action == "preview" else args.format
        request["destination"] = str(job.root / f"model.{extension}")
    if args.action == "transform":
        if not math.isfinite(args.scale) or not 0 < args.scale <= 10000:
            raise Failure(INPUT_INVALID, "Scale must be positive and at most 10000")
        if any(not math.isfinite(x) for x in args.rotate):
            raise Failure(INPUT_INVALID, "Rotation must be finite")
        request.update(scale=args.scale, rotate=list(args.rotate))
    if args.action == "rename-bones":
        mapping_path = job.input(args.mapping, limit=65536)
        try:
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise Failure(INPUT_INVALID, "Mapping must be a JSON object") from exc
        if not isinstance(mapping, dict) or not 0 < len(mapping) <= 1024 or any(
                not isinstance(k, str) or not isinstance(v, str)
                or not 1 <= len(k.encode()) <= 63 or not 1 <= len(v.encode()) <= 63
                or any(ord(c) < 32 for c in k + v) for k, v in mapping.items()):
            raise Failure(INPUT_INVALID, "Expected 1-1024 old/new bone name pairs of 1-63 UTF-8 bytes without control characters")
        request["mapping"] = mapping
    if args.action == "retime":
        if not 1 <= args.fps <= 240:
            raise Failure(INPUT_INVALID, "FPS must be 1-240")
        request["fps"] = args.fps
    request_path = job.root / "request.json"
    request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
    job.run([*executable("blender"), "--background", "--factory-startup", "--disable-autoexec", "--threads", "2",
             "--python-exit-code", "1", "--python", str(WORKER), "--", str(request_path)], timeout=args.timeout)
    result_path = Path(request["result"])
    if not result_path.is_file():
        raise Failure(BACKEND_FAILED, "Blender worker wrote no result; see the step log")
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise Failure(BACKEND_FAILED, "Blender worker result is not valid JSON") from exc
    if args.action != "inspect":
        output = Path(request["destination"])
        if not output.is_file() or output.stat().st_size == 0:
            raise Failure(BACKEND_FAILED, "Blender produced no output file")
        result["file"] = output.name
        fmt = getattr(args, "format", None)
        if fmt == "obj":
            result["format_limitation"] = "OBJ stores mesh geometry and materials; rigs and animations are dropped."
        elif fmt == "cast":
            result["format_limitation"] = "Cast triangulates meshes and may split vertices at UV seams."
    result["verification"] = "Blender inspection before/after; in-game appearance and animation untested"
    return result
