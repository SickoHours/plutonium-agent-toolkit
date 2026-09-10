"""``project init|plan|build|verify``: a declarative recipe for a T6 Zombies mod.

Recipe (``project.json``, schema 1)::

    {
      "schema": 1, "game": "t6", "name": "hello_zm",
      "scripts": [{"source": "scripts/hello.gsc", "target": "scripts/zm/hello_zm.gsc", "instance": "server"}],
      "assets":  [{"source": "note.txt", "target": "note.txt", "type": "rawfile"}],
      "loads":   []
    }

``plan`` validates the recipe and hashes every declared input without running a
backend. ``build`` compiles each script, stages compiled scripts and assets into
an OAT project, links ``mod.ff``, reads it back and byte-compares every rawfile.
``verify`` re-hashes a receipt's outputs and, with ``--inputs``, its inputs.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

from ..core.errors import BACKEND_FAILED, INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING, Failure
from ..core.jobs import Job
from ..core.receipts import sha256_file, verify_outputs
from . import fastfiles, scripts
from .backends import executable

NAME = re.compile(r"^[a-z0-9_]{1,64}$")
ZONE_PART = re.compile(r"^[A-Za-z0-9_.-]{1,255}$")
MAX_SCRIPTS, MAX_ASSETS, MAX_LOADS = 128, 4096, 32

INIT_SCRIPT = '''// Created by pat project init. Prints once when the map starts.
#include maps\\mp\\_utility;

main()
{
    level thread on_start();
}

on_start()
{
    flag_wait( "initial_blackscreen_passed" );
    iprintln( "^2{name} loaded" );
}
'''


def add_parser(sub, common):
    p = sub.add_parser("project", help="Declarative T6 mod recipes: init, plan, build, verify")
    actions = p.add_subparsers(dest="action", required=True)
    q = actions.add_parser("init", help="Create a minimal recipe and source in a new directory")
    q.add_argument("--name", default="my_mod", help="Mod name: lowercase letters, digits, underscore")
    common(q)
    for action, help_text in (("plan", "Validate a recipe and hash inputs; runs no backend"),
                              ("build", "Compile, link, read back and compare")):
        q = actions.add_parser(action, help=help_text)
        q.add_argument("recipe", help="Path to project.json")
        common(q)
    q = actions.add_parser("verify", help="Re-hash a build receipt's outputs")
    q.add_argument("receipt", help="Path to a build's receipt.json")
    q.add_argument("--inputs", action="store_true", help="Also re-hash the recorded inputs at their original paths")
    common(q)


def _rel(text: str, base: Path) -> Path:
    if not isinstance(text, str) or not text or len(text) > 4096:
        raise Failure(INPUT_INVALID, "Expected a relative path string")
    p = Path(text)
    if p.is_absolute() or ".." in p.parts or not p.parts or text != text.strip() or "\\" in text:
        raise Failure(INPUT_INVALID, f"Use forward-slash relative paths inside the recipe directory: {text}")
    full = (base / p)
    if not full.resolve().is_relative_to(base.resolve()):
        raise Failure(INPUT_INVALID, f"Recipe path escapes the recipe directory: {text}")
    return full


def _zone_target(text: str) -> Path:
    if not isinstance(text, str) or "\\" in text:
        raise Failure(INPUT_INVALID, "Zone targets use forward slashes")
    p = Path(text)
    if p.is_absolute() or ".." in p.parts or not p.parts or any(not ZONE_PART.match(part) for part in p.parts):
        raise Failure(INPUT_INVALID, f"Zone target parts use letters, digits, dot, underscore or dash: {text}")
    return p


def _fields(row, allowed: set, required: set, what: str) -> None:
    if not isinstance(row, dict) or set(row) - allowed or required - set(row):
        raise Failure(INPUT_INVALID, f"{what}: expected fields {sorted(required)} (optional {sorted(allowed - required)})")


def load_recipe(path: Path, job: Job) -> tuple[dict, list, list, list]:
    src = job.input(path, limit=2 * 1024 * 1024)
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise Failure(INPUT_INVALID, f"Recipe is not valid JSON: {src}") from exc
    _fields(data, {"schema", "game", "name", "scripts", "assets", "loads", "mode"}, {"schema", "game", "name"}, "recipe")
    if data["schema"] != 1 or data["game"] != "t6":
        raise Failure(INPUT_INVALID, "Expected a schema 1 recipe for game t6")
    if not isinstance(data["name"], str) or not NAME.match(data["name"]):
        raise Failure(INPUT_INVALID, "Recipe name uses lowercase letters, digits and underscore")
    if data.get("mode", "zm") not in ("zm",):
        raise Failure(INPUT_INVALID, "Only mode 'zm' is supported by this release")
    scripts_rows, asset_rows, load_rows = data.get("scripts", []), data.get("assets", []), data.get("loads", [])
    if not all(isinstance(x, list) for x in (scripts_rows, asset_rows, load_rows)):
        raise Failure(INPUT_INVALID, "scripts, assets and loads must be lists")
    if len(scripts_rows) > MAX_SCRIPTS or len(asset_rows) > MAX_ASSETS or len(load_rows) > MAX_LOADS:
        raise Failure(INPUT_LIMIT, f"At most {MAX_SCRIPTS} scripts, {MAX_ASSETS} assets and {MAX_LOADS} loads")
    base = src.parent
    targets: set[str] = set()
    compiled, loose, loads = [], [], []
    for row in scripts_rows:
        _fields(row, {"source", "target", "instance"}, {"source", "target"}, "script")
        target = _zone_target(row["target"])
        instance = row.get("instance", "client" if target.suffix == ".csc" else "server")
        want = ".csc" if instance == "client" else ".gsc"
        if instance not in scripts.INSTANCES or target.suffix != want:
            raise Failure(INPUT_INVALID, f"Script target {target.as_posix()} must end in {want} for instance {instance}")
        source = _rel(row["source"], base)
        if source.suffix != want:
            raise Failure(INPUT_INVALID, f"Script source {row['source']} must end in {want}")
        key = target.as_posix().casefold()
        if key in targets:
            raise Failure(INPUT_INVALID, f"Duplicate target {target.as_posix()}")
        targets.add(key)
        compiled.append((job.input(source), target, instance))
    for row in asset_rows:
        _fields(row, {"source", "target", "type", "name"}, {"source", "target", "type"}, "asset")
        target = _zone_target(row["target"])
        asset_type = row["type"]
        if not isinstance(asset_type, str) or not NAME.match(asset_type):
            raise Failure(INPUT_INVALID, f"Asset type must be an OAT asset type identifier: {asset_type!r}")
        name = row.get("name", target.as_posix())
        if asset_type == "rawfile" and name != target.as_posix():
            raise Failure(INPUT_INVALID, "A rawfile's name must equal its target path")
        key = target.as_posix().casefold()
        if key in targets:
            raise Failure(INPUT_INVALID, f"Duplicate target {target.as_posix()}")
        targets.add(key)
        loose.append((job.input(_rel(row["source"], base)), target, asset_type, _zone_target(name).as_posix()))
    for text in load_rows:
        loads.append(job.input(_rel(text, base)))
    for source, _, _ in compiled:
        job.input_tree(source.parent)
    return data, compiled, loose, loads


def _plan(data, compiled, loose, loads, job: Job) -> dict:
    checks = []
    for name in (["gsc"] if compiled else []) + ["linker", "unlinker"]:
        try:
            checks.append({"id": name, "argv": executable(name), "available": True})
        except Failure as exc:
            checks.append({"id": name, "available": False, "message": exc.message})
    plan = {
        "schema_version": 1, "name": data["name"], "game": data["game"], "mode": data.get("mode", "zm"),
        "scripts": [{"source": str(p), "target": t.as_posix(), "instance": i} for p, t, i in compiled],
        "assets": [{"source": str(p), "target": t.as_posix(), "type": k, "name": n} for p, t, k, n in loose],
        "loads": [str(p) for p in loads],
        "backends": checks, "backends_available": all(c["available"] for c in checks),
        "input_files": len(job.inputs),
        "verification": "recipe and declared inputs validated and hashed; backend presence checked; nothing compiled",
    }
    (job.root / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return plan


def _build(data, compiled, loose, loads, plan, args, job: Job) -> dict:
    missing = [c["id"] for c in plan["backends"] if not c["available"]]
    if missing:
        raise Failure("backend_unavailable", f"Required backends are not installed: {missing}", "Run: pat dev setup")
    base = job.root / "project"
    raw, zone_dir = base / "raw", base / "zone_source"
    raw.mkdir(parents=True)
    zone_dir.mkdir()
    lines = ["> game,T6", f"> name,{data['name']}"]
    rawfiles = []
    for index, (source, target, instance) in enumerate(compiled):
        child = Job(job.root / f"script-{index:03d}", "gsc compile", ["pat", "gsc", "compile", str(source)],
                    timeout=max(1, int(job.deadline - __import__("time").monotonic())))
        try:
            result = scripts.execute(SimpleNamespace(action="compile", input=str(source), instance=instance,
                                                     includes=str(source.parent), timeout=args.timeout), child)
            child.finish(result)
        except Failure as exc:
            child.fail(exc)
            raise
        produced = child.root / result["files"][0]
        dest = raw / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(produced, dest)
        lines.append(f"rawfile,{target.as_posix()}")
        rawfiles.append(target)
    for source, target, asset_type, name in loose:
        dest = raw / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        lines.append(f"{asset_type},{name}")
        if asset_type == "rawfile":
            rawfiles.append(target)
    (zone_dir / "mod.zone").write_text("\n".join(lines) + "\n", encoding="utf-8")
    link = fastfiles.execute(SimpleNamespace(action="link", project=str(base), zone="mod", load=[str(p) for p in loads],
                                             assets=[], timeout=args.timeout), job)
    if len(link["packages"]) != 1:
        raise Failure(BACKEND_FAILED, "A recipe must produce exactly one fastfile")
    package = job.root / link["packages"][0]["path"]
    job.run([*executable("unlinker"), "--no-color", "--include-assets", "rawfile", "--output-folder",
             str(job.root / "readback"), str(package)], timeout=args.timeout)
    for rel in rawfiles:
        restored = job.root / "readback" / rel
        if not restored.is_file() or sha256_file(raw / rel) != sha256_file(restored):
            raise Failure(BACKEND_FAILED, f"Rawfile did not round-trip through the fastfile: {rel.as_posix()}")
    return {**link, "plan": "plan.json", "rawfiles_verified": len(rawfiles), "mod_ff": link["packages"][0]["path"],
            "install_hint": f"Copy {link['packages'][0]['path']} to <storage>/t6/mods/{data['name']}/mod.ff; loading it in game is a separate, authorized step"}


def _verify(args, job: Job) -> dict:
    receipt_path = job.input(args.receipt, limit=16 * 1024 * 1024)
    if receipt_path.name != "receipt.json":
        raise Failure(INPUT_INVALID, "Point verify at a build's receipt.json")
    report = verify_outputs(receipt_path)
    result = {"build_receipt": str(receipt_path), "outputs": report}
    if args.inputs:
        data = json.loads(receipt_path.read_text(encoding="utf-8"))
        changed, missing = [], []
        for path, digest in data.get("inputs", {}).items():
            p = Path(path)
            if not p.is_file():
                missing.append(path)
            elif sha256_file(p) != digest:
                changed.append(path)
        result["inputs"] = {"verified": not changed and not missing, "changed": changed, "missing": missing,
                            "count": len(data.get("inputs", {}))}
    ok = report["verified"] and result.get("inputs", {"verified": True})["verified"]
    if not ok:
        raise Failure("artifact_changed", "Recorded outputs or inputs no longer match the receipt", **result)
    return {**result, "verification": "recorded hashes match; says nothing about gameplay"}


def execute(args, job: Job) -> dict:
    if args.action == "init":
        if not NAME.match(args.name):
            raise Failure(INPUT_INVALID, "Name uses lowercase letters, digits and underscore")
        (job.root / "scripts").mkdir()
        (job.root / "scripts" / f"{args.name}.gsc").write_text(INIT_SCRIPT.replace("{name}", args.name), encoding="utf-8")
        (job.root / "README.txt").write_text(f"{args.name}: created by pat project init.\n", encoding="utf-8")
        recipe = {"schema": 1, "game": "t6", "mode": "zm", "name": args.name,
                  "scripts": [{"source": f"scripts/{args.name}.gsc", "target": f"scripts/zm/{args.name}.gsc", "instance": "server"}],
                  "assets": [{"source": "README.txt", "target": "README.txt", "type": "rawfile"}], "loads": []}
        (job.root / "project.json").write_text(json.dumps(recipe, indent=2) + "\n", encoding="utf-8")
        return {"recipe": "project.json", "next": ["pat project plan <dir>/project.json --output <new dir>"]}
    if args.action == "verify":
        return _verify(args, job)
    data, compiled, loose, loads = load_recipe(Path(args.recipe), job)
    plan = _plan(data, compiled, loose, loads, job)
    if args.action == "plan":
        return {"plan": "plan.json", **{k: plan[k] for k in ("name", "backends", "backends_available", "input_files", "verification")},
                "scripts": len(compiled), "assets": len(loose), "loads": len(loads)}
    return _build(data, compiled, loose, loads, plan, args, job)
