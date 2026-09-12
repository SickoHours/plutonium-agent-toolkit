"""``project init|plan|build|verify``: a declarative recipe for a T6 Zombies or IW5 multiplayer mod.

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
from . import fastfiles, scripts, titles
from .backends import executable

NAME = re.compile(r"^[a-z0-9_]{1,64}\Z")
ZONE_PART = re.compile(r"^[A-Za-z0-9_.-]{1,255}\Z")
MAX_SCRIPTS, MAX_ASSETS, MAX_LOADS = 128, 4096, 32

INIT_SCRIPT = '''// Created by pat project init. Prints to each player once they spawn.
// Uses only engine builtins so gsc-tool accepts it offline without the game's include files.

main()
{
    level thread on_player_connect();
}

on_player_connect()
{
    for ( ;; )
    {
        level waittill( "connected", player );
        player thread on_player_spawned();
    }
}

on_player_spawned()
{
    self waittill( "spawned_player" );
    self iprintln( "^2{name} loaded" );
}
'''


def add_parser(sub, common):
    p = sub.add_parser("project", help="Declarative mod recipes (t6 or iw5): init, plan, build, verify")
    actions = p.add_subparsers(dest="action", required=True)
    q = actions.add_parser("init", help="Create a minimal recipe and source in a new directory")
    q.add_argument("--name", default="my_mod", help="Mod name: lowercase letters, digits, underscore")
    q.add_argument("--game", choices=titles.names(), default=titles.DEFAULT_TITLE,
                   help="Title the recipe targets (default t6)")
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
    if data["schema"] != 1 or data["game"] not in titles.names():
        raise Failure(INPUT_INVALID, f"Expected a schema 1 recipe for one of games {', '.join(titles.names())}")
    if not isinstance(data["name"], str) or not NAME.match(data["name"]):
        raise Failure(INPUT_INVALID, "Recipe name uses lowercase letters, digits and underscore")
    allowed_modes = titles.modes(data["game"])
    if data.get("mode", allowed_modes[0]) not in allowed_modes:
        raise Failure(INPUT_INVALID, f"Game {data['game']} supports modes {', '.join(allowed_modes)}")
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
        if instance not in titles.instances(data["game"]):
            raise Failure(INPUT_INVALID, f"Game {data['game']} has no {instance} script instance: {target.as_posix()}",
                          "IW5 has one server VM; there is no .csc client script on that title.")
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
        "schema_version": 1, "name": data["name"], "game": data["game"],
        "mode": data.get("mode", titles.modes(data["game"])[0]),
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
    game = data["game"]
    zone = titles.zone(game)
    zone_name = zone["name"]
    base = job.root / "project"
    raw, zone_dir = base / "raw", base / "zone_source"
    raw.mkdir(parents=True)
    zone_dir.mkdir()
    # Plutonium loads mods/<folder>/mod.ff, and a CoD fastfile is bound to its file name (the zone
    # name keys its compressed streams), so the zone is always linked as its canonical name ("mod"
    # for both T6 and IW5). The recipe name is the install folder only. Native Tier 3 finding: a
    # hello_zm.ff renamed to mod.ff could not be inflated by OpenAssetTools and hung the client.
    lines = [f"> game,{zone['game_token']}", f"> name,{zone_name}"]
    rawfiles = []
    # T6 executes gsc-tool's bytecode, so the compiled file is the rawfile. Plutonium IW5 compiles
    # GSC source itself and never runs gsc-tool bytecode: the source is the rawfile and gsc-tool
    # runs as a dry-run syntax gate (`gsc check`). docs/knowledge/iw5.md.
    action = "compile" if titles.script_form(game) == "compiled" else "check"
    for index, (source, target, instance) in enumerate(compiled):
        child = Job(job.root / f"script-{index:03d}", f"gsc {action}", ["pat", "gsc", action, str(source)],
                    timeout=max(1, int(job.deadline - __import__("time").monotonic())))
        try:
            result = scripts.execute(SimpleNamespace(action=action, input=str(source), instance=instance,
                                                     game=game, includes=str(source.parent), timeout=args.timeout), child)
            child.finish(result)
        except Failure as exc:
            child.fail(exc)
            raise
        produced = child.root / result["files"][0] if result["files"] else source
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
    (zone_dir / f"{zone_name}.zone").write_text("\n".join(lines) + "\n", encoding="utf-8")
    link = fastfiles.execute(SimpleNamespace(action="link", project=str(base), zone=zone_name, load=[str(p) for p in loads],
                                             assets=[], timeout=args.timeout), job)
    if len(link["packages"]) != 1:
        raise Failure(BACKEND_FAILED, "A recipe must produce exactly one fastfile")
    package = job.root / link["packages"][0]["path"]
    readback_log = job.run([*executable("unlinker"), "--no-color", "--include-assets", "rawfile", "--output-folder",
                            str(job.root / "readback"), str(package)], timeout=args.timeout)
    fastfiles.check_readback_log(readback_log)
    for rel in rawfiles:
        restored = job.root / "readback" / rel
        if not restored.is_file() or sha256_file(raw / rel) != sha256_file(restored):
            raise Failure(BACKEND_FAILED, f"Rawfile did not round-trip through the fastfile: {rel.as_posix()}")
    return {**link, "plan": "plan.json", "game": game, "script_form": titles.script_form(game),
            "rawfiles_verified": len(rawfiles), "mod_ff": link["packages"][0]["path"],
            "install_hint": f"pat game install-mod <output>/{link['packages'][0]['path']} {data['name']}  (keeps the name mod.ff; a renamed fastfile cannot be read; the folder goes under the storage of game {game}). Loading it in game is a separate, authorized step"}


def _verify(args, job: Job) -> dict:
    receipt_path = job.input(args.receipt, limit=16 * 1024 * 1024)
    if receipt_path.name != "receipt.json":
        raise Failure(INPUT_INVALID, "Point verify at a build's receipt.json")
    report = verify_outputs(receipt_path)
    result = {"build_receipt": str(receipt_path), "outputs": report}
    if args.inputs:
        try:
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise Failure(INPUT_INVALID, f"Receipt is not valid JSON: {receipt_path}") from exc
        if not isinstance(data.get("inputs"), dict):
            raise Failure(INPUT_INVALID, "Receipt lacks an inputs map")
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
        mode = titles.modes(args.game)[0]
        (job.root / "scripts").mkdir()
        (job.root / "scripts" / f"{args.name}.gsc").write_text(INIT_SCRIPT.replace("{name}", args.name), encoding="utf-8")
        (job.root / "README.txt").write_text(f"{args.name}: created by pat project init.\n", encoding="utf-8")
        recipe = {"schema": 1, "game": args.game, "mode": mode, "name": args.name,
                  "scripts": [{"source": f"scripts/{args.name}.gsc", "target": titles.script_target(args.game, args.name), "instance": "server"}],
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
