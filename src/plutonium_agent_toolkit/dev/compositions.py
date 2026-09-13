"""``module plan|build|declare``: declared modules composed into one mod on a named base.

A module declaration (``module.json``) sits beside a module's payload and says what the module is
and needs. The payload is either a ``project.json`` recipe (scripts and loose assets the toolkit
compiles and links) or a seed (an already-linked ``mod.ff`` with a manifest, see ``seeds.py``).
A composition recipe (``composition.json``) names a base, a map and the members to compose:
module directories, other compositions (a pack used as a base for a bigger pack), or references
to published modules pinned at a commit. ``plan`` resolves the composition (dependency order,
conflicts, base and map fit, budget) and lists every collision as a decision for the agent to
record; ``build`` compiles every recipe module's scripts, links one ``mod.ff`` as zone ``mod``
against every seed and load, reads it back and byte-compares every rawfile. Both formats are
specified in ``docs/MODULES.md``.

Module declaration (``module.json``, schema 1)::

    {
      "schema": 1, "id": "penetrator", "version": "0.1.0", "title": "The Penetrator",
      "category": "weapons", "kind": "melee", "tags": ["saints-row"],
      "seed": "seed.json",                       # or "recipe": "project.json"
      "bases": ["b2"], "maps": ["zm_factory"],
      "dependencies": [], "conflicts": [],
      "provides": {"weapons": ["halo_penetrator_zm"]},
      "resource_contract": {"threads": 0, "entities": 0, "hud": 0, "network_fields": 0},
      "menu_route": "Equipment & melee > Melee > The Penetrator",
      "distribution": "seed",
      "source": {"repository": "https://github.com/<owner>/<repo>", "commit": "<40 hex>"},
      "origin": "saints-row",                   # the game the identity comes from; "unverified" when unknown
      "donor": "Saints Row: The Third assets converted by <who>, 2026"   # credit for where the bytes came from
    }

Composition recipe (``composition.json``, schema 1)::

    {
      "schema": 1, "name": "b2_enhanced_penetrator_pack", "base": "b2", "map": "zm_factory",
      "modules": [
        {"path": "../dlc5-enhanced", "role": "base"},
        "../penetrator",
        {"name": "owner/round_announcer", "commit": "<40 hex>", "path": "../fetched/round_announcer"}
      ],
      "loads": ["../base/zone/common_zm.ff"],
      "budget": {"threads": 4, "entities": 0, "hud": 0, "network_fields": 0},
      "decisions": [{"collision": "scripts/zm/hud.gsc", "owner": "dlc5_enhanced", "reason": "the pack's HUD wins"}]
    }
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import re
import shutil
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

from ..core.errors import BACKEND_FAILED, INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING, Failure
from ..core.jobs import Job
from ..core.receipts import FILE_FLAGS, sha256_file
from . import fastfiles, projects, scripts, seeds, titles
from .backends import executable

ID = re.compile(r"^[a-z0-9_]{1,64}\Z")
BASE = re.compile(r"^[a-z0-9]{1,16}\Z")
MAP = re.compile(r"^[a-z0-9_]{1,64}\Z")
VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,31}\Z")
CATEGORY = re.compile(r"^[a-z][a-z0-9-]{0,31}\Z")
TAG = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}\Z")
COMMIT = re.compile(r"^[0-9a-f]{40}\Z")
NAME_REF = re.compile(r"^[a-z0-9][a-z0-9-]{0,38}/[a-z0-9_]{1,64}\Z")
STAGES = ("test", "probe", "pack", "pub")
CONTRACT_FIELDS = ("threads", "entities", "hud", "network_fields")
# The taxonomy people browse by. `category` is the shelf; `kind` narrows it; `tags` are free
# lowercase words (a source game, a series, a theme). None of them affects resolution.
CATEGORIES = ("weapons", "perks", "gobblegums", "powerups", "equipment", "bosses", "companions", "maps", "ui",
              "core", "scripts", "audio", "tooling", "pack", "module")
KINDS = {"weapons": ("wonder", "firearm", "melee", "launcher", "special"), "perks": ("perk", "machine"),
         "gobblegums": ("gum", "machine"), "powerups": ("powerup",), "equipment": ("tactical", "lethal", "buildable", "shield"),
         "bosses": ("boss", "special-round"), "companions": ("companion",), "maps": ("map", "patch"),
         "ui": ("hud", "menu"), "core": ("inventory", "registry", "adapter"), "scripts": ("script",),
         "audio": ("bank", "music"), "tooling": ("tool",), "pack": ("pack",), "module": ()}
DISTRIBUTIONS = ("source", "seed", "private")
# Origin is the game or series the thing's identity comes from (the ICR-1 is a Black Ops III rifle
# whichever pack it was converted from); it drives the title. Donor is who or what the bytes came
# from (a conversion pack, a capture, a person) and drives the credit line. Neither affects
# resolution. An origin nobody has verified says so instead of defaulting to the donor.
ORIGIN_UNVERIFIED = "unverified"
MAX_DONOR = 400
PROVIDES_KINDS = ("weapons", "perks", "gobblegums", "powerups", "equipment", "localize", "soundbanks", "scripts", "models", "effects",
                  "rawfiles")
# A whole pack declared as one seed lists every asset it embeds; a Beta-era pack carries several
# hundred models and weapons, so a declaration that narrows provides by copying the manifest block
# needs room above the per-kind count a hand-written declaration would ever reach.
MAX_PROVIDES_NAMES = 4096
# The kinds a seed manifest derives from the package listing (seeds.provides_of). For these the
# manifest is the fact: a non-private seed's declaration may only narrow them, and a name the
# manifest does not list (including every name when the manifest lists none) is a contradiction.
# Kinds the listing cannot see (perks, gobblegums, powerups, equipment, scripts) stay the declaration's.
MANIFEST_KINDS = ("weapons", "localize", "soundbanks", "rawfiles", "models", "effects")
MAX_MODULES = 128
MAX_DECISIONS = 1024
MAX_BASE_LISTINGS = 8
MAX_LIST = 64
MAX_TAGS = 16
MAX_CONTRACT = 100_000
MAX_NESTING = 4


def add_parser(sub, common):
    p = sub.add_parser("module", help="Declared modules composed into one mod on a named base: plan, build, declare")
    actions = p.add_subparsers(dest="action", required=True)
    q = actions.add_parser("inspect", help="Validate one declaration's metadata without resolving payloads or creating a job")
    q.add_argument("declaration", help="Path to module.json or composition.json")
    q.add_argument("--json", action="store_true")
    for action, help_text in (("plan", "Resolve a composition, list collisions as decisions and hash its inputs; runs no backend"),
                              ("build", "Compile, link against seeds and loads, read back and compare every module into one mod.ff")):
        q = actions.add_parser(action, help=help_text)
        q.add_argument("composition", help="Path to composition.json")
        common(q)
    q = actions.add_parser("fetch", help="Download a published module or pack at its exact commit into a new directory")
    q.add_argument("reference", help="<owner>/<id>@<commit> (through a recorded registry) or https://github.com/<owner>/<repo>@<commit>")
    q.add_argument("--path", help="Directory inside the repository that holds module.json or composition.json (default: the registry entry's path, or the root)")
    common(q)
    q = actions.add_parser("declare", help="Read a prebuilt mod.ff back and draft its seed manifest and declaration")
    q.add_argument("package", help="Path to a mod.ff (soundbanks beside it are hashed too)")
    q.add_argument("--load", action="append", default=[], help="Base fastfile the package references; repeat as needed")
    q.add_argument("--game", choices=titles.names(), default=None, help="Title the package targets; inferred from the fastfile magic when omitted")
    q.add_argument("--id", help="Module id for the draft declaration")
    q.add_argument("--title", help="Display title for the draft")
    q.add_argument("--category", help="Category for the draft (weapons, perks, ...)")
    q.add_argument("--base", help="Base token the package was built and tested on")
    q.add_argument("--map", help="Map id the package was tested on")
    common(q)


# ----- inert declaration inspection ------------------------------------------------------

INSPECT_PROTOCOL = "pat.module-inspect/1"
MAX_DECLARATION_BYTES = 256 * 1024
MAX_INSPECTION_TEXT = 2048
MAX_INSPECTION_CODE = 200
MODULE_METADATA_FIELDS = ("id", "version", "game", "title", "category", "kind", "tags", "bases", "maps",
                          "dependencies", "conflicts", "origin", "donor", "distribution", "menu_route", "payload")
COMPOSITION_METADATA_FIELDS = ("name", "title", "game", "tags", "base", "map", "origin", "donor", "members")


def _read_inspection(path: Path) -> bytes:
    """One bounded regular-file read. Refuse final links/reparse points and changed identities.

    Symlinked ancestors are allowed, as in plan/build. POSIX also refuses a final-component
    link at open. Windows uses lstat/fstat identity checks, like the receipt reader;
    no native Windows qualification is claimed here.
    """
    def checked_stat():
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise Failure(INPUT_MISSING, f"Declaration is missing or is a link: {path}")
        if not stat.S_ISREG(info.st_mode):
            raise Failure(INPUT_MISSING, f"Declaration is not a regular file: {path}")
        return info

    try:
        before = checked_stat()
        if before.st_size > MAX_DECLARATION_BYTES:
            raise Failure(INPUT_LIMIT, f"Declaration exceeds {MAX_DECLARATION_BYTES} bytes: {path}")
        with os.fdopen(os.open(path, FILE_FLAGS), "rb") as stream:
            opened = os.fstat(stream.fileno())
            after = checked_stat()
            if not stat.S_ISREG(opened.st_mode) or any(
                    (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino) for info in (before, after)):
                raise Failure(INPUT_MISSING, f"Declaration changed while opening: {path}")
            data = stream.read(MAX_DECLARATION_BYTES + 1)
        if len(data) > MAX_DECLARATION_BYTES:
            raise Failure(INPUT_LIMIT, f"Declaration exceeds {MAX_DECLARATION_BYTES} bytes: {path}")
        return data
    except (OSError, ValueError) as exc:
        raise Failure(INPUT_MISSING, f"Cannot read declaration: {path} ({exc})") from exc


def _inspection_units(text: str) -> int:
    """JavaScript string length: supplementary characters use two UTF-16 code units.

    Count directly so escaped lone surrogates count as one without an encoding error.
    """
    return sum(2 if ord(char) > 0xFFFF else 1 for char in text)


def _inspection_prose(text: str, notice: str = "") -> str:
    """Replace excessive detail explicitly; never return a misleading truncated value."""
    if _inspection_units(notice + text) <= MAX_INSPECTION_TEXT:
        return notice + text
    return notice + f"Inspection detail omitted due to the diagnostic limit of {MAX_INSPECTION_TEXT} UTF-16 code units."


def _inspection_failure(exc: Failure, result: dict) -> Failure:
    """Bound the inspection transport without changing shared validator failures."""
    field = exc.details.get("field", "/")
    notice = ""
    if _inspection_units(field) > MAX_INSPECTION_TEXT:
        field = "/"
        notice = f"The offending key exceeds the diagnostic limit of {MAX_INSPECTION_TEXT} UTF-16 code units; its JSON Pointer is omitted. "
    code = exc.code
    if _inspection_units(code) > MAX_INSPECTION_CODE:
        code = INPUT_INVALID
        notice += f"The original error code exceeds the diagnostic limit of {MAX_INSPECTION_CODE} UTF-16 code units and is omitted. "
    message = _inspection_prose(exc.message, notice)
    result["diagnostics"] = [{"field": field, "error_code": code, "message": message}]
    return Failure(code, message, _inspection_prose(exc.hint), inspection=result)


def inspect(path: Path) -> dict:
    """Inspect metadata only; exact input bytes supply both the digest and JSON parser."""
    path = path.absolute()  # Do not resolve away a symlink before the bounded read.
    result = {"protocol": INSPECT_PROTOCOL, "file": str(path), "sha256": None, "kind": "unknown",
              "validation": "invalid", "validation_scope": "declaration-only", "metadata": None, "diagnostics": []}
    try:
        raw = _read_inspection(path)
        result["sha256"] = hashlib.sha256(raw).hexdigest()
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, RecursionError) as exc:
            raise Failure(INPUT_INVALID, f"Declaration is not valid JSON: {path}", field="/") from exc
        # Explicit filenames disambiguate malformed declarations; renamed files use their keys.
        kind = {"module.json": "module", "composition.json": "composition"}.get(path.name)
        if kind is None and isinstance(data, dict):
            kind = "module" if "id" in data else "composition" if "modules" in data or "name" in data else None
        if kind == "module":
            result["kind"] = "module"
            metadata = validate_declaration_metadata(data)
            fields = MODULE_METADATA_FIELDS
        elif kind == "composition":
            result["kind"] = "composition"
            metadata = validate_composition_metadata(data)
            fields = COMPOSITION_METADATA_FIELDS
        else:
            raise Failure(INPUT_INVALID, "Expected a module or composition declaration", field="/")
        result.update(validation="metadata-valid", metadata={key: metadata[key] for key in fields})
        return result
    except Failure as exc:
        raise _inspection_failure(exc, result) from exc


# ----- declarations ---------------------------------------------------------------------

def _pointer(key) -> str:
    return "/" + str(key).replace("~", "~0").replace("/", "~1")


def _at(field: str, validate, *args):
    """Attach structural source coordinates, never inferred from an error message."""
    try:
        return validate(*args)
    except Failure as exc:
        child = exc.details.get("field", "/")
        exc.details["field"] = field + (child if child != "/" else "")
        raise


def _fields(row, allowed: set, required: set, what: str, field: str = "") -> None:
    try:
        projects._fields(row, allowed, required, what)
    except Failure as exc:
        key = None
        if isinstance(row, dict):
            unknown = sorted(set(row) - allowed)
            missing = sorted(required - set(row))
            key = (unknown or missing or [None])[0]
            if unknown:
                exc.message += f"; unknown field {key!r}"
        exc.details["field"] = field + _pointer(key) if key is not None else field or "/"
        raise


def _recipe_path(text: str) -> None:
    """The lexical part of projects._rel; containment is checked during resolution."""
    p = Path(text)
    if p.is_absolute() or PureWindowsPath(text).anchor or ".." in p.parts or not p.parts or text != text.strip() or "\\" in text:
        raise Failure(INPUT_INVALID, f"Use forward-slash relative paths inside the recipe directory: {text}")


def _relative_path(text: str, what: str) -> str:
    """Shared declaration-only part of composition directory/file resolution."""
    if not isinstance(text, str) or not text or len(text) > 4096 or "\\" in text or text != text.strip():
        raise Failure(INPUT_INVALID, f"{what} paths are forward-slash relative paths")
    p = Path(text)
    if text.startswith("/") or p.is_absolute() or not p.parts:
        raise Failure(INPUT_INVALID, f"{what} paths are relative to the composition directory: {text}")
    return text


def _text(value, what: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise Failure(INPUT_INVALID, f"{what} must be a non-empty string of at most {limit} characters")
    return value


def _origin(value, owner: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not TAG.match(value):
        raise Failure(INPUT_INVALID, f"{owner}: origin is one lowercase word naming the game or series the identity comes from "
                                     f"(bo3, waw, saints-row), or {ORIGIN_UNVERIFIED!r}")
    return value


def _donor(value, owner: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_DONOR or "\n" in value or "\r" in value:
        raise Failure(INPUT_INVALID, f"{owner}: donor is one line of credit of at most {MAX_DONOR} characters "
                                     "(the pack, capture or person the bytes came from)")
    return value


def _ids(value, what: str, owner: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_LIST:
        raise Failure(INPUT_INVALID, f"{owner}: {what} must be a list of at most {MAX_LIST} module ids")
    for index, item in enumerate(value):
        if not isinstance(item, str) or not ID.match(item):
            raise Failure(INPUT_INVALID, f"{owner}: {what} entries use lowercase letters, digits and underscore: {item!r}", field=f"/{index}")
        if item == owner:
            raise Failure(INPUT_INVALID, f"{owner}: a module cannot list itself under {what}", field=f"/{index}")
    if len(set(value)) != len(value):
        raise Failure(INPUT_INVALID, f"{owner}: duplicate entries under {what}")
    return list(value)


def _contract(value, what: str) -> dict:
    if value is None:
        return {field: 0 for field in CONTRACT_FIELDS}
    if not isinstance(value, dict) or set(value) - set(CONTRACT_FIELDS):
        unknown = sorted(set(value) - set(CONTRACT_FIELDS)) if isinstance(value, dict) else []
        suffix = f"; unknown field {unknown[0]!r}" if unknown else ""
        raise Failure(INPUT_INVALID, f"{what} names only {list(CONTRACT_FIELDS)}{suffix}",
                      field=_pointer(unknown[0]) if unknown else "/")
    rows = {}
    for field in CONTRACT_FIELDS:
        n = value.get(field, 0)
        if type(n) is not int or n < 0 or n > MAX_CONTRACT:
            raise Failure(INPUT_INVALID, f"{what}.{field} must be a whole number from 0 to {MAX_CONTRACT}", field=_pointer(field))
        rows[field] = n
    return rows


def _provides(value, owner: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - set(PROVIDES_KINDS):
        unknown = sorted(set(value) - set(PROVIDES_KINDS)) if isinstance(value, dict) else []
        suffix = f"; unknown field {unknown[0]!r}" if unknown else ""
        raise Failure(INPUT_INVALID, f"{owner}: provides maps kinds {list(PROVIDES_KINDS)} to lists of names{suffix}",
                      field=_pointer(unknown[0]) if unknown else "/")
    out = {}
    for kind, names in value.items():
        if not isinstance(names, list) or len(names) > MAX_PROVIDES_NAMES or not all(isinstance(n, str) and 0 < len(n) <= 128 for n in names):
            raise Failure(INPUT_INVALID, f"{owner}: provides.{kind} is a list of names", field=_pointer(kind))
        if len(set(names)) != len(names):
            raise Failure(INPUT_INVALID, f"{owner}: duplicate names under provides.{kind}", field=_pointer(kind))
        out[kind] = list(names)
    return out


def _relative_dir(text: str, base: Path, job: Job, what: str) -> Path:
    """A directory named in a composition: relative, forward slashes, may live beside the
    composition (``../hello-zm``), never absolute, never a link, never inside the job output."""
    _relative_path(text, what)
    full = base / Path(text)
    if full.is_symlink() or not full.is_dir():
        raise Failure(INPUT_MISSING, f"{what} directory is missing or is a link: {text}")
    full = full.resolve()
    if full.is_relative_to(job.root):
        raise Failure(INPUT_INVALID, f"{what} directories must live outside the job's output directory")
    return full


def _relative_file(text: str, base: Path, job: Job, what: str) -> Path:
    """A file named in a composition (a base fastfile to load): relative like a member directory,
    so a pack may point at zones kept beside it (``../base/common_zm.ff``), never absolute or a link."""
    _relative_path(text, what)
    full = base / Path(text)
    if full.is_symlink() or not full.is_file():
        raise Failure(INPUT_MISSING, f"{what} file is missing or is a link: {text}")
    return job.input(full)


def validate_declaration_metadata(data, *, where: str = "module.json") -> dict:
    """Authoritative declaration checks; no filesystem or payload resolution."""
    _fields(data, {"schema", "id", "version", "game", "title", "category", "kind", "tags", "recipe", "seed", "bases", "maps",
                            "dependencies", "conflicts", "provides", "resource_contract", "menu_route", "distribution", "source",
                            "origin", "donor"},
                     {"schema", "id", "version", "bases", "maps"}, where)
    if data["schema"] != 1:
        raise Failure(INPUT_INVALID, f"{where}: expected schema 1", field='/schema')
    game = data.get("game", titles.DEFAULT_TITLE)
    if game not in titles.names():
        raise Failure(INPUT_INVALID, f"{where}: game is one of {', '.join(titles.names())}", field='/game')
    mid = data["id"]
    if not isinstance(mid, str) or not ID.match(mid):
        raise Failure(INPUT_INVALID, f"{where}: id uses lowercase letters, digits and underscore", field='/id')
    if not isinstance(data["version"], str) or not VERSION.match(data["version"]):
        raise Failure(INPUT_INVALID, f"{mid}: version is a short version string (letters, digits, dot, plus, dash)", field='/version')
    title = _at("/title", _text, data.get("title", mid), f"{mid}: title", 120)
    category = data.get("category", "module")
    if not isinstance(category, str) or not CATEGORY.match(category):
        raise Failure(INPUT_INVALID, f"{mid}: category is a lowercase identifier such as weapons, perks or scripts", field='/category')
    kind = data.get("kind")
    if kind is not None and (not isinstance(kind, str) or not CATEGORY.match(kind)):
        raise Failure(INPUT_INVALID, f"{mid}: kind is a lowercase identifier that narrows the category (melee, wonder, perk, ...)", field='/kind')
    title_kinds = titles.kinds(game)
    if kind is not None and category in title_kinds and title_kinds[category] and kind not in title_kinds[category]:
        raise Failure(INPUT_INVALID, f"{mid}: kind {kind!r} is not one of {list(title_kinds[category])} for category {category!r} in game {game}",
                      "Use a listed kind so packs and catalogs group modules the same way, or drop kind and keep only tags.", field='/kind')
    tags = data.get("tags", [])
    if not isinstance(tags, list) or len(tags) > MAX_TAGS or not all(isinstance(t, str) and TAG.match(t) for t in tags) \
            or len(set(tags)) != len(tags):
        raise Failure(INPUT_INVALID, f"{mid}: tags is a list of at most {MAX_TAGS} distinct lowercase words (a source game, a series, a theme)", field='/tags')
    if ("recipe" in data) == ("seed" in data):
        raise Failure(INPUT_INVALID, f"{mid}: a declaration names exactly one payload: recipe (project.json) or seed (seed.json)", field='/recipe')
    payload = "recipe" if "recipe" in data else "seed"
    payload_path = _at("/" + payload, _text, data[payload], f"{mid}: {payload}", 4096)
    if payload == "recipe":
        _at("/recipe", _recipe_path, payload_path)
    distribution = data.get("distribution", "seed" if "seed" in data else "source")
    if distribution not in DISTRIBUTIONS:
        raise Failure(INPUT_INVALID, f"{mid}: distribution is one of {list(DISTRIBUTIONS)}", field='/distribution')
    if payload == "seed" and ("\\" in payload_path or Path(payload_path).is_absolute()
                              or PureWindowsPath(payload_path).anchor or ".." in Path(payload_path).parts):
        raise Failure(INPUT_INVALID, f"{mid}: seed is a forward-slash relative path inside the module directory", field="/seed")
    bases = data["bases"]
    if not isinstance(bases, list) or not bases or len(bases) > MAX_LIST or not all(isinstance(b, str) and BASE.match(b) for b in bases) \
            or len(set(bases)) != len(bases):
        raise Failure(INPUT_INVALID, f"{mid}: bases is a non-empty list of distinct base tokens (lowercase letters and digits)", field='/bases')
    maps = data["maps"]
    if not isinstance(maps, list) or not maps or len(maps) > MAX_LIST or not all(isinstance(m, str) and (m == "*" or MAP.match(m)) for m in maps) \
            or len(set(maps)) != len(maps):
        raise Failure(INPUT_INVALID, f"{mid}: maps is a non-empty list of distinct map ids, or [\"*\"] for any map", field='/maps')
    menu_route = data.get("menu_route", "")
    if not isinstance(menu_route, str) or len(menu_route) > 200:
        raise Failure(INPUT_INVALID, f"{mid}: menu_route is a string of at most 200 characters", field='/menu_route')
    source = data.get("source")
    if source is not None:
        _fields(source, {"repository", "commit"}, {"repository"}, f"{mid}: source", "/source")
        repository = _at("/source/repository", _text, source["repository"], f"{mid}: source.repository", 512)
        if not repository.startswith("https://"):
            raise Failure(INPUT_INVALID, f"{mid}: source.repository is an https URL", field='/source/repository')
        if "commit" in source and (not isinstance(source["commit"], str) or not COMMIT.match(source["commit"])):
            raise Failure(INPUT_INVALID, f"{mid}: source.commit is a 40-character lowercase hex commit id", field='/source/commit')
    provides = _at("/provides", _provides, data.get("provides"), mid)
    return {"id": mid, "version": data["version"], "game": game, "title": title, "category": category, "kind": kind, "tags": list(tags),
            "payload": payload, "payload_path": payload_path, "distribution": distribution,
            "bases": list(bases), "maps": list(maps),
            "dependencies": _at("/dependencies", _ids, data.get("dependencies", []), "dependencies", mid),
            "conflicts": _at("/conflicts", _ids, data.get("conflicts", []), "conflicts", mid),
            "provides": provides,
            "resource_contract": _at("/resource_contract", _contract, data.get("resource_contract"), f"{mid}: resource_contract"),
            "menu_route": menu_route, "source": source,
            "origin": _at("/origin", _origin, data.get("origin"), mid), "donor": _at("/donor", _donor, data.get("donor"), mid)}


def load_declaration(directory: Path, job: Job) -> dict:
    path = directory / "module.json"
    if path.is_symlink() or not path.is_file():
        raise Failure(INPUT_MISSING, f"Module directory has no module.json: {directory}")
    src = job.input(path, limit=256 * 1024)
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise Failure(INPUT_INVALID, f"module.json is not valid JSON: {src}") from exc
    declaration = validate_declaration_metadata(data, where=f"module.json in {directory.name}")
    mid = declaration["id"]
    distribution = declaration["distribution"]
    recipe = seed = None
    if declaration["payload"] == "recipe":
        recipe = projects._rel(declaration["payload_path"], directory)
        if recipe.is_symlink() or not recipe.is_file():
            raise Failure(INPUT_MISSING, f"{mid}: recipe is missing: {data['recipe']}")
    else:
        seed_rel = declaration["payload_path"]
        if distribution == "private" and not (directory / seed_rel).is_file():
            seed = {"private": True, "relative": seed_rel, "provides": {}, "missing": ["seed manifest"]}
        else:
            seed = seeds.load_manifest(directory, seed_rel, job, mid, allow_missing_files=distribution == "private")
    provides = declaration["provides"]
    if seed and not seed.get("private"):
        # The manifest is the fact; a declaration may narrow it, never contradict it.
        for pkind, names in provides.items():
            if pkind not in MANIFEST_KINDS:
                continue
            listed = set(seed["provides"].get(pkind, []))
            if not set(names) <= listed:
                raise Failure(INPUT_INVALID, f"{mid}: provides.{pkind} names {sorted(set(names) - listed)} which the seed manifest does not list",
                              "A seed's manifest is the fact for what the package embeds; a declaration may narrow that list, never add to it.")
        for pkind, names in seed["provides"].items():
            provides.setdefault(pkind, list(names))
    declaration.pop("payload")
    declaration.pop("payload_path")
    return declaration | {"directory": directory, "recipe": recipe, "seed": seed, "declaration": src}


# ----- compositions ----------------------------------------------------------------------

LISTING_ROW = re.compile(r"^([a-z0-9_]+),\s*([^\s,][^\n]*)$")  # embedded rows only; a reference row (type, ,name) is not a base copy


def _base_owned(listings: list[Path]) -> set[str]:
    """Asset names the base zones already carry, read from plain listings (one ``type,name``
    row per line, the shape an unlinker ``--list`` prints). A reference row (``type, ,name``)
    means the zone only points at the asset, so it is skipped: the base has no copy to win
    with. A seed that carries an embedded name got it by linking against the base; the base
    wins and no decision is needed. Listings are read line by line and capped at 200000 rows
    and 64 MiB."""
    names: set[str] = set()
    for path in listings:
        if path.stat().st_size > 64 * 1024 * 1024:
            raise Failure(INPUT_LIMIT, f"Base listing is larger than 64 MiB: {path.name}")
        rows = 0
        for line in path.open(encoding="utf-8", errors="replace"):
            m = LISTING_ROW.match(line.strip())
            if not m:
                continue
            rows += 1
            if rows > 200_000:
                raise Failure(INPUT_LIMIT, f"Base listing has more than 200000 rows: {path.name}")
            names.add(f"{m.group(1)},{m.group(2).strip()}".casefold())
    return names


def _decisions(value, comp_name: str) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_DECISIONS:
        raise Failure(INPUT_INVALID, f"{comp_name}: decisions is a list of at most {MAX_DECISIONS} recorded decisions", field='/')
    rows = []
    seen = set()
    for index, row in enumerate(value):
        _fields(row, {"collision", "owner", "reason"}, {"collision", "owner"}, f"{comp_name}: decision", f"/{index}")
        collision = _at(f"/{index}/collision", _text, row["collision"], f"{comp_name}: decision.collision", 512)
        owner = row["owner"]
        if not isinstance(owner, str) or not ID.match(owner):
            raise Failure(INPUT_INVALID, f"{comp_name}: decision.owner is a module id in the composition", field=f"/{index}/owner")
        reason = row.get("reason", "")
        if not isinstance(reason, str) or len(reason) > 400:
            raise Failure(INPUT_INVALID, f"{comp_name}: decision.reason is at most 400 characters", field=f"/{index}/reason")
        key = collision.casefold()
        if key in seen:
            raise Failure(INPUT_INVALID, f"{comp_name}: two decisions for the same collision: {collision}", field=f"/{index}/collision")
        seen.add(key)
        rows.append({"collision": collision, "owner": owner, "reason": reason})
    return rows


def validate_composition_metadata(data) -> dict:
    """Authoritative composition checks without opening members, loads or listings."""
    _fields(data, {"schema", "name", "game", "base", "map", "modules", "loads", "budget", "decisions", "title", "tags", "zone_header",
                            "origin", "donor", "base_owned"},
                     {"schema", "name", "base", "map", "modules"}, "composition")
    if data["schema"] != 1:
        raise Failure(INPUT_INVALID, "Expected a schema 1 composition", field='/schema')
    game = data.get("game", titles.DEFAULT_TITLE)
    if game not in titles.names():
        raise Failure(INPUT_INVALID, f"Composition game is one of {', '.join(titles.names())}", field='/game')
    base = data["base"]
    if not isinstance(base, str) or not BASE.match(base):
        raise Failure(INPUT_INVALID, "Composition base is a short token of lowercase letters and digits (stock, or the base release's short name)", field='/base')
    map_id = data["map"]
    if not isinstance(map_id, str) or not MAP.match(map_id):
        raise Failure(INPUT_INVALID, "Composition map is one concrete map id; a composition is planned for one map", field='/map')
    name = data["name"]
    if not isinstance(name, str) or not projects.NAME.match(name) \
            or not re.fullmatch(rf"{re.escape(base)}_[a-z0-9_]+_(?:{'|'.join(STAGES)})", name):
        raise Failure(INPUT_INVALID, f"Composition name follows <base>_<feature>_<stage> with base {base!r} and stage test, pack or pub", field='/name')
    title = data.get("title", name)
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise Failure(INPUT_INVALID, "Composition title is at most 120 characters", field='/title')
    tags = data.get("tags", [])
    if not isinstance(tags, list) or len(tags) > MAX_TAGS or not all(isinstance(t, str) and TAG.match(t) for t in tags):
        raise Failure(INPUT_INVALID, f"Composition tags is a list of at most {MAX_TAGS} lowercase words", field='/tags')
    entries = data["modules"]
    if not isinstance(entries, list) or not entries or len(entries) > MAX_MODULES:
        raise Failure(INPUT_INVALID, f"modules lists 1 to {MAX_MODULES} members", field='/modules')
    members = []
    base_members = 0
    for index, entry in enumerate(entries):
        row = {"path": entry} if isinstance(entry, str) else entry
        _fields(row, {"path", "name", "commit", "role"}, set(), "composition member", f"/modules/{index}")
        role = row.get("role", "module")
        if role not in ("module", "base"):
            raise Failure(INPUT_INVALID, "A member's role is module or base", field=f"/modules/{index}/role")
        if "name" in row:
            ref = row["name"]
            if not isinstance(ref, str) or not NAME_REF.match(ref):
                raise Failure(INPUT_INVALID, f"A reference name is <github-owner>/<module id>: {ref!r}", field=f"/modules/{index}/name")
            if not isinstance(row.get("commit"), str) or not COMMIT.match(row["commit"]):
                raise Failure(INPUT_INVALID, f"Reference {ref} needs a 40-hex commit; a pack pins what it was built from", field=f"/modules/{index}/commit")
            if "path" not in row:
                raise Failure(INPUT_MISSING, f"Reference {ref} is not fetched: add its local path once module fetch has placed it",
                              "pat module fetch is the route that resolves a reference into a directory; until then name the fetched path here.", field=f"/modules/{index}/path")
        elif "commit" in row:
            raise Failure(INPUT_INVALID, "commit belongs to a reference (with name); a local path member has none", field=f"/modules/{index}/commit")
        if "path" not in row:
            raise Failure(INPUT_INVALID, "Every member names a path", field=f"/modules/{index}/path")
        _at(f"/modules/{index}/path" if isinstance(entry, dict) else f"/modules/{index}",
            _relative_path, row["path"], "Member")
        if role == "base":
            base_members += 1
        members.append({"path": row["path"], "role": role, "name": row.get("name"), "commit": row.get("commit")})
    if base_members > 1:
        raise Failure(INPUT_INVALID, "A composition names at most one member with role base",
                      "The base is the pack everything else attaches to; put a second pack in as an ordinary member or nest it.", field='/modules')
    load_rows = data.get("loads", [])
    if not isinstance(load_rows, list) or len(load_rows) > projects.MAX_LOADS:
        raise Failure(INPUT_INVALID, f"loads is a list of at most {projects.MAX_LOADS} fastfiles", field='/loads')
    loads = [_at(f"/loads/{index}", _relative_path, text, "Load") for index, text in enumerate(load_rows)]
    listing_rows = data.get("base_owned", [])
    if not isinstance(listing_rows, list) or len(listing_rows) > MAX_BASE_LISTINGS:
        raise Failure(INPUT_INVALID, f"base_owned is a list of at most {MAX_BASE_LISTINGS} asset listings of the base zones", field='/base_owned')
    base_owned = [_at(f"/base_owned/{index}", _relative_path, text, "Base listing") for index, text in enumerate(listing_rows)]
    header = data.get("zone_header", [])
    if not isinstance(header, list) or len(header) > 32 or not all(isinstance(h, str) and re.fullmatch(r">[A-Za-z0-9_.@]+,[A-Za-z0-9_.-]{0,64}", h) for h in header):
        raise Failure(INPUT_INVALID, "zone_header is a list of at most 32 linker metadata lines such as >level.ipak_read,common_zm", field='/zone_header')
    return {"name": name, "title": title, "tags": list(tags), "game": game, "base": base, "map": map_id, "members": members,
            "origin": _at("/origin", _origin, data.get("origin"), name), "donor": _at("/donor", _donor, data.get("donor"), name),
            "zone_header": list(header), "loads": loads, "budget": _at("/budget", _contract, data["budget"], "budget") if "budget" in data else None,
            "decisions": _at("/decisions", _decisions, data.get("decisions"), name), "base_owned": base_owned}


def load_composition(path: Path, job: Job, depth: int = 0, seen: tuple = ()) -> dict:
    src = job.input(path, limit=256 * 1024)
    key = str(src.resolve())
    if key in seen:
        raise Failure(INPUT_INVALID, f"Compositions include each other in a cycle: {src.name}")
    if depth > MAX_NESTING:
        raise Failure(INPUT_LIMIT, f"Compositions nest at most {MAX_NESTING} deep")
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise Failure(INPUT_INVALID, f"Composition is not valid JSON: {src}") from exc
    comp = validate_composition_metadata(data)
    game, base, map_id = comp["game"], comp["base"], comp["map"]
    directories: list[Path] = []
    members = []
    for row in comp["members"]:
        role = row["role"]
        directory = _relative_dir(row["path"], src.parent, job, "Member")
        if directory in directories:
            raise Failure(INPUT_INVALID, f"Member directory listed twice: {row['path']}")
        directories.append(directory)
        nested = directory / "composition.json"
        if (directory / "module.json").is_file():
            member = {"kind": "module", "directory": directory, "role": role, "path": row["path"],
                      "reference": {"name": row["name"], "commit": row["commit"]} if row["name"] is not None else None}
        elif nested.is_file() and not nested.is_symlink():
            inner = load_composition(nested, job, depth + 1, seen + (key,))
            if inner["game"] != game:
                raise Failure(INPUT_INVALID, f"Nested composition {inner['name']} is for game {inner['game']!r}, not {game!r}")
            if inner["base"] != base:
                raise Failure(INPUT_INVALID, f"Nested composition {inner['name']} is for base {inner['base']!r}, not {base!r}")
            if inner["map"] != map_id:
                raise Failure(INPUT_INVALID, f"Nested composition {inner['name']} is for map {inner['map']!r}, not {map_id!r}")
            member = {"kind": "composition", "directory": directory, "role": role, "path": row["path"], "composition": inner,
                      "reference": {"name": row["name"], "commit": row["commit"]} if row["name"] is not None else None}
        else:
            raise Failure(INPUT_MISSING, f"Member directory has neither module.json nor composition.json: {row['path']}")
        members.append(member)
    loads = [_relative_file(text, src.parent, job, "Load") for text in comp["loads"]]
    base_owned = _base_owned([_relative_file(text, src.parent, job, "Base listing") for text in comp["base_owned"]])
    return comp | {"members": members, "loads": loads, "base_owned": base_owned, "source": src}


def flatten(comp: dict, job: Job) -> tuple[list[dict], list[Path], list[dict], list[str]]:
    """Every module in this composition and its nested compositions, with the loads and
    decisions gathered along the way. A nested composition's decisions apply to its own
    collisions; the outer recipe records the ones between its members."""
    modules: list[dict] = []
    loads: list[Path] = list(comp["loads"])
    decisions: list[dict] = list(comp["decisions"])
    comp.setdefault("base_owned", set())
    header: list[str] = list(comp["zone_header"])
    for member in comp["members"]:
        if member["kind"] == "module":
            declaration = load_declaration(member["directory"], job)
            declaration["role"] = member["role"]
            declaration["reference"] = member["reference"]
            declaration["via"] = comp["name"]
            modules.append(declaration)
        else:
            inner_modules, inner_loads, inner_decisions, inner_header = flatten(member["composition"], job)
            header += [h for h in inner_header if h not in header]
            for declaration in inner_modules:
                if member["role"] == "base":
                    declaration["role"] = "base"
                modules.append(declaration)
            loads += [p for p in inner_loads if p not in loads]
            decisions += inner_decisions
            comp["base_owned"] |= member["composition"].get("base_owned", set())
    return modules, loads, decisions, header


def _order(modules: list[dict]) -> list[str]:
    """Dependency order (a module after everything it depends on); refuses cycles. Base-role
    members sort first among equals so the base's assets are staged before attachments."""
    pending = {m["id"]: set(m["dependencies"]) for m in modules}
    rank = {m["id"]: 0 if m.get("role") == "base" else 1 for m in modules}
    order: list[str] = []
    while pending:
        ready = sorted((mid for mid, deps in pending.items() if not deps - set(order)), key=lambda mid: (rank[mid], mid))
        if not ready:
            raise Failure(INPUT_INVALID, f"Dependency cycle among modules: {sorted(pending)}")
        for mid in ready:
            order.append(mid)
            del pending[mid]
    return order


