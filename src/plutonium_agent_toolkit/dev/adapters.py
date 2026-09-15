"""Adapter recipes: the third module payload, a donor-converted module a workspace builder cuts.

A ``module.json`` names ``recipe``; the file is either a **project recipe** (``schema``, ``game``,
``name``: scripts and loose assets the toolkit compiles and links itself, ``projects.py``) or an
**adapter recipe** (``schema``, ``foundation``, ``map`` and ``module`` or ``adapter``): a donor
conversion whose prepared inputs and build steps belong to a workspace builder the toolkit runs
as a backend. The planner reads what the recipe declares it delivers (weapons, one soundbank,
localized strings, loose scripts, rooted rawfiles, native scripts, effects, models, materials,
images) so the member counts against the pools and collides like a seed; ``module build`` runs
the builder, reads the package it produced back with OpenAssetTools and links the pack against
it exactly as it would a seed. Nothing here trusts the builder's own word for what the package
carries: the readback is the manifest.

The builder is supplied by the workspace, never pinned by the toolkit: ``PAT_BACKEND_ADAPTER_BUILDER``
names an executable (a ``.py`` runs under the toolkit's interpreter), or ``--workspace`` names a
directory whose ``toolchain/pat-adapter-build`` (or ``.py``) is it. Its contract: argv
``<builder> <recipe.json> --output <new dir>``, exit 0, ``<dir>/build.json`` with ``status``
``succeeded`` and ``<dir>/stage/mod.ff`` beside its soundbanks, with loose scripts under
``<dir>/stage/scripts/``.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
from pathlib import Path

from ..core.errors import BACKEND_UNAVAILABLE, INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING, Failure
from ..core.jobs import Job
from . import backends

MAX_RECIPE_BYTES = 2 * 1024 * 1024
MAX_NAMES = 4096
MAX_ALIAS_BYTES = 4 * 1024 * 1024
MAX_ALIAS_ROWS = 4096
SCRIPT_INSTANCES = ("server", "client")
PROJECT_KEYS = ("schema", "game", "name")
ADAPTER_KEYS = ("schema", "foundation", "map")


def is_adapter_recipe(data) -> bool:
    """A recipe the toolkit cannot compile itself: it names the foundation and map it was cut for
    and has no ``game``/``name`` pair. A project recipe is decided first, so a file that carries
    both shapes is a project recipe and validated as one."""
    if not isinstance(data, dict) or data.get("schema") != 1:
        return False
    if all(key in data for key in PROJECT_KEYS):
        return False
    return all(key in data for key in ADAPTER_KEYS) and ("module" in data or "adapter" in data)


def _names(value, what: str, owner: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_NAMES or not all(isinstance(v, str) and 0 < len(v) <= 256 for v in value):
        raise Failure(INPUT_INVALID, f"{owner}: adapter recipe {what} is a list of at most {MAX_NAMES} names")
    return list(value)


def _rel(text, directory: Path, owner: str, what: str) -> Path:
    if not isinstance(text, str) or not text or len(text) > 4096 or "\\" in text or text != text.strip():
        raise Failure(INPUT_INVALID, f"{owner}: adapter recipe {what} is a forward-slash relative path")
    p = Path(text)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise Failure(INPUT_INVALID, f"{owner}: adapter recipe {what} stays inside the module directory: {text}")
    full = directory / p
    if not full.resolve().is_relative_to(directory.resolve()):
        raise Failure(INPUT_INVALID, f"{owner}: adapter recipe {what} escapes the module directory: {text}")
    return full


def _script_entries(data: dict, owner: str) -> list[dict]:
    rows = data.get("loose_scripts")
    if rows is None and data.get("loose_script") is not None:
        rows = [data["loose_script"]]
    if rows is None:
        rows = data.get("scripts", [])
    if not isinstance(rows, list) or len(rows) > 128:
        raise Failure(INPUT_INVALID, f"{owner}: adapter recipe scripts is a list of at most 128 entries")
    out = []
    for row in rows:
        if not isinstance(row, dict) or not {"source", "target"} <= set(row):
            raise Failure(INPUT_INVALID, f"{owner}: each adapter script names source and target")
        target = row["target"]
        if not isinstance(target, str) or "\\" in target or Path(target).is_absolute() or ".." in Path(target).parts:
            raise Failure(INPUT_INVALID, f"{owner}: adapter script target is a forward-slash zone path: {target!r}")
        instance = row.get("instance", "client" if target.lower().endswith(".csc") else "server")
        if instance not in SCRIPT_INSTANCES:
            raise Failure(INPUT_INVALID, f"{owner}: adapter script instance is server or client: {target}")
        out.append({"source": row["source"], "target": target, "instance": instance})
    return out


def read_aliases(path: Path, owner: str) -> list[str]:
    """Alias names from a soundbank alias CSV (the ``Name`` column), bounded; an unreadable or
    oddly shaped file yields nothing rather than a guess."""
    try:
        if path.stat().st_size > MAX_ALIAS_BYTES:
            raise Failure(INPUT_LIMIT, f"{owner}: alias table exceeds {MAX_ALIAS_BYTES} bytes")
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "Name" not in reader.fieldnames:
        return []
    names = []
    for row in reader:
        name = (row.get("Name") or "").strip()
        if name and name not in names:
            names.append(name)
        if len(names) > MAX_ALIAS_ROWS:
            raise Failure(INPUT_LIMIT, f"{owner}: alias table has more than {MAX_ALIAS_ROWS} rows")
    return names


def load_recipe(path: Path, directory: Path, job: Job, owner: str) -> dict:
    """Validate an adapter recipe, hash what the plan can see (the recipe, its pinned inputs
    record, every loose script source, the alias table when the prepared inputs are on this
    machine) and derive the seed-like facts the planner needs."""
    src = job.input(path, limit=MAX_RECIPE_BYTES)
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise Failure(INPUT_INVALID, f"{owner}: adapter recipe is not valid JSON: {src}") from exc
    if not is_adapter_recipe(data):
        raise Failure(INPUT_INVALID, f"{owner}: not an adapter recipe (schema 1 with foundation, map and module)")
    for key in ("foundation", "map"):
        if not isinstance(data[key], str) or not data[key] or len(data[key]) > 64:
            raise Failure(INPUT_INVALID, f"{owner}: adapter recipe {key} is a short identifier")
    weapons = _names(data.get("weapons"), "weapons", owner)
    if not weapons and isinstance(data.get("weapon"), str):
        weapons = [data["weapon"]]
    bank = None
    aliases_rel = None
    if data.get("soundbank") is not None:
        sb = data["soundbank"]
        if not isinstance(sb, dict) or not isinstance(sb.get("name"), str) or not sb["name"]:
            raise Failure(INPUT_INVALID, f"{owner}: adapter recipe soundbank names a bank")
        bank = sb["name"]
        aliases_rel = sb.get("aliases") if isinstance(sb.get("aliases"), str) else None
    localize = data.get("localize") or {}
    if not isinstance(localize, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in localize.items()) or len(localize) > MAX_NAMES:
        raise Failure(INPUT_INVALID, f"{owner}: adapter recipe localize maps references to strings")
    scripts = []
    for row in _script_entries(data, owner):
        source = _rel(row["source"], directory, owner, "script source")
        if source.is_symlink() or not source.is_file():
            raise Failure(INPUT_MISSING, f"{owner}: adapter script source is missing: {row['source']}")
        scripts.append({"source": job.input(source), "target": row["target"], "instance": row["instance"]})
    rawfiles = _names(data.get("rawfiles"), "rawfiles", owner)
    native_scripts = _names(data.get("native_scripts"), "native_scripts", owner)
    effects = _names(data.get("extra_effects"), "extra_effects", owner)
    assets = data.get("assets") or {}
    if not isinstance(assets, dict):
        raise Failure(INPUT_INVALID, f"{owner}: adapter recipe assets is an object of asset lists")
    models = _names(assets.get("xmodel"), "assets.xmodel", owner)
    materials = _names(assets.get("materials"), "assets.materials", owner)
    images = _names(assets.get("images"), "assets.images", owner)
    camo = _names(assets.get("camo"), "assets.camo", owner)
    explicit_roots = _names(data.get("roots"), "roots", owner)
    for row in explicit_roots:
        if "," not in row:
            raise Failure(INPUT_INVALID, f"{owner}: adapter recipe roots are 'type,name' rows: {row!r}")
    for rel in ("inputs",):
        if isinstance(data.get(rel), str):
            p = _rel(data[rel], directory, owner, rel)
            if p.is_file() and not p.is_symlink():
                job.input(p)
    embed_loose = bool(data.get("embed_loose_scripts", False))
    prepared = data.get("prepared") if isinstance(data.get("prepared"), str) else None
    prepared_present = bool(prepared) and Path(prepared).is_dir()
    aliases: list[str] = []
    clips: list[str] = []
    if prepared_present:
        if aliases_rel and "\\" not in aliases_rel and ".." not in Path(aliases_rel).parts:
            table = Path(prepared) / "assets" / aliases_rel
            if table.is_file() and not table.is_symlink():
                job.input(table, limit=MAX_ALIAS_BYTES)
                aliases = read_aliases(table, owner)
        record = Path(prepared) / "prepared.json"
        if record.is_file() and not record.is_symlink():
            try:
                job.input(record, limit=MAX_RECIPE_BYTES)
                entries = json.loads(record.read_text(encoding="utf-8")).get("entries", [])
                for entry in entries if isinstance(entries, list) else []:
                    if isinstance(entry, dict) and entry.get("id") in weapons and isinstance(entry.get("clips"), dict):
                        for clip in entry["clips"].values():
                            if isinstance(clip, str) and clip not in clips:
                                clips.append(clip)
            except (ValueError, OSError):
                clips = []
    clips = sorted(set(clips) | set(_names(data.get("extra_clips"), "extra_clips", owner)))
    embedded = ([f"weapon,{w}" for w in weapons] + ([f"soundbank,{bank}"] if bank else [])
                + [f"localize,{k}" for k in sorted(localize)] + [f"xanim,{c}" for c in clips]
                + [f"xmodel,{m}" for m in models] + [f"material,{m}" for m in materials] + [f"image,{i}" for i in images]
                + [f"camo,{c}" for c in camo] + [f"rawfile,{r}" for r in rawfiles] + [f"script,{s}" for s in native_scripts]
                + [f"fx,{e}" for e in effects] + explicit_roots)
    if embed_loose:
        rawfiles = rawfiles + [s["target"] for s in scripts]
        embedded += [f"rawfile,{s['target']}" for s in scripts]
    seen: list[str] = []
    for row in embedded:
        if row not in seen:
            seen.append(row)
    from . import seeds
    provides = seeds.provides_of(seen)
    provides["scripts"] = sorted([s["target"] for s in scripts] + native_scripts)
    for kind in ("weapons", "soundbanks"):
        provides.setdefault(kind, [])
    weapons = sorted(set(weapons) | set(provides["weapons"]))
    provides["weapons"] = weapons
    provides = {k: v for k, v in provides.items() if v}
    return {"recipe": src, "directory": directory, "foundation": data["foundation"], "map": data["map"],
            "profile": data.get("profile") if isinstance(data.get("profile"), str) else None,
            "weapons": weapons, "soundbank": bank, "aliases": aliases, "localize": dict(localize), "scripts": scripts,
            "rawfiles": rawfiles, "native_scripts": native_scripts, "effects": effects, "clips": clips,
            "embed_loose_scripts": embed_loose, "embedded": seen, "provides": provides,
            "prepared": prepared, "prepared_present": prepared_present}


def builder_argv(workspace: str | None) -> list[str]:
    """The workspace's adapter builder: an override, or ``toolchain/pat-adapter-build[.py]`` under
    ``--workspace``. Never pinned, never downloaded."""
    override = backends.override_for("adapter_builder")
    if override is not None:
        return [sys.executable, str(override)] if override.suffix.lower() == ".py" else [str(override)]
    if workspace:
        root = Path(workspace).expanduser()
        for name in ("pat-adapter-build", "pat-adapter-build.py"):
            candidate = root / "toolchain" / name
            if candidate.is_file() and not candidate.is_symlink():
                if candidate.suffix.lower() == ".py":
                    return [sys.executable, str(candidate)]
                if os.access(candidate, os.X_OK):
                    return [str(candidate)]
    raise Failure(BACKEND_UNAVAILABLE, "No adapter builder: set PAT_BACKEND_ADAPTER_BUILDER or pass --workspace with toolchain/pat-adapter-build",
                  "An adapter recipe is built by the workspace that owns its donor inputs; the toolkit runs that builder as a backend and reads the package back.")


def build(module: dict, args, job: Job, workspace: str | None) -> dict:
    """Run the workspace builder for one adapter member into ``<job>/adapters/<id>`` and turn the
    package it produced into a seed the pack links against. The manifest comes from an unlinker
    readback of the produced ``mod.ff``; the builder's own ``build.json`` is recorded, not trusted."""
    from types import SimpleNamespace

    from . import fastfiles, seeds

    mid = module["id"]
    adapter = module["adapter"]
    argv = builder_argv(workspace)
    out = job.root / "adapters" / mid
    if out.exists():
        raise Failure(INPUT_INVALID, f"Adapter output already exists for {mid}")
    out.parent.mkdir(parents=True, exist_ok=True)
    timeout = max(1, int(job.deadline - __import__("time").monotonic()))
    log = job.run([*argv, str(adapter["recipe"]), "--output", str(out)], timeout=min(args.timeout, timeout))
    record_path = out / "build.json"
    if record_path.is_symlink() or not record_path.is_file() or record_path.stat().st_size > MAX_RECIPE_BYTES:
        raise Failure(INPUT_INVALID, f"Adapter builder for {mid} wrote no build.json", f"See {log.name}")
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise Failure(INPUT_INVALID, f"Adapter builder for {mid} wrote an unreadable build.json") from exc
    if not isinstance(record, dict) or record.get("status") != "succeeded":
        raise Failure(INPUT_INVALID, f"Adapter builder for {mid} did not report status succeeded",
                      "Read the builder's own log under the job's adapters directory.", builder_status=record.get("status") if isinstance(record, dict) else None)
    stage = out / "stage"
    package = stage / "mod.ff"
    if package.is_symlink() or not package.is_file():
        raise Failure(INPUT_MISSING, f"Adapter builder for {mid} produced no stage/mod.ff")
    banks = sorted(p for p in stage.iterdir() if p.is_file() and not p.is_symlink() and seeds.BANK.match(p.name))
    listing = fastfiles.execute(SimpleNamespace(action="inspect", input=str(package), load=[], timeout=args.timeout),
                                Job(out / "readback", "ff inspect", ["pat", "ff", "inspect", str(package)], timeout=timeout))
    text = (out / "readback" / listing["inventory_log"]).read_text(encoding="utf-8", errors="replace")
    embedded, referenced = seeds.parse_listing(text)
    if not embedded:
        raise Failure(INPUT_INVALID, f"Adapter package for {mid} lists no embedded assets")
    roots = seeds.roots_of(embedded)
    strings = None
    if adapter["localize"]:
        strings = out / "mod.str"
        strings.write_text(seeds.write_strings(adapter["localize"]), encoding="utf-8")
    loose = []
    scripts_dir = stage / "scripts"
    if scripts_dir.is_dir():
        for directory, dirs, files in os.walk(scripts_dir, followlinks=False):
            dirs.sort()
            for name in sorted(files):
                p = Path(directory) / name
                if not p.is_symlink() and p.suffix.lower() in (".gsc", ".csc"):
                    loose.append((p, Path("scripts") / p.relative_to(scripts_dir)))
    from ..core.receipts import sha256_file
    files = {"mod.ff": package}
    for bank in banks:
        files[bank.name] = bank
    return {"package": package, "files": files, "roots": roots, "embedded": embedded, "referenced": referenced,
            "provides": seeds.provides_of(embedded), "strings": strings, "private": False, "missing": [],
            "manifest": record_path, "directory": stage, "loose_scripts": loose,
            "report": {"id": mid, "output": str(out), "builder": argv[-1] if argv else None, "log": log.name,
                       "mod_ff_sha256": sha256_file(package), "builder_mod_ff_sha256": record.get("mod_ff_sha256"),
                       "embedded": len(embedded), "referenced": len(referenced), "roots": len(roots),
                       "soundbanks": [b.name for b in banks], "loose_scripts": [t.as_posix() for _, t in loose]}}
