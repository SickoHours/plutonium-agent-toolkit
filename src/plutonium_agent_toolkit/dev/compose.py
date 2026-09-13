"""Author a recipe from declared IDs; only this module resolves source paths."""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

from ..core.errors import Failure, INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING
from ..core.jobs import Job
from ..core.receipts import sha256_file
from . import compositions


def read_json(path: Path, job: Job, limit=4 * 1024 * 1024):
    source = job.input(path, limit=limit)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (ValueError, OSError, RecursionError) as exc:
        raise Failure(INPUT_INVALID, "Invalid composition input JSON") from exc
    if not isinstance(value, dict):
        raise Failure(INPUT_INVALID, "Composition input must be a JSON object")
    return source, value


def relative(path: Path, directory: Path) -> str:
    try:
        return Path(os.path.relpath(path, directory)).as_posix()
    except ValueError as exc:
        raise Failure(INPUT_INVALID, "Recipe and inputs must be on the same filesystem drive") from exc


def publish(args, job: Job):
    if not args.composition or not args.from_build:
        raise Failure(INPUT_INVALID, "Publishing requires --composition and --from-build receipt.json")
    source, data = read_json(Path(args.composition), job)
    receipt_path, receipt = read_json(Path(args.from_build), job, 64 * 1024 * 1024)
    if receipt.get("command") != "module build" or receipt.get("status") != "succeeded" or receipt.get("ok") is not True:
        raise Failure(INPUT_INVALID, "Only a succeeded module build can publish its recipe")
    if receipt.get("inputs", {}).get(str(source)) != sha256_file(source):
        raise Failure(INPUT_INVALID, "Build receipt does not name this exact recipe")
    result = receipt.get("result", {})
    mod = result.get("mod_ff")
    if not isinstance(mod, str) or Path(mod).is_absolute() or ".." in Path(mod).parts:
        raise Failure(INPUT_INVALID, "Build receipt has no valid package path")
    package = job.input(receipt_path.parent / mod)
    if receipt.get("outputs", {}).get(mod) != sha256_file(package):
        raise Failure(INPUT_INVALID, "Built package changed since its receipt")
    compositions.validate_composition_metadata(data)
    destination = Path(args.publish_to).expanduser().absolute()
    if destination.name != data["name"]:
        raise Failure(INPUT_INVALID, "Publish directory must match the composition name")
    def existing(value, *, member=False):
        path = source.parent / value
        if path.is_symlink() or not (path.is_dir() if member else path.is_file()):
            raise Failure(INPUT_MISSING, "Published input is missing or is a link")
        if member and not any((path / name).is_file() for name in ("module.json", "composition.json")):
            raise Failure(INPUT_MISSING, "Published member declaration is missing")
        return relative(path.resolve(), destination)
    for field in ("loads", "base_owned"):
        data[field] = [existing(value) for value in data.get(field, [])]
    members = []
    for value in data["modules"]:
        if isinstance(value, str):
            members.append(existing(value, member=True))
        else:
            members.append(dict(value, path=existing(value["path"], member=True)))
    data["modules"] = members
    compositions.validate_composition_metadata(data)
    # Exclusive publication; a saved recipe is never silently replaced.
    try:
        destination.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise Failure(INPUT_INVALID, "A recipe with this name already exists; choose another name") from exc
    output = destination / "composition.json"
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(data, indent=2) + "\n")
    return {"published": str(output), "name": data["name"], "composition_sha256": sha256_file(output),
            "build_receipt": str(receipt_path), "mod_ff_sha256": sha256_file(package)}


