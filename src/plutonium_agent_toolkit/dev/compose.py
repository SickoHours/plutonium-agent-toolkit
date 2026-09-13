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
    except (ValueError, OSError) as exc:
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
    for field in ("loads", "base_owned"):
        data[field] = [relative((source.parent / value).resolve(), destination) for value in data.get(field, [])]
    members = []
    for value in data["modules"]:
        if isinstance(value, str):
            members.append(relative((source.parent / value).resolve(), destination))
        else:
            members.append(dict(value, path=relative((source.parent / value["path"]).resolve(), destination)))
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
    for root_text in args.member_root:
        root = Path(root_text).expanduser().resolve()
        if not root.is_dir():
            raise Failure(INPUT_MISSING, f"Member root is missing: {root}")
        children = sorted(root.iterdir())
        if len(children) > 4096:
            raise Failure(INPUT_LIMIT, "Member root exceeds 4096 entries")
        for child in children:
            declaration = child / "module.json"
            if child.is_symlink() or not child.is_dir() or not declaration.is_file():
                continue
            _, data = read_json(declaration, job, compositions.MAX_DECLARATION_BYTES)
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
    foundation_path, foundation = read_json(Path(args.foundation), job)
    descriptor_path, descriptor = foundation_path, foundation
    if foundation.get("private_descriptor"):
        descriptor_path, descriptor = read_json(foundation_path.parent / foundation["private_descriptor"], job)
    loads = descriptor.get("link_loads", {}).get(args.map)
    if not isinstance(loads, list):
        raise Failure(INPUT_MISSING, f"Foundation has no staged link loads for {args.map}")
    header = foundation.get("mod_zone_header", descriptor.get("mod_zone_header", []))
    # A descriptor may carry the original map's ipak line; select the requested map.
    header = [f">level.ipak_read,{args.map}" if line.startswith(">level.ipak_read,zm_") else line for line in header]
    recipe = {"schema": 1, "name": args.name, "base": args.base, "map": args.map,
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
