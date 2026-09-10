"""``weapon catalog`` and ``weapon plan``: saved BO3 donor libraries and T6 weapon recipes.

Both are offline. ``catalog`` verifies a sealed donor capture (index hashes,
page sizes, process and map identity) and writes ``library.json``. ``plan``
re-verifies the donor, checks a recipe's declared assets against the library
and reports what is missing. Neither executes a converter, touches a game, or
implies that a weapon will work; they make the inputs to a port checkable.

Donor receipt (JSON)::

    {"root": "<absolute private donor dir>", "index": "index.json", "index_sha256": "<64 hex>",
     "map": "zm_zod", "pid": 1234, "start_ticks": "…",
     "adapter_index": "native/index.json", "adapter_index_sha256": "<64 hex>"}   # optional

The index maps relative paths to SHA-256. The capture manifest (``--capture``)
is the ``bo3-page-capture-v1`` record: ``map_before``, ``map_after``, ``pid``,
``start_ticks``, ``captured_bytes``, ``pages`` and ``models``/``animations``/
``weapons`` arrays. Recipe schema 1 fields are documented in docs/WEAPONS.md.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ..core.errors import INPUT_CHANGED, INPUT_INVALID, INPUT_LIMIT, Failure
from ..core.jobs import Job
from ..core.receipts import sha256_file

MAX_INDEX_FILES = 4096
MAX_INDEX_BYTES = 2 * 1024**3
MAX_PAGES = 32768
MAX_RECORDS = 4096
KINDS = ("models", "animations", "weapons")
NAME = re.compile(r"[A-Za-z0-9_./*#-]{1,240}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
PAGE = re.compile(r"[0-9a-f]{16}\.bin\Z")
FAMILY = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
PREFIX = re.compile(r"[a-z][a-z0-9_]{2,63}_\Z")
RECIPE_FIELDS = {"schema", "family", "source_engine", "target_engine", "adapter", "hands_model", "variants",
                 "required_files", "keep_loaded_prefixes", "resident_cap_bytes", "menu_route"}
VARIANT_FIELDS = {"role", "source_weapon", "target_weapon", "view_model", "world_model", "clips", "native_template", "inventory_type"}
GATES = ["source_bind_relative_tracks", "packaged_model_offsets", "native_camera_and_ads_ownership",
         "independent_hand_tracks", "reload_sound_events", "complete_native_weapon_fields", "native_left_slot",
         "loaded_family_audio_cap", "final_memory_promotion", "package_readback", "normal_and_pap_playtest"]


def add_parser(sub, common):
    p = sub.add_parser("weapon", help="Saved BO3 donor catalogs and T6 weapon recipe planning (offline)")
    a = p.add_subparsers(dest="action", required=True)
    q = a.add_parser("catalog", help="Verify a sealed BO3 donor and index its saved asset records")
    q.add_argument("receipt", help="Donor receipt JSON")
    q.add_argument("--capture", required=True, help="Capture manifest path relative to the donor root")
    common(q)
    q = a.add_parser("plan", help="Check a T7-to-T6 recipe against a freshly re-verified catalog")
    q.add_argument("recipe", help="Recipe JSON")
    q.add_argument("--library", required=True, help="library.json written by weapon catalog")
    common(q)


def _require(condition, message, code=INPUT_INVALID):
    if not condition:
        raise Failure(code, message)


def _fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _name(value) -> str:
    _require(isinstance(value, str) and NAME.match(value), f"Invalid engine asset name {value!r}")
    _require(".." not in value.split("/"), "Asset names cannot traverse")
    return value


def _rel(root: Path, value) -> Path:
    _require(isinstance(value, str) and value and len(value) <= 4096 and "\\" not in value, "Expected a forward-slash relative path")
    p = Path(value)
    _require(not p.is_absolute() and ".." not in p.parts and bool(p.parts), f"Expected a safe relative path: {value}")
    full = root / p
    _require(full.resolve().is_relative_to(root.resolve()), "Donor reference leaves its root")
    return full


def _read_json(path: Path, limit: int = 2 * 1024 * 1024) -> dict:
    if path.stat().st_size > limit:
        raise Failure(INPUT_LIMIT, f"{path.name} exceeds {limit} bytes")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise Failure(INPUT_INVALID, f"Invalid JSON: {path}") from exc


def _pinned_files(job: Job, root: Path, index: dict) -> dict:
    _require(isinstance(index, dict) and 0 < len(index) <= MAX_INDEX_FILES, "Donor file count exceeds bound")
    _require(not job.root.is_relative_to(root), "Output must be outside the donor root")
    total = 0
    result = {}
    for rel, expected in sorted(index.items()):
        _require(isinstance(expected, str) and HEX64.match(expected), "Invalid donor digest")
        p = job.input(_rel(root, rel))
        size = p.stat().st_size
        total += size
        _require(total <= MAX_INDEX_BYTES, "Donor exceeds 2 GiB", INPUT_LIMIT)
        _require(job.inputs[str(p)] == expected, f"Donor file changed: {rel}", INPUT_CHANGED)
        result[rel] = {"sha256": expected, "bytes": size}
    return result


def catalog(job: Job, receipt_path: Path, capture_rel: str) -> dict:
    receipt_path = job.input(receipt_path, limit=2 * 1024 * 1024)
    receipt = _read_json(receipt_path)
    _require(isinstance(receipt, dict) and {"root", "index", "index_sha256", "map", "pid", "start_ticks"} <= set(receipt),
             "Donor receipt needs root, index, index_sha256, map, pid, start_ticks")
    root = Path(receipt["root"]).expanduser().resolve()
    _require(root.is_absolute() and root.is_dir(), "Donor root must be an existing absolute directory")
    index_path = job.input(_rel(root, receipt["index"]), limit=2 * 1024 * 1024)
    _require(job.inputs[str(index_path)] == receipt["index_sha256"], "Sealed index changed", INPUT_CHANGED)
    index = _read_json(index_path)
    _require(isinstance(index, dict) and isinstance(index.get("files"), dict), "Index needs a files map")
    files = _pinned_files(job, root, index["files"])
    _require(capture_rel in files, "Capture manifest must be in the sealed index")
    capture = _read_json(_rel(root, capture_rel))
    before, after = capture.get("map_before"), capture.get("map_after")
    _require(isinstance(before, list) and len(before) == 1 and before == after, "Capture map identity changed during capture")
    _require(before[0].get("name") == receipt["map"], "Donor map does not match the receipt")
    _require(capture.get("pid") == receipt["pid"] and str(capture.get("start_ticks")) == str(receipt["start_ticks"]),
             "Capture process identity differs from the receipt")
    pages = capture.get("pages")
    _require(isinstance(pages, dict) and 0 < len(pages) <= MAX_PAGES, "Snapshot page count exceeds bound")
    for page, expected in pages.items():
        _require(PAGE.match(page) and int(page[:-4], 16) % 4096 == 0, f"Invalid snapshot page address {page}")
        rel = (Path(capture_rel).parent / page).as_posix()
        _require(rel in files and files[rel] == {"sha256": expected, "bytes": 4096}, f"Missing, altered or short snapshot page: {page}")
    _require(capture.get("captured_bytes") == len(pages) * 4096, "Snapshot byte count differs from its pages")
    assets = {}
    for kind in KINDS:
        rows = capture.get(kind)
        _require(isinstance(rows, list) and len(rows) <= MAX_RECORDS, f"{kind} count exceeds bound")
        items = []
        for row in rows:
            item = {"name": _name(row.get("name"))}
            if kind == "models":
                tags = row.get("tags")
                _require(isinstance(tags, list) and 0 < len(tags) <= 255 and len(set(tags)) == len(tags), "Invalid model bone names")
                item.update(bones=len(tags), materials=sorted({_name(m) for lod in row.get("lods", []) for m in lod.get("materials", [])}))
            items.append(item)
        _require(len({i["name"] for i in items}) == len(items), f"Ambiguous duplicate {kind}")
        assets[kind] = sorted(items, key=lambda i: i["name"])
    adapter = {}
    if "adapter_index" in receipt:
        path = job.input(_rel(root, receipt["adapter_index"]))
        _require(job.inputs[str(path)] == receipt.get("adapter_index_sha256"), "Native adapter index changed", INPUT_CHANGED)
        adapter = _pinned_files(job, path.parent, _read_json(path).get("files", {}))
    return {"schema_version": 1, "source_engine": "t7", "format": "bo3-page-capture-v1",
            "donor_receipt": str(receipt_path), "donor_receipt_sha256": job.inputs[str(receipt_path)],
            "capture": capture_rel, "map": receipt["map"], "assets": assets, "files": files,
            "native_adapter_files": adapter,
            "identity": _fingerprint({"index": receipt["index_sha256"], "capture": files[capture_rel]["sha256"], "adapter": adapter}),
            "captured_bytes": capture["captured_bytes"], "live_access": False,
            "limits": ["Indexed saved records; pointer coverage and binary decoding belong to the owning converter.",
                       "A historical capture is not atomic and pins no BO3 executable hash.",
                       "No live BO3 capture and no generic weapon conversion are provided."]}


def read_recipe(path: Path) -> dict:
    recipe = _read_json(path)
    _require(isinstance(recipe, dict) and set(recipe) == RECIPE_FIELDS, f"Recipe must have exactly these fields: {sorted(RECIPE_FIELDS)}")
    _require(recipe["schema"] == 1 and recipe["source_engine"] == "t7" and recipe["target_engine"] == "t6", "Expected schema 1, source t7, target t6")
    _require(isinstance(recipe["family"], str) and FAMILY.match(recipe["family"]), "Invalid family")
    _name(recipe["adapter"])
    _name(recipe["hands_model"])
    _require(isinstance(recipe["menu_route"], str) and 0 < len(recipe["menu_route"]) <= 512, "menu_route required")
    _require(type(recipe["resident_cap_bytes"]) is int and 0 < recipe["resident_cap_bytes"] <= 16 * 1024**2, "resident_cap_bytes must be within 16 MiB")
    prefixes = recipe["keep_loaded_prefixes"]
    _require(isinstance(prefixes, list) and 0 < len(prefixes) <= 16 and len(set(prefixes)) == len(prefixes), "Invalid resident prefixes")
    for prefix in prefixes:
        _require(isinstance(prefix, str) and PREFIX.match(prefix), f"Resident prefix {prefix!r} must be a bounded family namespace ending in _")
    required = recipe["required_files"]
    _require(isinstance(required, list) and len(required) <= MAX_INDEX_FILES and len(set(required)) == len(required), "Invalid required_files")
    for f in required:
        _rel(Path("/donor"), f)
    variants = recipe["variants"]
    _require(isinstance(variants, list) and 2 <= len(variants) <= 3, "Declare normal and pap variants, plus optional left")
    roles = sorted(v.get("role") for v in variants if isinstance(v, dict))
    _require(roles in (["normal", "pap"], ["left", "normal", "pap"]), "Variant roles must be normal+pap, optionally left")
    for v in variants:
        _require(set(v) == VARIANT_FIELDS, f"Variant fields must be exactly {sorted(VARIANT_FIELDS)}")
        for k in ("source_weapon", "target_weapon", "view_model", "world_model", "native_template"):
            _name(v[k])
        _require(v["inventory_type"] == ("dwlefthand" if v["role"] == "left" else "primary"), "Left hand must be dwlefthand; others primary")
        clips = v["clips"]
        _require(isinstance(clips, dict) and {"idle", "fire", "reload"} <= clips.keys() and len(clips) <= 32, "Each variant needs idle/fire/reload clips")
        for slot, clip in clips.items():
            _name(slot)
            _name(clip)
    for key in ("source_weapon", "target_weapon"):
        _require(len({v[key] for v in variants}) == len(variants), f"Duplicate {key} across variants")
    return recipe


def plan(recipe: dict, library: dict) -> dict:
    available = {kind: {r["name"] for r in library["assets"][kind]} for kind in KINDS}
    needs = {kind: set() for kind in KINDS}
    needs["models"].add(recipe["hands_model"])
    for v in recipe["variants"]:
        needs["models"].update([v["view_model"], v["world_model"]])
        needs["weapons"].add(v["source_weapon"])
        needs["animations"].update(v["clips"].values())
    missing = {kind: sorted(needs[kind] - available[kind]) for kind in KINDS}
    missing["files"] = sorted(set(recipe["required_files"]) - set(library["files"]))
    native = {v["native_template"]: ("indexed" if v["native_template"] in library["native_adapter_files"] else "owning_builder_required")
              for v in recipe["variants"]}
    return {"schema_version": 1, "family": recipe["family"], "recipe_sha256": _fingerprint(recipe),
            "library_identity": library["identity"], "declared_inputs_available": not any(missing.values()),
            "missing": missing, "native_templates": native, "selected": {k: sorted(v) for k, v in needs.items()},
            "adapter": recipe["adapter"],
            "adapter_execution": "An owning project's reviewed converter runs the recipe; this command executes nothing.",
            "required_gates": GATES, "offline_converted": False, "package_verified": False,
            "gameplay_accepted": False, "live_access": False}


def execute(args, job: Job) -> dict:
    if args.action == "catalog":
        library = catalog(job, Path(args.receipt), args.capture)
        (job.root / "library.json").write_text(json.dumps(library, indent=2) + "\n", encoding="utf-8")
        return {"library": "library.json", "identity": library["identity"],
                "counts": {k: len(v) for k, v in library["assets"].items()}, "live_access": False}
    recipe = read_recipe(job.input(Path(args.recipe), limit=2 * 1024 * 1024))
    library_path = job.input(Path(args.library), limit=2 * 1024 * 1024)
    _require(not job.root.is_relative_to(library_path.parent), "Output must be outside the catalog job")
    old = _read_json(library_path)
    _require(isinstance(old, dict) and {"donor_receipt", "capture"} <= set(old), "library.json is not a weapon catalog")
    fresh = catalog(job, Path(old["donor_receipt"]), old["capture"])
    _require(old == fresh, "Library differs from the freshly verified donor; rebuild the catalog", INPUT_CHANGED)
    result = plan(recipe, fresh)
    (job.root / "plan.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
