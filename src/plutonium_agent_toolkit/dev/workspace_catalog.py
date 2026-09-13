"""Inert, source-labelled workspace records for a catalog client. Never evaluates recipes."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ..core.errors import Failure, INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING
from .compositions import validate_declaration_metadata

MAX_BYTES = 64 * 1024 * 1024
MAX_MODULES = 512
FLAGS = ("offline_verified", "installed", "runtime_verified", "player_accepted")
ICON_ROLES = {"bound HUD icon", "shared HUD icon", "local reference icon"}


def read_object(path: Path, *, optional=False):
    if optional and not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise Failure(INPUT_MISSING, f"Record is missing or is a link: {path.name}")
    if path.stat().st_size > MAX_BYTES:
        raise Failure(INPUT_LIMIT, f"Record exceeds the size bound: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Failure(INPUT_INVALID, f"Record is not readable JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise Failure(INPUT_INVALID, f"Record must be an object: {path.name}")
    return value


def text(value, limit=2048):
    return value[:limit] if isinstance(value, str) else None


def rows(value, key):
    result = value.get(key, [])
    if not isinstance(result, list) or len(result) > 4096:
        raise Failure(INPUT_LIMIT, f"{key} must be a list with at most 4096 records")
    return [row for row in result if isinstance(row, dict)]


def project_record(row, source, pointer):
    return {"id": text(row.get("id")) or "unnamed", "foundation": text(row.get("foundation", row.get("base"))),
            "map": text(row.get("map")), "sha256": text(row.get("sha256")),
            **{flag: row.get(flag) if type(row.get(flag)) is bool else None for flag in FLAGS},
            "receipt": text(row.get("receipt", row.get("evidence"))), "source": source, "pointer": pointer,
            "recorded_at": text(row.get("recorded_at", row.get("at"))), "scope": text(row.get("scope")),
            "verdict": text(row.get("verdict"))}


def icon_binding(art, art_root):
    for row in rows(art, "artwork"):
        binding = row.get("binding", {})
        role = binding.get("role") if isinstance(binding, dict) else None
        url = row.get("url")
        if role in ICON_ROLES and isinstance(url, str) and re.fullmatch(r"local-media/[0-9a-f]{64}\.webp", url):
            file = art_root / url
            if file.is_symlink() or not file.is_file() or file.stat().st_size > 16 * 1024 * 1024:
                continue
            if not file.resolve().is_relative_to(art_root):
                continue
            digest = hashlib.sha256(file.read_bytes()).hexdigest()
            return {"id": "local-" + digest, "role": role, "source": "local art catalog"}
    return None


def latest_test(directory: Path):
    file = directory / "docs/TEST.md"
    if not file.is_file() or file.is_symlink() or file.stat().st_size > 512 * 1024:
        return None
    lines = file.read_text(encoding="utf-8").splitlines()
    candidates = [(i, line) for i, line in enumerate(lines, 1) if re.search(r"\b(build|receipt)\b", line, re.I) and line.strip()]
    if not candidates:
        return None
    number, line = candidates[-1]
    return {"line": number, "text": line[:2048]}


def catalog(directory: str, art_catalog: str | None = None):
    root = Path(directory).expanduser().resolve()
    read_object(root / "workspace.json")
    module_root = root / "modules"
    if not module_root.is_dir() or module_root.is_symlink():
        raise Failure(INPUT_MISSING, "Workspace modules directory is missing")
    records = read_object(root / "registry/t6-modules.json", optional=True)
    recipes = read_object(root / "registry/module-recipes.json", optional=True)
    art = read_object(Path(art_catalog).expanduser().resolve()) if art_catalog else {}
    registry = {row.get("id"): row for row in rows(records, "modules")}
    bindings = rows(recipes, "recipes")
    art_rows = rows(art, "modules")
    children = sorted(module_root.iterdir())
    if len(children) > MAX_MODULES:
        raise Failure(INPUT_LIMIT, "Workspace has more than 512 module directories")
    modules, diagnostics = [], []
    for child in children:
        declaration = child / "module.json"
        if child.is_symlink() or not child.is_dir() or not declaration.exists():
            continue
        try:
            data = read_object(declaration)
            metadata = validate_declaration_metadata(data)
            module_id = metadata["id"]
            matching = [r for r in bindings if r.get("catalog_id") == child.name or r.get("id") == child.name
                        or r.get("recipe") in (f"modules/{child.name}/recipe.json", f"modules/{child.name}/project.json")]
            catalog_id = matching[0].get("catalog_id", child.name) if matching else child.name
            registered = registry.get(catalog_id, {})
            module_art = next((r for r in art_rows if r.get("declarationId") == module_id), {})
            builds = []
            for binding in matching:
                for i, row in enumerate(rows(binding, "builds")):
                    builds.append(project_record(row, "registry/module-recipes.json", f"{binding.get('id')}/builds/{i}"))
            for i, row in enumerate(rows(registered, "build_revisions")):
                builds.append(project_record(row, "registry/t6-modules.json", f"{catalog_id}/build_revisions/{i}"))
            if len(builds) > 256:
                raise Failure(INPUT_LIMIT, "Module has more than 256 build records")
            symbol = module_art.get("coverSymbol", {}).get("url")
            if not isinstance(symbol, str) or not re.fullmatch(r"library-symbols/[a-z0-9-]+\.svg", symbol):
                symbol = None
            modules.append({"id": module_id, "directory": f"modules/{child.name}",
                            "declaration_sha256": hashlib.sha256(declaration.read_bytes()).hexdigest(),
                            "weapon_class": text(registered.get("weapon_class")),
                            "registry_origin": text(registered.get("origin_primary")),
                            "icon_binding": icon_binding(module_art, Path(art_catalog).resolve().parent) if art_catalog else None,
                            "symbol": "symbol-" + Path(symbol).stem if symbol else None,
                            "provides": data.get("provides", {}), "build_records": builds,
                            "latest_test": latest_test(child)})
        except (Failure, OSError, ValueError) as exc:
            diagnostics.append({"path": f"modules/{child.name}", "message": str(exc)[:2048]})
    foundations = []
    foundation_root = root / "foundations"
    if foundation_root.is_dir() and not foundation_root.is_symlink():
        for file in sorted(foundation_root.glob("*.json"))[:64]:
            try:
                info = read_object(file)
                if not info.get("id") or not info.get("profile_prefix"):
                    continue
                descriptor = info
                descriptor_path = file
                if info.get("private_descriptor"):
                    descriptor_path = (file.parent / info["private_descriptor"]).resolve()
                    descriptor = read_object(descriptor_path)
                links = descriptor.get("link_loads", {})
                maps = info.get("maps", {})
                for map_id in dict.fromkeys([*maps, *links]):
                    loads = links.get(map_id)
                    staged = isinstance(loads, list) and bool(loads) and all(isinstance(p, str) and (descriptor_path.parent / p).is_file() for p in loads)
                    foundations.append({"id": info["id"], "base": info["profile_prefix"], "map": map_id,
                                        "staged": staged, "source": f"foundations/{file.name}"})
            except (Failure, OSError, ValueError, TypeError) as exc:
                diagnostics.append({"path": f"foundations/{file.name}", "message": str(exc)[:2048]})
    return {"protocol": "pat.workspace-catalog/1", "modules": modules, "foundations": foundations,
            "diagnostics": diagnostics[:64], "truncated": len(diagnostics) > 64}