def resolve(comp: dict, modules: list[dict]) -> dict:
    ids = [m["id"] for m in modules]
    if len(set(ids)) != len(ids):
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        raise Failure(INPUT_INVALID, f"Two members declare the same id: {duplicates}",
                      "A module appears once in a pack, including through nested compositions.")
    known = set(ids)
    for m in modules:
        for dep in m["dependencies"]:
            if dep not in known:
                raise Failure(INPUT_INVALID, f"{m['id']} depends on {dep}, which is not in the composition",
                              "Add the module directory that declares that id to the composition's modules list.")
        for other in m["conflicts"]:
            if other in known:
                raise Failure(INPUT_INVALID, f"{m['id']} declares a conflict with {other}; both are in the composition")
        if comp["base"] not in m["bases"]:
            raise Failure(INPUT_INVALID, f"{m['id']} is declared for bases {m['bases']}, not for {comp['base']!r}",
                          "Build the module on a base it declares, or extend its declaration after testing it there.")
        if "*" not in m["maps"] and comp["map"] not in m["maps"]:
            raise Failure(INPUT_INVALID, f"{m['id']} is declared for maps {m['maps']}, not for {comp['map']!r}",
                          "Qualify the module on that map first (build alone, load, play, record the verdict), then extend maps.")
        if m["seed"] and m["seed"].get("private"):
            raise Failure(INPUT_MISSING, f"{m['id']} is distribution private and its seed package is not on this machine (missing: {m['seed'].get('missing')})",
                          "Others can read what a private module provides from its manifest; building a pack with it needs the package beside the manifest.")
    order = _order(modules)
    totals = {field: sum(m["resource_contract"][field] for m in modules) for field in CONTRACT_FIELDS}
    if comp["budget"] is not None:
        for field in CONTRACT_FIELDS:
            if totals[field] > comp["budget"][field]:
                raise Failure(INPUT_LIMIT, f"Resource budget exceeded: {field} {totals[field]} > {comp['budget'][field]}",
                              "Raise the budget deliberately after measuring, or leave a module out; the sum counts every module.")
    return {"order": order, "resource_totals": totals}