def execute(args, job: Job):
    if args.publish_to:
        return publish(args, job)
    if not args.name or not args.base or not args.map or not args.foundation or not args.module:
        raise Failure(INPUT_INVALID, "Compose requires --name, --base, --map, --foundation and at least one --module")
    if len(args.module) > compositions.MAX_MODULES or len(args.member_root) > 16:
        raise Failure(INPUT_LIMIT, "Too many module IDs or member roots")
    index = {}
    discovery_bytes = 0
    for root_text in args.member_root:
        root = Path(root_text).expanduser().resolve()
        if not root.is_dir():
            raise Failure(INPUT_MISSING, f"Member root is missing: {root}")
        children = sorted(root.iterdir())
        if len(children) > 4096:
            raise Failure(INPUT_LIMIT, "Member root exceeds 4096 entries")
        for child in children:
            job.check_deadline()
            declaration = child / "module.json"
            if child.is_symlink() or not child.is_dir() or not declaration.is_file():
                continue
            raw = compositions._read_inspection(declaration)
            discovery_bytes += len(raw)
            if discovery_bytes > 64 * 1024 * 1024:
                raise Failure(INPUT_LIMIT, "Module discovery exceeds 64 MiB")
            try:
                data = json.loads(raw)
            except (ValueError, RecursionError) as exc:
                raise Failure(INPUT_INVALID, "Invalid discovered module JSON") from exc
            metadata = compositions.validate_declaration_metadata(data)
            index.setdefault(metadata["id"], (child, metadata))  # Ordered roots prefer a built seed.
    selected = {}
    def include(mid):
        if mid in selected:
            return
        if mid not in index:
            raise Failure(INPUT_MISSING, f"No declaration for module {mid}")
        if len(selected) >= compositions.MAX_MODULES:
            raise Failure(INPUT_LIMIT, "Dependency closure exceeds 128 modules")
        selected[mid] = index[mid]
        for dep in index[mid][1]["dependencies"]:
            include(dep)
    for mid in args.module:
        if not isinstance(mid, str) or not compositions.ID.fullmatch(mid):
            raise Failure(INPUT_INVALID, "Module IDs must be declared identifiers")
        include(mid)
        if mid + "_registration" in index:
            include(mid + "_registration")
    # Only selected declarations are inputs of this composition; discovery has its own budget.
    for path, discovered in selected.values():
        _, current = read_json(path / "module.json", job, compositions.MAX_DECLARATION_BYTES)
        if compositions.validate_declaration_metadata(current) != discovered:
            raise Failure(INPUT_INVALID, "Selected declaration changed after discovery")
    foundation_path, foundation = read_json(Path(args.foundation), job)
    if foundation.get("profile_prefix") and foundation["profile_prefix"] != args.base:
        raise Failure(INPUT_INVALID, "Requested base does not match the foundation profile prefix")
    descriptor_path, descriptor = foundation_path, foundation
    if foundation.get("private_descriptor"):
        descriptor_path, descriptor = read_json(foundation_path.parent / foundation["private_descriptor"], job)
    link_loads = descriptor.get("link_loads", {})
    if not isinstance(link_loads, dict):
        raise Failure(INPUT_INVALID, "Foundation link_loads must be an object of map id to file paths")
    loads = link_loads.get(args.map)
    if loads is None:
        raise Failure(INPUT_MISSING, f"Foundation has no staged link loads for {args.map}")
    if not isinstance(loads, list) or len(loads) > 16 or any(not isinstance(value, str) or not value for value in loads):
        raise Failure(INPUT_INVALID, f"Foundation link loads for {args.map} must be a list of at most 16 paths")
    header = foundation.get("mod_zone_header", descriptor.get("mod_zone_header", []))
    if not isinstance(header, list) or len(header) > 64 or any(not isinstance(line, str) for line in header):
        raise Failure(INPUT_INVALID, "Foundation mod_zone_header must be a list of at most 64 strings")
    # A descriptor may carry the original map's ipak line; select the requested map.
    header = [f">level.ipak_read,{args.map}" if line.startswith(">level.ipak_read,zm_") else line for line in header]
    # The recipe names the title its members target; a mixed set is refused here, before any plan.
    games = sorted({metadata["game"] for _, metadata in selected.values()})
    game = getattr(args, "game", None) or (games[0] if len(games) == 1 else None)
    if game is None:
        raise Failure(INPUT_INVALID, f"Members target more than one title ({', '.join(games)}); pass --game or split the pack")
    if games != [game]:
        raise Failure(INPUT_INVALID, f"--game {game} but the members target {', '.join(games)}",
                      "Every module in a composition targets the same game; pick members for one title.")
    recipe = {"schema": 1, "name": args.name, "game": game, "base": args.base, "map": args.map,
              "modules": [relative(path, job.root) for path, _ in selected.values()],
              "loads": [relative((descriptor_path.parent / value).resolve(), job.root) for value in loads],
              "zone_header": header}
    assets = descriptor.get("assets", {})
    zones = foundation.get("maps", {}).get(args.map, {}).get("runtime_zones", [])
    base_owned = sorted({row for zone in zones for row in assets.get(zone, {}).get("embedded", [])})
    if base_owned:
        listing = job.root / "base-owned.txt"
        listing.write_text("\n".join(base_owned) + "\n", encoding="utf-8")
        recipe["base_owned"] = [listing.name]
    compositions.validate_composition_metadata(recipe)
    source = job.root / "composition.json"
    source.write_text(json.dumps(recipe, indent=2) + "\n", encoding="utf-8")
    planning = Job(job.root / "planning", "module plan", ["module", "plan", str(source)], timeout=max(args.timeout, 60)*4)
    try:
        planned = compositions.execute(SimpleNamespace(**(vars(args) | {"action": "plan", "composition": str(source), "allow_unqualified": True})), planning)
        planning.finish(planned)
    except Failure as exc:
        planning.fail(exc)
        raise
    return {**planned, "composition": str(source), "plan": "planning/plan.json", "plan_receipt": "planning/receipt.json"}
