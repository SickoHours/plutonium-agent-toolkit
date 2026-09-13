"""Inert, source-labelled workspace records for a catalog client. Never evaluates recipes."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from ..core.errors import Failure, INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING
from .compositions import MAX_DECLARATION_BYTES, validate_declaration_metadata

MAX_BYTES = 64 * 1024 * 1024
MAX_MODULES = 512
MAX_ICON_BYTES = 64 * 1024 * 1024
MAX_ICON_FILE_BYTES = 16 * 1024 * 1024
MAX_FOUNDATION_MAPS = 64
MAX_FOUNDATION_ROWS = 256
MAX_PROVIDES_BYTES = 64 * 1024
MAX_RETAINED_BYTES = 512 * 1024
FLAGS = ("offline_verified", "installed", "runtime_verified", "player_accepted")
ICON_ROLES = {"bound HUD icon", "shared HUD icon", "local reference icon"}


def read_bytes(path: Path, *, optional=False, limit=MAX_BYTES):
    if path.is_symlink():
        raise Failure(INPUT_MISSING, f"Record is a link: {path.name}")
    if optional and not path.exists():
        return None
    if not path.is_file():
        raise Failure(INPUT_MISSING, f"Record is missing: {path.name}")
    if path.stat().st_size > limit:
        raise Failure(INPUT_LIMIT, f"Record exceeds the size bound: {path.name}")
    try:
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError as exc:
        raise Failure(INPUT_INVALID, f"Record is not readable: {path.name}") from exc
    if len(data) > limit:
        raise Failure(INPUT_LIMIT, f"Record exceeds the size bound: {path.name}")
    return data


def parse_object(data: bytes, path: Path):
    try:
        value = json.loads(data.decode("utf-8"))
    except (ValueError, RecursionError) as exc:
        raise Failure(INPUT_INVALID, f"Record is not readable JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise Failure(INPUT_INVALID, f"Record must be an object: {path.name}")
    return value


def read_object(path: Path, *, optional=False):
    data = read_bytes(path, optional=optional)
    return {} if data is None else parse_object(data, path)


class IconBudget:
    def __init__(self):
        self.remaining = MAX_ICON_BYTES
        self.digests = {}

    def digest(self, file: Path):
        canonical = file.resolve()
        if canonical in self.digests:
            return self.digests[canonical]
        size = file.stat().st_size
        if size > self.remaining:
            raise Failure(INPUT_LIMIT, "Workspace icon bytes exceed the aggregate budget")
        with file.open("rb") as stream:
            data = stream.read(min(self.remaining, MAX_ICON_FILE_BYTES) + 1)
        if len(data) > min(self.remaining, MAX_ICON_FILE_BYTES):
            raise Failure(INPUT_LIMIT, "Workspace icon bytes exceed the size bound")
        self.remaining -= len(data)
        digest = hashlib.sha256(data).hexdigest()
        self.digests[canonical] = digest
        return digest


def directory_entries(directory: Path, limit: int):
    entries = []
    with os.scandir(directory) as stream:
        for entry in stream:
            if len(entries) >= limit:
                raise Failure(INPUT_LIMIT, f"Directory exceeds {limit} entries: {directory.name}")
            entries.append(directory / entry.name)
    return sorted(entries)


def safe_output(value):
    if isinstance(value, str):
        return value[:2048].encode("utf-8", errors="backslashreplace").decode("utf-8")[:2048]
    if isinstance(value, list):
        return [safe_output(item) for item in value]
    if isinstance(value, dict):
        return {safe_output(key): safe_output(item) for key, item in value.items()}
    return value


class OutputBudget:
    def __init__(self):
        self.remaining = MAX_RETAINED_BYTES

    def take(self, value):
        normalized = safe_output(value)
        encoded = json.dumps(normalized, ensure_ascii=False, allow_nan=False, indent=2)
        # Include indentation when the row is nested in the CLI envelope's result arrays.
        size = len(encoded.encode("utf-8")) + 8 * (encoded.count("\n") + 1)
        if size > self.remaining:
            raise Failure(INPUT_LIMIT, "Workspace catalog output exceeds the aggregate budget")
        self.remaining -= size
        return normalized


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


def icon_binding(art, art_root, budget):
    for row in rows(art, "artwork"):
        binding = row.get("binding", {})
        role = binding.get("role") if isinstance(binding, dict) else None
        url = row.get("url")
        if isinstance(role, str) and role in ICON_ROLES and isinstance(url, str) and re.fullmatch(r"local-media/[0-9a-f]{64}\.webp", url):
            file = art_root / url
            if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_ICON_FILE_BYTES:
                continue
            if not file.resolve().is_relative_to(art_root):
                continue
            digest = budget.digest(file)
            return {"id": "local-" + digest, "role": role, "source": "local art catalog"}
    return None


def latest_test(directory: Path):
    file = directory / "docs/TEST.md"
    if not file.is_file() or file.is_symlink() or file.stat().st_size > 512 * 1024:
        return None
    with file.open("rb") as stream:
        data = stream.read(512 * 1024 + 1)
    if len(data) > 512 * 1024:
        return None
    lines = data.decode("utf-8").splitlines()
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
    diagnostics = []
    def optional_records(relative):
        try:
            return read_object(root / relative, optional=True)
        except (Failure, OSError) as exc:
            diagnostics.append({"path": relative, "message": str(exc)[:2048]})
            return {}
    records = optional_records("registry/t6-modules.json")
    recipes = optional_records("registry/module-recipes.json")
    art = read_object(Path(art_catalog).expanduser().resolve()) if art_catalog else {}
    registry = {row["id"]: row for row in rows(records, "modules") if isinstance(row.get("id"), str)}
    bindings = rows(recipes, "recipes")
    art_rows = rows(art, "modules")
    children = directory_entries(module_root, MAX_MODULES)
    modules = []
    icon_budget = IconBudget()
    output_budget = OutputBudget()
    truncated = False
    for child in children:
        declaration = child / "module.json"
        if child.is_symlink() or not child.is_dir() or not declaration.exists():
            continue
        try:
            declaration_bytes = read_bytes(declaration, limit=MAX_DECLARATION_BYTES)
            data = parse_object(declaration_bytes, declaration)
            metadata = validate_declaration_metadata(data)
            module_id = metadata["id"]
            provides = data.get("provides", {})
            if len(json.dumps(provides, ensure_ascii=True).encode("ascii")) > MAX_PROVIDES_BYTES:
                raise Failure(INPUT_LIMIT, "Declared provides exceeds the projection budget")
            matching = [r for r in bindings if r.get("catalog_id") == child.name or r.get("id") == child.name
                        or r.get("recipe") in (f"modules/{child.name}/recipe.json", f"modules/{child.name}/project.json")]
            catalog_id = matching[0].get("catalog_id", child.name) if matching else child.name
            if not isinstance(catalog_id, str):
                raise Failure(INPUT_INVALID, "Recipe catalog_id must be a string")
            registered = registry.get(catalog_id, {})
            module_art = next((r for r in art_rows if r.get("declarationId") == module_id), {})
            builds = []
            catalog_pointer = text(catalog_id, 256)
            for binding in matching:
                binding_pointer = text(binding.get("id"), 256) or child.name
                for i, row in enumerate(rows(binding, "builds")):
                    if len(builds) >= 256:
                        raise Failure(INPUT_LIMIT, "Module has more than 256 build records")
                    builds.append(project_record(row, "registry/module-recipes.json", f"{binding_pointer}/builds/{i}"))
            for i, row in enumerate(rows(registered, "build_revisions")):
                if len(builds) >= 256:
                    raise Failure(INPUT_LIMIT, "Module has more than 256 build records")
                builds.append(project_record(row, "registry/t6-modules.json", f"{catalog_pointer}/build_revisions/{i}"))
            cover_symbol = module_art.get("coverSymbol", {})
            if not isinstance(cover_symbol, dict):
                raise Failure(INPUT_INVALID, "coverSymbol must be an object")
            symbol = cover_symbol.get("url")
            if not isinstance(symbol, str) or not re.fullmatch(r"library-symbols/[a-z0-9-]+\.svg", symbol):
                symbol = None
            modules.append(output_budget.take({"id": module_id, "directory": f"modules/{child.name}",
                            "declaration_sha256": hashlib.sha256(declaration_bytes).hexdigest(),
                            "weapon_class": text(registered.get("weapon_class")),
                            "registry_origin": text(registered.get("origin_primary")),
                            "icon_binding": icon_binding(module_art, Path(art_catalog).resolve().parent, icon_budget) if art_catalog else None,
                            "symbol": "symbol-" + Path(symbol).stem if symbol else None,
                            "provides": provides, "build_records": builds,
                            "latest_test": latest_test(child)}))
        except (Failure, OSError, ValueError) as exc:
            if isinstance(exc, Failure) and exc.code == INPUT_LIMIT:
                truncated = True
            diagnostics.append({"path": f"modules/{child.name}", "message": str(exc)[:2048]})
    foundations = []
    foundation_root = root / "foundations"
    if foundation_root.is_dir() and not foundation_root.is_symlink():
        try:
            foundation_files = directory_entries(foundation_root, 64)
        except (Failure, OSError) as exc:
            diagnostics.append({"path": "foundations", "message": str(exc)[:2048]})
            truncated = True
            foundation_files = []
        for file in foundation_files:
            if file.suffix != ".json":
                continue
            try:
                info = read_object(file)
                if "id" not in info or "profile_prefix" not in info:
                    continue
                if not isinstance(info["id"], str) or not isinstance(info["profile_prefix"], str) or not info["id"] or not info["profile_prefix"]:
                    raise Failure(INPUT_INVALID, "Foundation id and profile_prefix must be non-empty strings")
                descriptor = info
                descriptor_path = file
                if info.get("private_descriptor"):
                    descriptor_path = (file.parent / info["private_descriptor"]).resolve()
                    descriptor = read_object(descriptor_path)
                links = descriptor.get("link_loads", {})
                maps = info.get("maps", {})
                if not isinstance(links, dict):
                    raise Failure(INPUT_INVALID, "link_loads must be an object")
                if not isinstance(maps, dict):
                    raise Failure(INPUT_INVALID, "maps must be an object")
                if len(maps) > MAX_FOUNDATION_MAPS or len(links) > MAX_FOUNDATION_MAPS or len(maps.keys() | links.keys()) > MAX_FOUNDATION_MAPS:
                    truncated = True
                    raise Failure(INPUT_LIMIT, "Foundation exceeds the map count bound")
                if len(foundations) + len(maps.keys() | links.keys()) > MAX_FOUNDATION_ROWS:
                    truncated = True
                    raise Failure(INPUT_LIMIT, "Workspace exceeds the foundation row bound")
                for map_id in dict.fromkeys([*maps, *links]):
                    loads = links.get(map_id)
                    staged = isinstance(loads, list) and len(loads) <= 16 and all(isinstance(p, str) and (descriptor_path.parent / p).is_file() for p in loads)
                    foundations.append(output_budget.take({"id": info["id"], "base": info["profile_prefix"], "map": map_id,
                                        "staged": staged, "source": f"foundations/{file.name}"}))
            except (Failure, OSError, ValueError, TypeError) as exc:
                if isinstance(exc, Failure) and exc.code == INPUT_LIMIT:
                    truncated = True
                diagnostics.append({"path": f"foundations/{file.name}", "message": str(exc)[:2048]})
    # Data rows are already normalized and budgeted. Keep diagnostics bounded separately;
    # avoid recursively copying the accumulated module payload a second time.
    bounded_diagnostics = [{"path": safe_output(row["path"])[:256], "message": safe_output(row["message"])[:512]} for row in diagnostics[:64]]
    return {"protocol": "pat.workspace-catalog/1", "modules": modules, "foundations": foundations,
            "diagnostics": bounded_diagnostics, "truncated": truncated or len(diagnostics) > 64}