def collisions(modules: list[dict], loaded: dict[str, tuple], decisions: list[dict], base_owned: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    """Every place two modules would own the same thing, as decisions. Identical bytes for the
    same file dedupe with no decision; a name the base zones already carry (``base_owned``,
    from the composition's base listings) is the base's and resolves with no decision; anything
    else needs an owner recorded in the recipe. Returns (decided, undecided)."""
    base_owned = base_owned or set()
    file_owners: dict[str, list[tuple[str, str]]] = {}
    for m in modules:
        if m["recipe"] is not None:
            _, compiled, loose, _ = loaded[m["id"]]
            for source, target, _ in compiled:
                file_owners.setdefault(target.as_posix().casefold(), []).append((m["id"], sha256_file(source)))
            for source, target, _, _ in loose:
                file_owners.setdefault(target.as_posix().casefold(), []).append((m["id"], sha256_file(source)))
        elif m["seed"] and not m["seed"].get("private"):
            for row in m["seed"]["embedded"]:
                kind, name = row.split(",", 1)
                if kind == "rawfile":
                    file_owners.setdefault(name.casefold(), []).append((m["id"], "seed:" + m["seed"]["files"]["mod.ff"].name))
    name_owners: dict[str, list[str]] = {}
    for m in modules:
        for pkind, names in m["provides"].items():
            if pkind == "rawfiles":
                # A provided rawfile is a file target: the file collision above already lists it (for a
                # seed, from its manifest's embedded rows) and the build resolves that one record.
                continue
            for name in names:
                name_owners.setdefault(f"{pkind}:{name}", []).append(m["id"])
        if m["seed"] and not m["seed"].get("private"):
            for row in m["seed"]["embedded"]:
                kind, name = row.split(",", 1)
                if kind in ("weapon", "soundbank", "xmodel", "xanim", "material", "fx", "image"):
                    name_owners.setdefault(f"asset:{row}", []).append(m["id"])
    recorded = {d["collision"].casefold(): d for d in decisions}
    decided, undecided = [], []
    for target, owners in sorted(file_owners.items()):
        if len(owners) < 2:
            continue
        ids = [o for o, _ in owners]
        digests = {d for _, d in owners}
        if len(digests) == 1 and not any(d.startswith("seed:") for d in digests):
            decided.append({"collision": target, "kind": "file", "modules": ids, "resolution": "identical bytes; one copy is packed", "owner": ids[0]})
            continue
        decision = recorded.get(target)
        row = {"collision": target, "kind": "file", "modules": ids}
        if decision and decision["owner"] in ids:
            decided.append({**row, "resolution": "recorded decision", "owner": decision["owner"], "reason": decision["reason"]})
        elif decision:
            raise Failure(INPUT_INVALID, f"Decision for {target} names {decision['owner']}, which is not one of {ids}")
        else:
            undecided.append({**row, "resolution": "undecided", "choices": ids,
                              "how": "record {\"collision\": \"" + target + "\", \"owner\": \"<one of the modules>\", \"reason\": \"...\"} under decisions in the composition, or rename the target in one module"})
    for key, ids in sorted(name_owners.items()):
        if len(ids) < 2:
            continue
        decision = recorded.get(key.casefold())
        row = {"collision": key, "kind": "name", "modules": ids}
        # Only a seed's embedded ``asset:`` rows can be base-owned: those are copies the linker
        # took from the base. A ``provides`` registration (weapons, models, effects, soundbanks)
        # is a module's own claim and stays a decision even when the base carries the name.
        if key.startswith("asset:") and key[6:].casefold() in base_owned and not decision:
            decided.append({**row, "resolution": "base-owned; the base zone's copy is loaded", "owner": ids[0]})
            continue
        if decision and decision["owner"] in ids:
            decided.append({**row, "resolution": "recorded decision", "owner": decision["owner"], "reason": decision["reason"]})
        elif decision:
            raise Failure(INPUT_INVALID, f"Decision for {key} names {decision['owner']}, which is not one of {ids}")
        else:
            undecided.append({**row, "resolution": "undecided", "choices": ids,
                              "how": "two modules register the same " + key.split(":", 1)[0] + "; keep one, or record an owner under decisions and drop the other's registration"})
    return decided, undecided


def _backends(compiled: list) -> list[dict]:
    checks = []
    for name in (["gsc"] if compiled else []) + ["linker", "unlinker"]:
        try:
            checks.append({"id": name, "argv": executable(name), "available": True})
        except Failure as exc:
            checks.append({"id": name, "available": False, "message": exc.message})
    return checks


def _plan_rows(modules: list[dict], order: list[str], job: Job) -> list[dict]:
    by_id = {m["id"]: m for m in modules}
    rows = []
    for mid in order:
        m = by_id[mid]
        row = {"id": mid, "version": m["version"], "title": m["title"], "category": m["category"], "kind": m["kind"],
               "tags": m["tags"], "role": m.get("role", "module"), "via": m.get("via"), "directory": str(m["directory"]),
               "declaration_sha256": job.inputs[str(m["declaration"])], "payload": "seed" if m["seed"] else "recipe",
               "distribution": m["distribution"], "dependencies": m["dependencies"], "conflicts": m["conflicts"],
               "bases": m["bases"], "maps": m["maps"], "provides": m["provides"], "resource_contract": m["resource_contract"],
               "menu_route": m["menu_route"], "source": m["source"], "reference": m.get("reference"),
               "origin": m["origin"], "donor": m["donor"]}
        if m["recipe"] is not None:
            row["recipe_sha256"] = job.inputs[str(m["recipe"].resolve())]
        else:
            row["seed_sha256"] = m["seed"]["files"]["mod.ff"] and job.inputs[str(m["seed"]["package"].resolve())]
            row["seed_manifest_sha256"] = job.inputs[str(m["seed"]["manifest"])]
            row["seed_roots"] = len(m["seed"]["roots"])
        rows.append(row)
    return rows


def execute(args, job: Job) -> dict:
    if args.action == "fetch":
        from . import registry

        return registry.fetch(args, job)
    if args.action == "declare":
        return seeds.declare(Path(args.package).expanduser(), args, job)
    comp = load_composition(Path(args.composition), job)
    modules, loads, decisions, header = flatten(comp, job)
    mixed = sorted({m["id"] for m in modules if m.get("game", titles.DEFAULT_TITLE) != comp["game"]})
    if mixed:
        raise Failure(INPUT_INVALID, f"Composition targets game {comp['game']} but these members target another game: {mixed}",
                      "Every module in a composition targets the same game; split the pack or fix the members' module.json game.")
    resolved = resolve(comp, modules)
    loaded = {m["id"]: projects.load_recipe(m["recipe"], job) for m in modules if m["recipe"] is not None}
    by_id = {m["id"]: m for m in modules}
    compiled, loose = [], []
    for mid in resolved["order"]:
        if mid in loaded:
            _, c, l, extra_loads = loaded[mid]
            compiled += c
            loose += l
            loads += [p for p in extra_loads if p not in loads]
    seed_modules = [by_id[mid] for mid in resolved["order"] if by_id[mid]["seed"]]
    if len(compiled) > projects.MAX_SCRIPTS or len(loose) > projects.MAX_ASSETS or len(loads) > projects.MAX_LOADS or len(seed_modules) > MAX_MODULES:
        raise Failure(INPUT_LIMIT, f"A composition holds at most {projects.MAX_SCRIPTS} scripts, {projects.MAX_ASSETS} assets, {projects.MAX_LOADS} loads and {MAX_MODULES} seeds")
    decided, undecided = collisions(modules, loaded, decisions, comp.get("base_owned"))
    checks = _backends(compiled)
    rows = _plan_rows(modules, resolved["order"], job)
    base_ids = [r["id"] for r in rows if r["role"] == "base"]
    plan = {
        "schema_version": 1, "name": comp["name"], "title": comp["title"], "tags": comp["tags"], "base": comp["base"],
        "map": comp["map"], "origin": comp["origin"], "donor": comp["donor"],
        "game": comp["game"], "mode": titles.zone(comp["game"])["mode"],
        "base_member": base_ids[0] if base_ids else None,
        "modules": rows, "order": resolved["order"],
        "scripts": [{"source": str(p), "target": t.as_posix(), "instance": i} for p, t, i in compiled],
        "assets": [{"source": str(p), "target": t.as_posix(), "type": k, "name": n} for p, t, k, n in loose],
        "seeds": [{"id": m["id"], "package": str(m["seed"]["package"]), "roots": m["seed"]["roots"],
                   "soundbanks": [n for n in m["seed"]["files"] if n != "mod.ff"],
                   "strings": str(m["seed"]["strings"]) if m["seed"].get("strings") else None} for m in seed_modules],
        "loads": [str(p) for p in loads], "zone_header": header,
        "resource_totals": resolved["resource_totals"], "budget": comp["budget"],
        "decisions": decided, "undecided": undecided, "base_owned_names": len(comp.get("base_owned") or ()),
        "backends": checks, "backends_available": all(c["available"] for c in checks),
        "input_files": len(job.inputs),
        "verification": "composition resolved (dependency order, conflicts, base and map fit, budget); collisions listed as decisions; "
                        "declarations, recipes, seeds and declared inputs hashed; backend presence checked; nothing compiled",
    }
    (job.root / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    summary = {"plan": "plan.json", "name": comp["name"], "title": comp["title"], "base": comp["base"], "map": comp["map"],
               "base_member": plan["base_member"],
               "modules": [{"id": r["id"], "version": r["version"], "order": i + 1, "payload": r["payload"], "role": r["role"]}
                           for i, r in enumerate(rows)],
               "resource_totals": resolved["resource_totals"], "budget": comp["budget"],
               "scripts": len(compiled), "assets": len(loose), "seeds": len(seed_modules), "loads": len(loads),
               "decisions": decided, "undecided": undecided, "base_owned_names": len(comp.get("base_owned") or ())}
    if args.action == "plan":
        return {**summary, "backends": checks, "backends_available": plan["backends_available"],
                "input_files": plan["input_files"], "verification": plan["verification"]}
    if undecided:
        raise Failure(INPUT_INVALID, f"{len(undecided)} collision(s) have no recorded decision; nothing was built",
                      "Read plan.json's undecided list, record an owner for each under decisions in the composition (or rename a target), then build.",
                      undecided=undecided)
    return _build_composition(comp, plan, compiled, loose, seed_modules, loads, decided, header, args, job)


def _build_composition(comp: dict, plan: dict, compiled, loose, seed_modules, loads, decided, header, args, job: Job) -> dict:
    base_owned_names = len(comp.get("base_owned") or ())
    missing = [c["id"] for c in plan["backends"] if not c["available"]]
    if missing:
        raise Failure("backend_unavailable", f"Required backends are not installed: {missing}", "Run: pat dev setup")
    # Decided file collisions: only the owner's copy is staged.
    losers = {(d["collision"], mid) for d in decided if d["kind"] == "file" for mid in d["modules"] if mid != d["owner"]}
    owner_of = {d["collision"]: d["owner"] for d in decided if d["kind"] == "file"}
    game = comp["game"]
    zone = titles.zone(game)
    zone_name = zone["name"]
    base = job.root / "project"
    raw, zone_dir = base / "raw", base / "zone_source"
    raw.mkdir(parents=True)
    zone_dir.mkdir()
    lines = [f"> game,{zone['game_token']}", f"> name,{zone_name}", *header]
    rawfiles = []
    staged_targets: set[str] = set()
    module_of_source = {}
    for m in plan["modules"]:
        module_of_source[m["id"]] = m["directory"]
    def owner_for(target: str, source: Path) -> str | None:
        for m in plan["modules"]:
            if str(source).startswith(m["directory"]):
                return m["id"]
        return None
    for index, (source, target, instance) in enumerate(compiled):
        key = target.as_posix().casefold()
        mid = owner_for(target.as_posix(), source)
        if key in owner_of and owner_of[key] != mid:
            continue
        if key in staged_targets:
            continue
        action = "compile" if titles.script_form(game) == "compiled" else "check"
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
        staged_targets.add(key)
    for source, target, asset_type, name in loose:
        key = target.as_posix().casefold()
        mid = owner_for(target.as_posix(), source)
        if key in owner_of and owner_of[key] != mid:
            continue
        if key in staged_targets:
            continue
        dest = raw / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        lines.append(f"{asset_type},{name}")
        if asset_type == "rawfile":
            rawfiles.append(target)
        staged_targets.add(key)
    seed_loads = []
    banks = job.root / "packages"
    strings: dict[str, str] = {}
    for m in seed_modules:
        seed_loads.append(m["seed"]["package"])
        for root in m["seed"]["roots"]:
            if root not in lines:
                lines.append(root)
        if m["seed"].get("strings"):
            rows = seeds.parse_strings(m["seed"]["strings"].read_text(encoding="utf-8", errors="replace"), m["id"])
            for key, value in rows.items():
                if key in strings and strings[key] != value:
                    raise Failure(INPUT_INVALID, f"Two seeds define the localized string {key} differently; record which module owns it",
                                  "Rename the string in one module, or drop one module from the pack.")
                strings[key] = value
    if strings:
        (raw / zone["language"] / "localizedstrings").mkdir(parents=True, exist_ok=True)
        (raw / zone["language"] / "localizedstrings" / f"{zone_name}.str").write_text(seeds.write_strings(strings), encoding="utf-8")
        lines.insert(2 + len(header), f"localize,{zone_name}")
    (zone_dir / f"{zone_name}.zone").write_text("\n".join(lines) + "\n", encoding="utf-8")
    link = fastfiles.execute(SimpleNamespace(action="link", project=str(base), zone=zone_name,
                                             load=[str(p) for p in seed_loads] + [str(p) for p in loads],
                                             assets=[], timeout=args.timeout), job)
    if len(link["packages"]) != 1:
        raise Failure(BACKEND_FAILED, "A composition must produce exactly one fastfile")
    package = job.root / link["packages"][0]["path"]
    # The seeds' soundbanks travel beside the package: the engine reads them from the profile folder.
    for m in seed_modules:
        for name, path in m["seed"]["files"].items():
            if name == "mod.ff":
                continue
            dest = banks / name
            if dest.exists():
                raise Failure(INPUT_INVALID, f"Two seeds ship the soundbank {name}; a pack carries one copy of each bank")
            shutil.copyfile(path, dest)
    readback_log = job.run([*executable("unlinker"), "--no-color", "--include-assets", "rawfile", "--output-folder",
                            str(job.root / "readback"), str(package)], timeout=args.timeout)
    fastfiles.check_readback_log(readback_log)
    for rel in rawfiles:
        restored = job.root / "readback" / rel
        if not restored.is_file() or sha256_file(raw / rel) != sha256_file(restored):
            raise Failure(BACKEND_FAILED, f"Rawfile did not round-trip through the fastfile: {rel.as_posix()}")
    # Every seed root must be in the composed package: the linker copies roots out of loaded seeds.
    listing_log = job.run([*executable("unlinker"), "--no-color", "--skip-obj", "--list", str(package)], timeout=args.timeout)
    fastfiles.check_readback_log(listing_log)
    embedded, referenced = seeds.parse_listing(listing_log.read_text(encoding="utf-8", errors="replace"))
    missing_roots = [root for m in seed_modules for root in m["seed"]["roots"] if root not in embedded]
    if missing_roots:
        raise Failure(BACKEND_FAILED, f"{len(missing_roots)} seed root(s) are not in the composed package: {missing_roots[:5]}",
                      "The linker did not copy them from the seed; check the loads and the seed manifest.", missing=missing_roots[:64])
    return {**link, "plan": "plan.json", "rawfiles_verified": len(rawfiles), "mod_ff": link["packages"][0]["path"],
            "seed_roots_verified": sum(len(m["seed"]["roots"]) for m in seed_modules),
            "embedded_assets": len(embedded), "referenced_assets": len(referenced), "localized_strings": len(strings),
            "soundbanks": sorted(p.name for p in banks.iterdir() if p.is_file() and p.name != "mod.ff"),
            "name": comp["name"], "title": comp["title"], "base": comp["base"], "map": comp["map"], "base_member": plan["base_member"],
            "modules": [{"id": r["id"], "version": r["version"], "order": i + 1, "payload": r["payload"], "role": r["role"]}
                        for i, r in enumerate(plan["modules"])],
            "resource_totals": plan["resource_totals"], "budget": plan["budget"], "decisions": decided, "base_owned_names": base_owned_names,
            "scripts": len(compiled), "assets": len(loose), "seeds": len(seed_modules), "loads": len(loads),
            "install_hint": f"pat game install-mod <output>/{link['packages'][0]['path']} {comp['name']}  (copy the soundbanks under packages/ beside it; loading in game is a separate, authorized step)",
            "verification": "every recipe module's scripts compiled, one mod.ff linked against every seed and load, read back, every rawfile "
                            "byte-compared and every seed root found in the package; fit, budget and decisions come from declarations, not from the game"}
