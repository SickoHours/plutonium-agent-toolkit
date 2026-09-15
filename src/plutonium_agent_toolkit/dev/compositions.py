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

from ..core.errors import BACKEND_FAILED, INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING, INVALID_ARGUMENTS, Failure
from ..core.jobs import Job
from ..core.receipts import FILE_FLAGS, sha256_file
from . import fastfiles, parameters, projects, scripts, seeds, titles
from .backends import executable

ID = re.compile(r"^[a-z0-9_]{1,64}\Z")
BASE = re.compile(r"^[a-z0-9]{1,16}\Z")
MAP = re.compile(r"^[a-z0-9_]{1,64}\Z")
VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,31}\Z")
CATEGORY = re.compile(r"^[a-z][a-z0-9-]{0,31}\Z")
TAG = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}\Z")
COMMIT = re.compile(r"^[0-9a-f]{40}\Z")
NAME_REF = re.compile(r"^[a-z0-9][a-z0-9-]{0,38}/[a-z0-9_]{1,64}\Z")
# A `recipes` key is one target: the foundation id as `foundations/<id>.json` names it, then the map.
RECIPE_TARGET = re.compile(r"^[a-z0-9-]{1,32}/zm_[a-z0-9_]{1,32}\Z")
MAX_RECIPES = 32
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
                  "rawfiles", "aliases")
# Zone paths that belong to the map, never to one member: a per-map animation state table, its
# animation tree and the AI type scripts that read them. Two members that each ship their own
# copy are not asking for an owner; the game needs one merged copy, a service module.
MAP_OWNED_PREFIXES = ("animstatedefs/", "animtrees/", "aitype/")
MAX_SHELF_ENTRIES = 4096
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
    q = actions.add_parser("state", help="Derive composition evidence state from current hashes, or read a module's evidence ledger per fact and scope")
    g = q.add_mutually_exclusive_group(required=True)
    g.add_argument("--composition", help="Composition directory (or composition.json) whose plan and receipts are checked by hash")
    g.add_argument("--ledger", help="A module directory or its evidence.json; reports the six facts per scope from ledger rows, unknown kept unknown")
    for name in ("plan","verify","test-plan","run","verdict"):
        q.add_argument("--"+name)
    q.add_argument("--base", help="With --ledger: the base token to query"); q.add_argument("--foundation", help="With --ledger: the foundation id to query")
    q.add_argument("--map", help="With --ledger: the map id to query"); q.add_argument("--package", help="With --ledger: a package sha256 to query")
    q.add_argument("--location", help="With --ledger: a survival location inside --map; without it only rows with no location match")
    q.add_argument("--target", help="With --ledger: a target key <foundation>/<map>/<mode>[/<location>] supplying foundation, map and location at once")
    q.add_argument("--json",action="store_true")
    q = actions.add_parser("ledger-from-registry", help="Propose evidence.json rows for one workspace module from the registry and its docs; prints them, writes nothing")
    q.add_argument("workspace", help="Workspace root holding modules/, registry/t6-modules.json and foundations/")
    q.add_argument("module_id", help="Directory name under modules/")
    q.add_argument("--dry-run", action="store_true", default=True, help="Always on: the proposal is printed, never written")
    q.add_argument("--json", action="store_true")
    q = actions.add_parser("inspect", help="Validate one declaration's metadata without resolving payloads or creating a job")
    q.add_argument("declaration", help="Path to module.json or composition.json")
    q.add_argument("--json", action="store_true")
    for action, help_text in (("plan", "Resolve a composition, list collisions as decisions and hash its inputs; runs no backend"),
                              ("build", "Compile, link against seeds and loads, read back and compare every module into one mod.ff")):
        q = actions.add_parser(action, help=help_text)
        q.add_argument("composition", help="Path to composition.json")
        q.add_argument("--allow-unqualified", action="store_true", help="Report base/map mismatches without refusing; does not add evidence")
        q.add_argument("--workspace", help="Workspace root whose registry/locations tables answer the members' placements needs (docs/target-sets.md)")
        q.add_argument("--target", action="append", default=[], metavar="KEY",
                       help="A target <foundation>/<map>/<mode>[/<location>][@<route>] to check placements against; repeatable. Its map must be the composition's, and a location two routes provide names one")
        q.add_argument("--image-report", metavar="PATH",
                       help="A readback measurement of which of this pack's images have no pixels in any bank the client opens (docs/MODULES.md); without it the image-sources check cannot decide a referenced image and says so")
        common(q)
    from . import qualify as qualify_route
    qualify_route.add_parser(actions, common)
    q = actions.add_parser("compose", help="Compose declared IDs against a foundation, or publish a successfully built recipe")
    q.add_argument("--name"); q.add_argument("--base"); q.add_argument("--map")
    q.add_argument("--game", choices=titles.names(), default=None, help="Title the recipe targets; inferred from the members when omitted")
    q.add_argument("--foundation")
    q.add_argument("--member-root", action="append", default=[])
    q.add_argument("--module", action="append", default=[])
    q.add_argument("--publish-to"); q.add_argument("--from-build"); q.add_argument("--composition")
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
                          "dependencies", "conflicts", "origin", "donor", "distribution", "menu_route", "payload", "recipes",
                          "lineage", "replaces", "entry", "placements", "parameters")
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
        result.update(validation="metadata-valid", metadata={key: metadata[key] for key in fields if key not in ("replaces","entry","placements","parameters","recipes") or key in data})
        if kind == "module" and "recipes" in data:
            # The targets the module names a cut for, not the paths: inspection resolves no payload.
            result["metadata"]["recipes"] = sorted(metadata["recipes"])
        if kind == "module":
            ledger_path = path.parent / "evidence.json"
            if ledger_path.exists() or ledger_path.is_symlink():
                # The ledger beside the declaration is read when present. Its defects are
                # diagnostics on the ledger summary, never on the declaration: a malformed
                # ledger leaves the declaration metadata-valid and the exit status 0.
                from . import ledger
                result["ledger"] = ledger.inspect(ledger_path, metadata["id"])
        if kind == "module" and metadata.get("tests"):
            from .testing_contracts import load_contract, requires_probe
            # A module is inspected alone; whether a probe member exists is a composition fact.
            # Validate the structure with probe scope and report the requirement; the planner
            # and the release-profile rule enforce it where the composition is known.
            contract = load_contract(path.parent, metadata, probe=True)
            result["metadata"]["tests"] = {"sha256": contract["sha256"], "steps": len(contract["steps"]),
                                           "human_steps": len(contract["human_only"]), "maps": list(contract["maps"]),
                                           "requires_probe": requires_probe(contract)}
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


def validate_lineage(value):
    if value is None:
        return None
    rows = [value] if isinstance(value, dict) else value
    if not isinstance(rows, list) or not 1 <= len(rows) <= 18:
        raise Failure(INPUT_INVALID, "lineage is one entry or 1 to 18 same-map source entries", field="/lineage")
    result = []
    for row in rows:
        _fields(row, {"game", "map", "source", "note"}, {"game", "map", "source"}, "lineage")
        if row["game"] not in ("t4", "t5") or not isinstance(row["map"], str) or not re.fullmatch(r"zm_[a-z0-9_]{1,60}", row["map"]):
            raise Failure(INPUT_INVALID, "lineage requires a T4/T5 game and a zm_ map ID", field="/lineage")
        if not isinstance(row["source"], str) or not row["source"].strip() or len(row["source"]) > 2048:
            raise Failure(INPUT_INVALID, "lineage source must be non-empty and at most 2048 characters", field="/lineage")
        note = row.get("note", "")
        if not isinstance(note, str) or len(note) > 400:
            raise Failure(INPUT_INVALID, "lineage note is at most 400 characters", field="/lineage")
        result.append(dict(row, note=note))
    return result


FUNCTION = re.compile(r'^[a-z0-9_/]+::[a-z0-9_]+$')

def mask_gsc(text):
    """Blank comments and quoted literals so a lexical scan sees only executable GSC.

    Same length, newlines kept, so callers that anchor on line starts still see the code
    lines. ``replaceFunc`` prose in a comment or a string, and ``main``/``init`` in a comment,
    are not code and must not be read as one.
    """
    chars=list(text);index=0;length=len(text)
    while index<length:
        char=text[index]
        if char=='/' and index+1<length and text[index+1]=='/':
            chars[index]=chars[index+1]=' ';index+=2
            while index<length and text[index]!='\n':chars[index]=' ';index+=1
        elif char=='/' and index+1<length and text[index+1]=='*':
            chars[index]=chars[index+1]=' ';index+=2
            while index<length and not (text[index]=='*' and index+1<length and text[index+1]=='/'):
                if text[index]!='\n':chars[index]=' '
                index+=1
            if index<length:
                chars[index]=' '
                if index+1<length:chars[index+1]=' '
                index+=2
        elif char in ('"',"'"):
            quote=char;chars[index]=' ';index+=1
            while index<length and text[index]!=quote:
                if text[index]=='\\' and index+1<length:
                    chars[index]=chars[index+1]=' ';index+=2;continue
                if text[index]!='\n':chars[index]=' '
                index+=1
            if index<length:chars[index]=' ';index+=1
        else:
            index+=1
    return ''.join(chars)


def scan_replacements(text):
    pattern=re.compile(r"(?<![\w])replacefunc\s*\(\s*([A-Za-z0-9_\\/]+)::([A-Za-z0-9_]+)",re.I)
    return {path.replace(chr(92),'/').lower()+'::'+name.lower() for path,name in pattern.findall(mask_gsc(text))}

def replacement_warnings(modules,loaded):
    warnings=[]
    for i,m in enumerate(modules):
        found=set()
        if m['id'] in loaded:
            for source,_,_ in loaded[m['id']][1]:
                text=mask_gsc(source.read_text(encoding='utf-8'))
                if m.get('entry') and re.search(r'(?im)^\s*(?:main|init)\s*\([^)]*\)\s*\{',text):
                    raise Failure(INPUT_INVALID,'An entry-managed module cannot define main or init',field=f'/modules/{i}/entry')
                found.update(scan_replacements(text))
        declared=set(m.get('replaces',{}).get('functions',[]))
        missing=found-declared
        if missing:
            raise Failure('declaration_mismatch','Source has undeclared function replacements',
                          'Declare these targets: '+', '.join(sorted(missing)),field=f'/modules/{i}/replaces/functions')
        for target in sorted(declared-found):warnings.append({'module':m['id'],'target':target,'message':'Declared replacement not found in available script source'})
    return warnings


def _placements(value, mid):
    """What a module needs placed on each target (a perk machine, a wall buy, ...), never
    where; ``docs/target-sets.md``. Absent is not an error and adds nothing."""
    from .targets import validate_placements
    return validate_placements(value, mid)


def _function(value):
    if not isinstance(value,str) or len(value)>256 or not FUNCTION.fullmatch(value.lower()):
        raise Failure(INPUT_INVALID,'Expected script/path::function')
    return value.lower()

def _replaces(value):
    if value is None:return {'functions':[],'files':[]}
    _fields(value,{'functions','files'},{'functions','files'},'replaces')
    out={}
    for key,maximum in (('functions',256),('files',64)):
        rows=value[key]
        if not isinstance(rows,list) or len(rows)>maximum:raise Failure(INPUT_INVALID,'Too many replacement targets',field='/'+key)
        normalized=[]
        for i,v in enumerate(rows):
            field=f'/{key}/{i}'
            if key=='functions':
                v=_at(field,_function,v);path,fn=v.split('::')
                if fn.startswith('codecallback_') or fn=='gamemode_callback_setup' or fn=='main' and (path.startswith('maps/mp/zm_') or '/gametypes' in path):
                    raise Failure(INPUT_INVALID,'Cannot replace a base-owned entry point','This engine entry point is base-owned; use foundation work.',field=field)
            else:
                _at(field,_text,v,'script path',256);v=v.lower();_at(field,_recipe_path,v)
                if not v.endswith(('.gsc','.csc')):raise Failure(INPUT_INVALID,'Replaced files must be scripts',field=field)
            if v not in normalized:normalized.append(v)
        out[key]=normalized
    return out

def _recipes(value, mid: str) -> dict[str, str]:
    """The per-target adapter recipes a declaration names: ``<foundation>/<map>`` to a recipe path
    relative to the module directory. Lexical only; that each file exists, parses as an adapter
    recipe and was cut for its own key is checked where the directory is known (``load_declaration``)."""
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > MAX_RECIPES:
        raise Failure(INPUT_INVALID, f"{mid}: recipes maps at most {MAX_RECIPES} '<foundation>/<map>' targets to recipe paths", field='/recipes')
    out: dict[str, str] = {}
    for key, path in value.items():
        if not isinstance(key, str) or not RECIPE_TARGET.match(key):
            raise Failure(INPUT_INVALID, f"{mid}: a recipes key is '<foundation>/<map>', the foundation id as foundations/<id>.json names it: {key!r}",
                          field='/recipes' + _pointer(key))
        field = "/recipes" + _pointer(key)
        _at(field, _text, path, f"{mid}: recipes[{key}]", 4096)
        _at(field, _recipe_path, path)
        out[key] = path
    return out


def _entry(value):
    if value is None:return None
    _fields(value,{'replace','register'},{'replace','register'},'entry')
    return {k:_at('/'+k,_function,v) for k,v in value.items()}


def validate_declaration_metadata(data, *, where: str = "module.json") -> dict:
    """Authoritative declaration checks; no filesystem or payload resolution."""
    _fields(data, {"schema", "id", "version", "game", "title", "category", "kind", "tags", "recipe", "recipes", "seed", "bases", "maps",
                            "dependencies", "conflicts", "provides", "resource_contract", "menu_route", "distribution", "source",
                            "origin", "donor", "lineage", "tests", "replaces", "entry", "placements", "parameters"},
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
    recipes = _recipes(data.get("recipes"), mid)
    if recipes and payload != "recipe":
        raise Failure(INPUT_INVALID, f"{mid}: recipes belongs to a recipe payload; a seed is one package, not a cut per target", field='/recipes')
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
    tests = data.get("tests")
    if tests is not None:
        _at("/tests", _text, tests, "tests", 4096)
        _at("/tests", _recipe_path, tests)
    provides = _at("/provides", _provides, data.get("provides"), mid)
    return {"id": mid, "version": data["version"], "game": game, "title": title, "category": category, "kind": kind, "tags": list(tags),
            "payload": payload, "payload_path": payload_path, "recipes": recipes, "distribution": distribution, "tests": tests,
            "replaces":_at("/replaces",_replaces,data.get("replaces")), "entry":_at("/entry",_entry,data.get("entry")),
            "placements": _placements(data.get("placements"), mid),
            "parameters": parameters.validate_declared(data.get("parameters"), mid),
            "bases": list(bases), "maps": list(maps),
            "dependencies": _at("/dependencies", _ids, data.get("dependencies", []), "dependencies", mid),
            "conflicts": _at("/conflicts", _ids, data.get("conflicts", []), "conflicts", mid),
            "provides": provides,
            "resource_contract": _at("/resource_contract", _contract, data.get("resource_contract"), f"{mid}: resource_contract"),
            "menu_route": menu_route, "source": source,
            "lineage": validate_lineage(data.get("lineage")),
            "origin": _at("/origin", _origin, data.get("origin"), mid), "donor": _at("/donor", _donor, data.get("donor"), mid)}


def _recipe_for_target(declaration: dict, directory: Path, job: Job, target: tuple[str | None, str | None] | None) -> tuple[Path, str | None]:
    """The recipe a composition on ``target`` builds this adapter from, and the ``recipes`` key
    it came from (``None`` for the default). An adapter recipe is a cut for one foundation and
    one map, so a module composed on another target needs the cut for it; ``recipes`` names one
    per target and ``recipe`` stays the default. Every entry is validated here, not only the
    chosen one: a key whose file was cut for another target is a declaration defect wherever the
    pack is aimed."""
    from . import adapters

    chosen_key = None
    foundation, map_id = target or (None, None)
    if foundation and map_id and f"{foundation}/{map_id}" in declaration["recipes"]:
        chosen_key = f"{foundation}/{map_id}"
    chosen = projects._rel(declaration["payload_path"], directory)
    mid = declaration["id"]
    for key, relative in declaration["recipes"].items():
        path = projects._rel(relative, directory)
        if path.is_symlink() or not path.is_file():
            raise Failure(INPUT_MISSING, f"{mid}: recipes[{key}] is missing: {relative}")
        src = job.input(path, limit=adapters.MAX_RECIPE_BYTES)
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise Failure(INPUT_INVALID, f"{mid}: recipes[{key}] is not valid JSON: {relative}") from exc
        if not adapters.is_adapter_recipe(data):
            raise Failure(INPUT_INVALID, f"{mid}: recipes[{key}] is not an adapter recipe: {relative}",
                          "A per-target entry names another cut of the same donor conversion: schema 1 with foundation, map and module.")
        if f"{data['foundation']}/{data['map']}" != key:
            raise Failure(INPUT_INVALID, f"{mid}: recipes[{key}] was cut for {data['foundation']}/{data['map']}: {relative}",
                          "A recipes key is the target its own recipe names; re-cut the recipe or file it under its own key.",
                          field='/recipes' + _pointer(key))
        if key == chosen_key:
            chosen = path
    return chosen, chosen_key


def load_declaration(directory: Path, job: Job, target: tuple[str | None, str | None] | None = None) -> dict:
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
    recipe = seed = adapter = None
    recipe_key = None
    if declaration["payload"] == "recipe":
        recipe = projects._rel(declaration["payload_path"], directory)
        if recipe.is_symlink() or not recipe.is_file():
            raise Failure(INPUT_MISSING, f"{mid}: recipe is missing: {data['recipe']}")
        # The third payload: a donor-converted module whose recipe a workspace builder cuts.
        # Decided by the recipe's own shape so a declaration needs no new field (adapters.py).
        from . import adapters
        if recipe.stat().st_size <= adapters.MAX_RECIPE_BYTES:
            try:
                shape = json.loads(recipe.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                shape = None
            if adapters.is_adapter_recipe(shape):
                recipe, recipe_key = _recipe_for_target(declaration, directory, job, target)
                adapter = adapters.load_recipe(recipe, directory, job, mid)
                recipe = None
        if recipe is not None and declaration["recipes"]:
            raise Failure(INPUT_INVALID, f"{mid}: recipes belongs to an adapter recipe; {declaration['payload_path']} is a project recipe the toolkit compiles itself",
                          "A project recipe is compiled and linked against whatever the composition targets; only a donor-converted cut is per target.",
                          field='/recipes')
    else:
        seed_rel = declaration["payload_path"]
        if distribution == "private" and not (directory / seed_rel).is_file():
            seed = {"private": True, "relative": seed_rel, "provides": {}, "missing": ["seed manifest"]}
        else:
            seed = seeds.load_manifest(directory, seed_rel, job, mid, allow_missing_files=distribution == "private")
    provides = declaration["provides"]
    if adapter is not None:
        # The recipe's declared outputs are the fact for an adapter, like a seed's manifest: a
        # declaration may narrow them and never add a name the recipe does not deliver.
        for pkind, names in provides.items():
            if pkind not in MANIFEST_KINDS or pkind == "rawfiles" and not adapter["rawfiles"]:
                continue
            listed = set(adapter["provides"].get(pkind, []))
            if not set(names) <= listed:
                raise Failure(INPUT_INVALID, f"{mid}: provides.{pkind} names {sorted(set(names) - listed)} which the adapter recipe does not deliver",
                              "An adapter recipe's weapons, soundbank, localize and rawfiles are what its build delivers; narrow the declaration, never widen it.")
        for pkind, names in adapter["provides"].items():
            provides.setdefault(pkind, list(names))
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
    return declaration | {"directory": directory, "recipe": recipe, "seed": seed, "adapter": adapter,
                          "recipe_key": recipe_key, "declaration": src}


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
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
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
        _fields(row, {"path", "name", "commit", "role", "parameters"}, set(), "composition member", f"/modules/{index}")
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
        members.append({"path": row["path"], "role": role, "name": row.get("name"), "commit": row.get("commit"),
                        "parameters": parameters.validate_setting(row.get("parameters"), f"Member {row['path']}", f"/modules/{index}/parameters")})
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
    for index, row in enumerate(comp["members"]):
        role = row["role"]
        directory = _relative_dir(row["path"], src.parent, job, "Member")
        if directory in directories:
            raise Failure(INPUT_INVALID, f"Member directory listed twice: {row['path']}")
        directories.append(directory)
        nested = directory / "composition.json"
        if (directory / "module.json").is_file():
            member = {"kind": "module", "directory": directory, "role": role, "path": row["path"], "parameters": row["parameters"],
                      "reference": {"name": row["name"], "commit": row["commit"]} if row["name"] is not None else None}
        elif nested.is_file() and not nested.is_symlink():
            if row["parameters"]:
                raise Failure(INPUT_INVALID, f"A nested composition takes no parameters: {row['path']}",
                              "Parameters are declared by a module and set on the member that is that module; set them in that pack's own composition.json.",
                              field=f"/modules/{index}/parameters")
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


def flatten(comp: dict, job: Job, target: tuple[str | None, str | None] | None = None) -> tuple[list[dict], list[Path], list[dict], list[str]]:
    """Every module in this composition and its nested compositions, with the loads and
    decisions gathered along the way. A nested composition's decisions apply to its own
    collisions; the outer recipe records the ones between its members. ``target`` is the pack's
    ``(foundation, map)``, which an adapter member's ``recipes`` picks its cut by; a nested
    composition declares the same base and map, so the outer target is its target too."""
    modules: list[dict] = []
    loads: list[Path] = list(comp["loads"])
    decisions: list[dict] = list(comp["decisions"])
    comp.setdefault("base_owned", set())
    header: list[str] = list(comp["zone_header"])
    for member in comp["members"]:
        if member["kind"] == "module":
            declaration = load_declaration(member["directory"], job, target)
            declaration["role"] = member["role"]
            declaration["parameters_set"] = member["parameters"]
            declaration["reference"] = member["reference"]
            declaration["via"] = comp["name"]
            modules.append(declaration)
        else:
            inner_modules, inner_loads, inner_decisions, inner_header = flatten(member["composition"], job, target)
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
    rank = {m["id"]: -1 if m["id"]=="test_probe" else 0 if m.get("role") == "base" else 1 for m in modules}
    order: list[str] = []
    while pending:
        ready = sorted((mid for mid, deps in pending.items() if not deps - set(order)), key=lambda mid: (rank[mid], mid))
        if not ready:
            raise Failure(INPUT_INVALID, f"Dependency cycle among modules: {sorted(pending)}")
        for mid in ready:
            order.append(mid)
            del pending[mid]
    return order


REFUSAL_KINDS = ("probe", "test_only", "duplicate_id", "missing_dependency", "conflict", "unqualified_base", "unqualified_map",
                 "private_payload", "cycle", "budget", "replacement", "service", "checks", "parameters")


def _refusal(kind: str, message: str, hint: str = "", modules=(), field: str | None = None, **extra) -> dict:
    row = {"kind": kind, "modules": sorted(set(modules)), "message": message, "hint": hint, "field": field}
    row.update(extra)
    return row


def refuse(refusals: list[dict], summary: str, hint: str, **details) -> Failure:
    """One failure for every refusal a plan found. The first refusal's own code, message and
    hint lead so a caller that reads only the top of the envelope sees what it always saw; the
    whole list travels under ``details.refusals`` for callers that act on data."""
    first = refusals[0]
    code = INPUT_LIMIT if first["kind"] == "budget" else INPUT_MISSING if first["kind"] == "private_payload" else INPUT_INVALID
    message = first["message"] if len(refusals) == 1 else f"{first['message']} (+{len(refusals) - 1} more refusal(s): {summary})"
    extra = {"refusals": refusals, **details}
    if first.get("field"):
        extra["field"] = first["field"]
    for key in ("collisions",):
        if first.get(key) is not None:
            extra.setdefault(key, first[key])
    return Failure(code, message, first["hint"] or hint, **extra)


def resolve(comp: dict, modules: list[dict], allow_unqualified: bool = False) -> dict:
    """Dependency order, fit, private payloads and budget. Every refusal is collected and
    returned under ``refusals`` (kinds in ``REFUSAL_KINDS``) so a caller reports all of them in
    one run; nothing raises here."""
    refusals: list[dict] = []
    for i,m in enumerate(modules):
        if "test-only" in m["tags"] and comp["name"].endswith(("_pack","_pub")):
            refusals.append(_refusal("test_only", "Test-only member cannot reach a release profile", modules=[m["id"]], field=f"/modules/{i}"))
        # Defaults filled, then what the composition set over them: the configuration this member
        # is planned and built with. A name the module does not declare, or a value outside its
        # declared type or constraint, refuses the plan and configures nothing.
        values, problems = parameters.effective(m.get("parameters"), m.get("parameters_set"))
        m["parameters_effective"] = values
        for name, message in problems:
            refusals.append(_refusal("parameters", f"{m['id']}: parameter {name!r} {message}",
                                     "A composition sets only the parameters the member's module declares, each within its declared type and "
                                     "constraint; pat module inspect lists them with their defaults.",
                                     modules=[m["id"]], field=f"/modules/{i}/parameters/{name}", parameter=name))
    ids = [m["id"] for m in modules]
    if len(set(ids)) != len(ids):
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        refusals.append(_refusal("duplicate_id", f"Two members declare the same id: {duplicates}",
                                 "A module appears once in a pack, including through nested compositions.", modules=duplicates))
    known = set(ids)
    unqualified = []
    for m in modules:
        for dep in m["dependencies"]:
            if dep not in known:
                refusals.append(_refusal("missing_dependency", f"{m['id']} depends on {dep}, which is not in the composition",
                                         "Add the module directory that declares that id to the composition's modules list.",
                                         modules=[m["id"], dep], dependency=dep, by=m["id"]))
        for other in m["conflicts"]:
            if other in known:
                refusals.append(_refusal("conflict", f"{m['id']} declares a conflict with {other}; both are in the composition", modules=[m["id"], other]))
        base_mismatch = comp["base"] not in m["bases"]
        map_mismatch = "*" not in m["maps"] and comp["map"] not in m["maps"]
        if base_mismatch or map_mismatch:
            # Listed whether or not the mismatch is tolerated: a refusal that names what is not
            # declared for this target is what ``adapt`` turns into a work order.
            unqualified.append({"id": m["id"], "declared_bases": m["bases"], "declared_maps": m["maps"], "base": comp["base"], "map": comp["map"]})
        if base_mismatch and not allow_unqualified:
            refusals.append(_refusal("unqualified_base", f"{m['id']} is declared for bases {m['bases']}, not for {comp['base']!r}",
                                     "Build the module on a base it declares, or extend its declaration after testing it there.",
                                     modules=[m["id"]], declared=m["bases"], wanted=comp["base"]))
        if map_mismatch and not allow_unqualified:
            refusals.append(_refusal("unqualified_map", f"{m['id']} is declared for maps {m['maps']}, not for {comp['map']!r}",
                                     "Qualify the module on that map first (build alone, load, play, record the verdict), then extend maps.",
                                     modules=[m["id"]], declared=m["maps"], wanted=comp["map"]))
        if m["seed"] and m["seed"].get("private"):
            refusals.append(_refusal("private_payload", f"{m['id']} is distribution private and its seed package is not on this machine (missing: {m['seed'].get('missing')})",
                                     "Others can read what a private module provides from its manifest; building a pack with it needs the package beside the manifest.",
                                     modules=[m["id"]], missing=m["seed"].get("missing")))
    order: list[str] = []
    try:
        # Only the members whose dependencies are present can be ordered; a missing dependency
        # is already a refusal above and must not also read as a cycle.
        orderable = list(modules)
        while True:
            present = {m["id"] for m in orderable}
            kept = [m for m in orderable if set(m["dependencies"]) <= present]
            if len(kept) == len(orderable):
                break
            orderable = kept
        order = _order(orderable)
    except Failure as exc:
        refusals.append(_refusal("cycle", exc.message, modules=[m["id"] for m in modules if m["id"] in exc.message]))
    totals = {field: sum(m["resource_contract"][field] for m in modules) for field in CONTRACT_FIELDS}
    if comp["budget"] is not None:
        for field in CONTRACT_FIELDS:
            if totals[field] > comp["budget"][field]:
                refusals.append(_refusal("budget", f"Resource budget exceeded: {field} {totals[field]} > {comp['budget'][field]}",
                                         "Raise the budget deliberately after measuring, or leave a module out; the sum counts every module.",
                                         field=f"/budget/{field}", resource=field, total=totals[field], bound=comp["budget"][field]))
    return {"order": order, "resource_totals": totals, "unqualified": unqualified, "refusals": refusals}


# What the plan can say about a member that is not declared for the target: why it is not, when
# it can tell. ``unknown`` is the honest answer for everything a plan cannot see (a missing effect
# root, a donor asset the target zones lack); only a build finds those, and `module qualify` types
# them from its own receipts.
ADAPT_PATTERNS = ("map-scripts", "dependency-unqualified", "adapter-recipe-single-target-without-recipes", "unknown")


def adapt_rows(comp: dict, modules: list[dict], unqualified: list[dict], foundation: str | None, checks=()) -> list[dict]:
    """One work order per member that is not declared for the composition's target.

    Read-only: nothing is widened, built or written here. Each row names the module, the target
    as ``<foundation>/<map>``, the command that would earn the widening, and the pattern the plan
    could see. The patterns a plan can decide are a script the target map does not carry
    (``map-scripts``, from a failed check this member owns), a dependency that is itself
    undeclared (``dependency-unqualified``), and an adapter whose recipe is a cut for another
    target with no ``recipes`` entry for this one
    (``adapter-recipe-single-target-without-recipes``); everything else is ``unknown``."""
    if not unqualified:
        return []
    undeclared = {row["id"] for row in unqualified}
    by_id = {m["id"]: m for m in modules}
    target = f"{foundation or comp['base']}/{comp['map']}"
    failed_scripts = {c["id"][len("map-scripts:"):]: c for c in checks
                      if c.get("outcome") == "failed" and str(c.get("id", "")).startswith("map-scripts:")}
    rows = []
    for row in unqualified:
        m = by_id.get(row["id"])
        if m is None:
            continue
        pattern, detail = "unknown", None
        owned = sorted(name for name in failed_scripts if name in set(m.get("provides", {}).get("scripts", [])))
        if owned:
            pattern = "map-scripts"
            detail = failed_scripts[owned[0]].get("detail")
        elif m.get("adapter") is not None and m.get("recipe_key") is None \
                and (m["adapter"]["foundation"], m["adapter"]["map"]) != (foundation, comp["map"]):
            pattern = "adapter-recipe-single-target-without-recipes"
            detail = f"the recipe is the {m['adapter']['foundation']}/{m['adapter']['map']} cut and recipes names no entry for {target}"
        elif sorted(set(m["dependencies"]) & undeclared):
            pattern = "dependency-unqualified"
            detail = "depends on " + ", ".join(sorted(set(m["dependencies"]) & undeclared))
        rows.append({"module": m["id"], "directory": str(m["directory"]), "target": target, "pattern": pattern,
                     "detail": detail, "declared_bases": row["declared_bases"], "declared_maps": row["declared_maps"],
                     "work_order": f"pat module qualify {m['directory']} --target {target}"})
    return rows


def collisions(modules: list[dict], loaded: dict[str, tuple], decisions: list[dict], base_owned: set[str] | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    """Every place two modules would own the same thing, as decisions. Identical bytes for the
    same file dedupe with no decision; a name the base zones already carry (``base_owned``,
    from the composition's base listings) is the base's and resolves with no decision; anything
    else needs an owner recorded in the recipe. Returns (decided, undecided, refused); declared replacements cannot be decided away."""
    base_owned = base_owned or set()
    file_owners: dict[str, list[tuple[str, str]]] = {}
    # A withheld row stages the file under raw/ but emits no zone entry, so a withheld owner
    # would drop a delivered member's ``rawfile,`` line: remember which owners are withheld.
    withheld_owners: set[tuple[str, str]] = set()
    for m in modules:
        if m["recipe"] is not None:
            data, compiled, loose, _ = loaded[m["id"]]
            for source, target, _ in compiled:
                file_owners.setdefault(target.as_posix().casefold(), []).append((m["id"], sha256_file(source)))
            for source, target, _, _ in loose:
                file_owners.setdefault(target.as_posix().casefold(), []).append((m["id"], sha256_file(source)))
            # A withheld authoring input is still one file under raw/ that every member's compiled
            # asset reads by name: two members withholding the same path with different bytes
            # would compile from whichever copy was staged last, so it is a file decision like any.
            for row in data.get("_withheld", []):
                file_owners.setdefault(row["target"].casefold(), []).append((m["id"], sha256_file(Path(row["path"]))))
                withheld_owners.add((row["target"].casefold(), m["id"]))
        elif m["seed"] and not m["seed"].get("private"):
            for row in m["seed"]["embedded"]:
                kind, name = row.split(",", 1)
                if kind == "rawfile":
                    file_owners.setdefault(name.casefold(), []).append((m["id"], "seed:" + m["seed"]["files"]["mod.ff"].name))
        elif m.get("adapter"):
            for script in m["adapter"]["scripts"]:
                file_owners.setdefault(script["target"].casefold(), []).append((m["id"], sha256_file(script["source"])))
            for row in m["adapter"]["embedded"]:
                kind, name = row.split(",", 1)
                if kind == "rawfile" and name.casefold() not in {s["target"].casefold() for s in m["adapter"]["scripts"]}:
                    file_owners.setdefault(name.casefold(), []).append((m["id"], "adapter:" + m["id"]))
    name_owners: dict[str, list[str]] = {}
    for m in modules:
        for pkind, names in m["provides"].items():
            if pkind == "rawfiles":
                # A provided rawfile is a file target: the file collision above already lists it (for a
                # seed, from its manifest's embedded rows) and the build resolves that one record.
                continue
            for name in names:
                name_owners.setdefault(f"{pkind}:{name}", []).append(m["id"])
        embedded_rows = m["seed"]["embedded"] if m["seed"] and not m["seed"].get("private") else m["adapter"]["embedded"] if m.get("adapter") else []
        for row in embedded_rows:
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
        if len(digests) == 1 and not any(d.startswith(("seed:", "adapter:")) for d in digests):
            # Identical bytes dedupe with no decision, but the owner must be a delivered member
            # where there is one: a withheld owner stages the file and emits no zone entry, so
            # picking it would silently drop the delivered member's rawfile row.
            owner = next((i for i in ids if (target, i) not in withheld_owners), ids[0])
            decided.append({"collision": target, "kind": "file", "modules": ids, "resolution": "identical bytes; one copy is packed", "owner": owner})
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
    refused=[]
    for kind,field in (("function","functions"),("file","files")):
        owners={}
        for m in modules:
            for target in m.get("replaces",{}).get(field,[]):owners.setdefault(target,[]).append(m["id"])
        for target,ids in sorted(owners.items()):
            if len(ids)>1:refused.append({"collision":kind+":"+target,"kind":kind,"modules":sorted(ids)})
    return decided, undecided, refused


def _aliases_of(m: dict, loaded: dict[str, tuple]) -> dict[str, list[str]]:
    """Sound alias names a member's banks carry, by bank: an adapter's alias table when its
    prepared inputs are on this machine, a recipe's soundbank row read from its alias CSV, or
    the declaration's own ``provides.aliases``. A seed manifest carries none, so a seed's bank
    is never judged here."""
    out: dict[str, list[str]] = {}
    declared = list(m.get("provides", {}).get("aliases", []))
    if m.get("adapter") and m["adapter"]["soundbank"]:
        out[m["adapter"]["soundbank"]] = list(m["adapter"]["aliases"])
    elif m["recipe"] is not None and m["id"] in loaded:
        from . import adapters
        for source, _target, asset_type, name in loaded[m["id"]][2]:
            if asset_type == "soundbank" and Path(source).suffix.lower() == ".csv":
                out[name] = adapters.read_aliases(Path(source), m["id"])
    if declared:
        banks = list(m.get("provides", {}).get("soundbanks", [])) or ["(declared)"]
        for bank in banks:
            out.setdefault(bank, [])
            out[bank] = sorted(set(out[bank]) | set(declared))
    return out


def shelf_services(workspace: str | None) -> list[dict]:
    """Declarations under ``<workspace>/modules`` that can own a shared thing: what each provides
    by kind, read from ``module.json`` only (no payload, no recipe). Bounded; unreadable
    declarations are skipped."""
    if not workspace:
        return []
    root = Path(workspace).expanduser() / "modules"
    if not root.is_dir():
        return []
    rows = []
    for index, child in enumerate(sorted(root.iterdir())):
        if index >= MAX_SHELF_ENTRIES:
            break
        path = child / "module.json"
        if child.is_symlink() or not path.is_file() or path.is_symlink():
            continue
        try:
            if path.stat().st_size > MAX_DECLARATION_BYTES:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            meta = validate_declaration_metadata(data)
        except (OSError, ValueError, Failure):
            continue
        rows.append({"id": meta["id"], "directory": child.name, "tags": meta["tags"], "provides": meta["provides"]})
    return rows


def _service_for(services: list[dict], kind: str, name: str) -> dict | None:
    """The shelf module that owns ``name``: one that provides it and registers no weapon of its
    own (a weapon module shipping its own copy of a shared table is the problem, not the
    service). A ``shared-service`` tag wins among candidates."""
    key = name.casefold()
    candidates = [row for row in services if any(n.casefold() == key for n in row["provides"].get(kind, [])) and not row["provides"].get("weapons")]
    candidates.sort(key=lambda row: (0 if "shared-service" in row["tags"] else 1, row["id"]))
    return candidates[0] if candidates else None


def native_weapons(map_id: str, foundation: str) -> set[str]:
    """WeaponDef names the target map's zones carry on this foundation, from the shipped table
    (``knowledge/native-weapons.json``); empty when the map or foundation is not tabled, so the
    check stays a base listing's job there."""
    from . import knowledge
    try:
        row = knowledge.load("native-weapons.json")["maps"].get(map_id)
    except Failure:
        return set()
    if not row or row.get("foundation") != foundation:
        return set()
    return {f"weapon,{w}".casefold() for w in row.get("weapons", [])}


def service_refusals(modules: list[dict], loaded: dict[str, tuple], undecided: list[dict], base_owned: set[str], services: list[dict]) -> list[dict]:
    """Collisions that are not an owner decision but a missing service (docs/MODULES.md):

    - two members ship differing copies of a map-owned table (``animstatedefs/``, ``animtrees/``,
      ``aitype/``): the map needs one merged copy;
    - two members' banks carry the same sound alias: the alias needs one bank module;
    - a member registers a WeaponDef the base zones already carry (``base_owned``): the native
      definition stays and the module declares only its new names.

    Each row names the members, the thing, and the shelf module that provides it when one
    does (``service``), so the fix is a dependency edit, not a decision."""
    rows = []
    for row in undecided:
        if row["kind"] != "file":
            continue
        target = row["collision"]
        if target.startswith(MAP_OWNED_PREFIXES):
            owner = _service_for(services, "rawfiles", target) or _service_for(services, "scripts", target)
            owner = owner if owner and owner["id"] not in row["modules"] else None
            rows.append({"kind": "service", "collision": target, "modules": row["modules"], "what": "map-owned table",
                         "message": f"{target} is a map-owned table that {', '.join(row['modules'])} each replace with their own copy; it needs one merged owner"
                                    + (f": depend on {owner['id']} and ship no copy" if owner else "; no module on the shelf provides it yet"),
                         "service": owner["id"] if owner else None, "hint": "A file two members would both replace is owned by a service module, never by either member."})
    alias_owners: dict[str, list[tuple[str, str]]] = {}
    for m in modules:
        for bank, aliases in _aliases_of(m, loaded).items():
            for alias in aliases:
                alias_owners.setdefault(alias, []).append((m["id"], bank))
    for alias, owners in sorted(alias_owners.items()):
        ids = sorted({mid for mid, _ in owners})
        if len(ids) < 2:
            continue
        banks = sorted({bank for _, bank in owners})
        owner = _service_for(services, "aliases", alias)
        owner = owner if owner and owner["id"] not in ids else None
        rows.append({"kind": "service", "collision": "alias:" + alias, "modules": ids, "what": "sound alias", "banks": banks,
                     "message": f"sound alias {alias} is carried by {len(banks)} banks ({', '.join(banks)[:400]}) from {', '.join(ids)[:400]}; one bank module must own it"
                                + (f": depend on {owner['id']} and ship no bank" if owner else "; no module on the shelf provides it yet"),
                     "service": owner["id"] if owner else None, "hint": "One alias, one bank: the members depend on the bank module and ship none of their own."})
    if base_owned:
        for m in modules:
            native = sorted(w for w in m.get("provides", {}).get("weapons", []) if f"weapon,{w}".casefold() in base_owned)
            if native:
                rows.append({"kind": "service", "collision": "weapons:" + ",".join(native), "modules": [m["id"]], "what": "native WeaponDef", "weapons": native,
                             "message": f"{m['id']} registers WeaponDef(s) the base zones already carry: {', '.join(native)[:400]}; keep the native definition and declare only new names",
                             "service": None, "hint": "An imported WeaponDef that overrides the map's own crashes precache; drop it from the recipe's weapons and provides."})
    return rows


def _backends(compiled: list, adapters_present: bool = False, workspace: str | None = None) -> list[dict]:
    checks = []
    for name in (["gsc"] if compiled else []) + ["linker", "unlinker"]:
        try:
            checks.append({"id": name, "argv": executable(name), "available": True})
        except Failure as exc:
            checks.append({"id": name, "available": False, "message": exc.message})
    if adapters_present:
        from . import adapters
        try:
            checks.append({"id": "adapter_builder", "argv": adapters.builder_argv(workspace), "available": True})
        except Failure as exc:
            checks.append({"id": "adapter_builder", "available": False, "message": exc.message})
    return checks


def _plan_rows(modules: list[dict], order: list[str], job: Job) -> list[dict]:
    by_id = {m["id"]: m for m in modules}
    rows = []
    for mid in order:
        m = by_id[mid]
        row = {"id": mid, "version": m["version"], "title": m["title"], "category": m["category"], "kind": m["kind"],
               "tags": m["tags"], "role": m.get("role", "module"), "via": m.get("via"), "directory": str(m["directory"]),
               "declaration_sha256": job.inputs[str(m["declaration"])],
               "payload": "seed" if m["seed"] else "adapter" if m.get("adapter") else "recipe",
               "distribution": m["distribution"], "dependencies": m["dependencies"], "conflicts": m["conflicts"],
               "bases": m["bases"], "maps": m["maps"], "provides": m["provides"], "resource_contract": m["resource_contract"],
               "menu_route": m["menu_route"], "source": m["source"], "reference": m.get("reference"),
               "origin": m["origin"], "donor": m["donor"], "replaces":m["replaces"], "entry":m["entry"], "placements": m.get("placements"),
               "parameters": m.get("parameters_effective", {})}
        if m["recipe"] is not None:
            row["recipe_sha256"] = job.inputs[str(m["recipe"].resolve())]
        elif m.get("adapter") is not None:
            a = m["adapter"]
            row["recipe_sha256"] = job.inputs[str(a["recipe"].resolve())]
            row["recipes"] = sorted(m.get("recipes") or ())
            row["adapter"] = {"foundation": a["foundation"], "map": a["map"], "profile": a["profile"],
                              "recipe_key": m.get("recipe_key"),
                              "prepared_present": a["prepared_present"], "declared_roots": len(a["embedded"]),
                              "loose_scripts": [s["target"] for s in a["scripts"]], "soundbank": a["soundbank"], "aliases": a["aliases"]}
        else:
            row["seed_sha256"] = m["seed"]["files"]["mod.ff"] and job.inputs[str(m["seed"]["package"].resolve())]
            row["seed_manifest_sha256"] = job.inputs[str(m["seed"]["manifest"])]
            row["seed_roots"] = len(m["seed"]["roots"])
        rows.append(row)
    return rows


def execute(args, job: Job) -> dict:
    if args.action == "qualify":
        from . import qualify

        return qualify.execute(args, job)
    if args.action == "compose":
        from . import compose
        return compose.execute(args, job)
    if args.action == "fetch":
        from . import registry

        return registry.fetch(args, job)
    if args.action == "declare":
        return seeds.declare(Path(args.package).expanduser(), args, job)
    comp = load_composition(Path(args.composition), job)
    from . import checks as offline_checks
    # The pack's target in the workspace's own foundation ids, resolved once: an adapter member
    # whose declaration names a recipe for it is planned and built from that cut, not the default.
    pack_foundation = offline_checks.foundation_of(comp["base"], getattr(args, "workspace", None))
    modules, loads, decisions, header = flatten(comp, job, (pack_foundation, comp["map"]))
    from ..testing.planner import prepare_probe
    try:
        prepare_probe(comp,modules,job)
    except Failure as exc:
        raise refuse([_refusal("probe", exc.message, exc.hint, field=exc.details.get("field"))], "probe",
                     "Read details.refusals: the test probe this composition needs is missing or does not cover its target.")
    mixed = sorted({m["id"] for m in modules if m.get("game", titles.DEFAULT_TITLE) != comp["game"]})
    if mixed:
        raise Failure(INPUT_INVALID, f"Composition targets game {comp['game']} but these members target another game: {mixed}",
                      "Every module in a composition targets the same game; split the pack or fix the members' module.json game.")
    resolved = resolve(comp, modules, getattr(args, "allow_unqualified", False))
    if resolved["refusals"]:
        raise refuse(resolved["refusals"], "; ".join(sorted({r["kind"] for r in resolved["refusals"]})),
                     "Read details.refusals: every refusal the composition has, with its kind and modules.",
                     unqualified=resolved["unqualified"],
                     adapt=adapt_rows(comp, modules, resolved["unqualified"], pack_foundation))
    loaded = {}
    absent: list[dict] = []
    for m in modules:
        if m["recipe"] is None:
            continue
        try:
            loaded[m["id"]] = projects.load_recipe(m["recipe"], job)
        except Failure as exc:
            if exc.code == INPUT_MISSING and m["distribution"] == "private":
                # A private recipe whose sources are not on this machine is the recipe-side of
                # a private seed without its package: plannable around, not buildable here.
                absent.append(_refusal("private_payload", f"{m['id']} is distribution private and its recipe inputs are not on this machine: {exc.message}",
                                       "The declaration says what the module provides; building with it needs its sources beside the recipe.",
                                       modules=[m["id"]], missing=[exc.message]))
                continue
            raise
    if absent:
        raise refuse(absent, "private_payload", "Read details.refusals: every private member whose inputs are absent here.")
    warnings=replacement_warnings(modules,loaded)
    by_id = {m["id"]: m for m in modules}
    compiled, loose = [], []
    owner_of_script: dict[str, str] = {}
    withheld: list[dict] = []
    for mid in resolved["order"]:
        if mid in loaded:
            data, c, l, extra_loads = loaded[mid]
            compiled += c
            loose += l
            for _, t, _ in c:
                owner_of_script[t.as_posix()] = mid
            for _, t, _, _ in l:
                owner_of_script[t.as_posix()] = mid
            withheld += [{"module": mid, **row} for row in data.get("_withheld", [])]
            loads += [p for p in extra_loads if p not in loads]
    seed_modules = [by_id[mid] for mid in resolved["order"] if by_id[mid]["seed"]]
    generated_entry = _generate_entry(comp, modules, by_id, resolved["order"], loaded, compiled, loose, seed_modules, job)
    if generated_entry is not None:
        compiled.append(generated_entry["script"])
    if len(compiled) > projects.MAX_SCRIPTS or len(loose) > projects.MAX_ASSETS or len(loads) > projects.MAX_LOADS or len(seed_modules) > MAX_MODULES:
        raise Failure(INPUT_LIMIT, f"A composition holds at most {projects.MAX_SCRIPTS} scripts, {projects.MAX_ASSETS} assets, {projects.MAX_LOADS} loads and {MAX_MODULES} seeds")
    decided, undecided, refused = collisions(modules, loaded, decisions, comp.get("base_owned"))
    late_refusals: list[dict] = []
    if refused:
        late_refusals.append(_refusal("replacement", "Overlapping declared replacements cannot be resolved by an owner decision",
                                      "Two members declare the same replacement target; one of them must stop replacing it.",
                                      modules=[mid for row in refused for mid in row["modules"]], collisions=refused))
    foundation = pack_foundation
    # The native-WeaponDef rule is a declaration check: the shipped per-map table names what the
    # map already registers, and a composition's own base listings add to it.
    owned_weapons = (comp.get("base_owned") or set()) | native_weapons(comp["map"], foundation)
    services = service_refusals(modules, loaded, undecided, owned_weapons, shelf_services(getattr(args, "workspace", None)))
    if services:
        served = {row["collision"] for row in services}
        undecided = [row for row in undecided if row["collision"] not in served]
        for row in services:
            late_refusals.append(_refusal("service", row["message"], row["hint"], modules=row["modules"], collision=row["collision"],
                                          what=row["what"], service=row["service"], **{k: v for k, v in row.items() if k in ("banks", "weapons")}))
    adapter_modules = [by_id[mid] for mid in resolved["order"] if by_id[mid].get("adapter")]
    checks = _backends(compiled, bool(adapter_modules), getattr(args, "workspace", None))
    rows = _plan_rows(modules, resolved["order"], job)
    base_ids = [r["id"] for r in rows if r["role"] == "base"]
    plan = {
        "schema_version": 1, "name": comp["name"], "title": comp["title"], "tags": comp["tags"], "base": comp["base"],
        "map": comp["map"], "origin": comp["origin"], "donor": comp["donor"],
        "game": comp["game"], "mode": titles.zone(comp["game"])["mode"], "warnings":warnings,
        "base_member": base_ids[0] if base_ids else None,
        "modules": rows, "order": resolved["order"],
        "scripts": [{"source": str(p), "target": t.as_posix(), "instance": i, "module": owner_of_script.get(t.as_posix())} for p, t, i in compiled],
        "assets": [{"source": str(p), "target": t.as_posix(), "type": k, "name": n, "module": owner_of_script.get(t.as_posix())} for p, t, k, n in loose],
        "withheld": withheld,
        "seeds": [{"id": m["id"], "package": str(m["seed"]["package"]), "roots": m["seed"]["roots"],
                   "soundbanks": [n for n in m["seed"]["files"] if n != "mod.ff"],
                   "strings": str(m["seed"]["strings"]) if m["seed"].get("strings") else None} for m in seed_modules],
        "adapters": [{"id": m["id"], "recipe": str(m["adapter"]["recipe"]), "recipe_key": m.get("recipe_key"),
                      "foundation": m["adapter"]["foundation"], "map": m["adapter"]["map"],
                      "roots": m["adapter"]["embedded"], "soundbanks": [m["adapter"]["soundbank"]] if m["adapter"]["soundbank"] else [],
                      "aliases": m["adapter"]["aliases"], "loose_scripts": [s["target"] for s in m["adapter"]["scripts"]],
                      "prepared_present": m["adapter"]["prepared_present"]} for m in adapter_modules],
        "loads": [str(p) for p in loads], "zone_header": header,
        "unqualified": resolved["unqualified"], "adapt": adapt_rows(comp, modules, resolved["unqualified"], pack_foundation),
        "resource_totals": resolved["resource_totals"], "budget": comp["budget"],
        "decisions": decided, "undecided": undecided, "base_owned_names": len(comp.get("base_owned") or ()),
        "backends": checks, "backends_available": all(c["available"] for c in checks),
        "input_files": len(job.inputs),
        "verification": "composition resolved (dependency order, conflicts, budget); base/map mismatches listed in unqualified; collisions listed as decisions; "
                        "declarations, recipes, seeds and declared inputs hashed; backend presence checked; nothing compiled",
    }
    plan["footprint"] = offline_checks.footprint(plan)
    plan["checks"] = offline_checks.evaluate(plan, getattr(args, "workspace", None))
    # Image pixels are the one pool a plan cannot read on its own: the banks are not here. The
    # check says what it can prove and stays not_counted for the rest unless a readback decides it.
    image_report = getattr(args, "image_report", None)
    plan["checks"] += offline_checks.image_sources(plan, offline_checks.read_image_report(job.input(Path(image_report))) if image_report else None)
    provided_weapons = {w for m in modules for w in (m.get("provides", {}).get("weapons") or [])}
    pack_scripts = {t.as_posix() for _, t, _ in compiled} | {t.as_posix() for _, t, _, _ in loose}
    for m in modules:
        pack_scripts |= set(m.get("provides", {}).get("scripts", []))
        for row in (m["seed"]["embedded"] if m["seed"] and not m["seed"].get("private") else m["adapter"]["embedded"] if m.get("adapter") else []):
            kind, asset = row.split(",", 1)
            if kind in ("script", "rawfile") and asset.lower().endswith((".gsc", ".csc")):
                pack_scripts.add(asset)
    for source,target,_ in compiled:
        try: text=Path(source).read_text(encoding="utf-8",errors="replace")
        except OSError: continue
        plan["checks"] += offline_checks.external_symbols(target.as_posix(),text,comp["game"])
        plan["checks"] += offline_checks.map_script_externals(target.as_posix(),text,comp["map"],foundation,comp["game"],pack_scripts)
        plan["checks"] += offline_checks.box_registrations(target.as_posix(),text,provided_weapons)
    if args.action == "build":
        plan["checks"] += offline_checks.check_scripts(compiled,args,job,comp["game"])
    else:
        plan["checks"] += [{"id":"symbols:"+t.as_posix(),"outcome":"not_counted","detail":"gsc check runs before the build link"} for _,t,_ in compiled]
    if generated_entry is not None:
        plan["generated_entry"] = generated_entry["plan"]
    plan["placements"] = _placement_checks(comp, modules, args, job)
    plan["checks"] += [{"id": "placements:" + row["target"], "outcome": row["outcome"], "detail": row["detail"]} for row in plan["placements"]]
    # The map-scripts rows exist only now, so the work orders are re-derived with them.
    plan["adapt"] = adapt_rows(comp, modules, resolved["unqualified"], pack_foundation, plan["checks"])
    (job.root / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    summary = {"plan": "plan.json", "name": comp["name"], "title": comp["title"], "base": comp["base"], "map": comp["map"],
               "base_member": plan["base_member"],
               "modules": [{"id": r["id"], "version": r["version"], "order": i + 1, "payload": r["payload"], "role": r["role"],
                            "parameters": r.get("parameters", {})}
                           for i, r in enumerate(rows)],
               "unqualified": resolved["unqualified"], "adapt": plan["adapt"],
        "resource_totals": resolved["resource_totals"], "budget": comp["budget"],
               "scripts": len(compiled), "assets": len(loose), "seeds": len(seed_modules), "adapters": len(adapter_modules), "loads": len(loads),
               "decisions": decided, "undecided": undecided, "base_owned_names": len(comp.get("base_owned") or ()),
               "footprint": plan["footprint"], "withheld": len(withheld)}
    summary["checks"] = plan["checks"]
    summary["placements"] = plan["placements"]
    failed=[c for c in plan["checks"] if c["outcome"]=="failed"]
    if failed:
        contributors=sorted({c["id"] for row in failed for c in row.get("contributors",[]) if c["id"] in by_id})
        late_refusals.append(_refusal("checks","Offline checks failed: "+"; ".join(f'{c["id"]}: {c["detail"]}' for c in failed)[:1200],
                                      "Read checks for every row; a pool row names its largest contributors, a map-scripts row the paths the target map lacks.",
                                      modules=contributors,failed=[c["id"] for c in failed]))
    if late_refusals:
        plan["refusals"]=late_refusals
        (job.root / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        raise refuse(late_refusals,"; ".join(sorted({r["kind"] for r in late_refusals})),
                     "Read details.refusals: every refusal the composition has, with its kind and modules.",
                     checks=plan["checks"],failed=[c["id"] for c in failed],undecided=undecided,
                     unqualified=resolved["unqualified"],adapt=plan["adapt"])
    if args.action == "plan":
        return {**summary, "backends": checks, "backends_available": plan["backends_available"],
                "input_files": plan["input_files"], "verification": plan["verification"]}
    if undecided:
        raise Failure(INPUT_INVALID, f"{len(undecided)} collision(s) have no recorded decision; nothing was built",
                      "Read plan.json's undecided list, record an owner for each under decisions in the composition (or rename a target), then build.",
                      undecided=undecided)
    if adapter_modules:
        # Adapter members are cut by the workspace builder first; each produced package is read
        # back and joins the seeds the pack links against. The plan on disk records the reports.
        from . import adapters
        missing = [c["id"] for c in checks if not c["available"]]
        if missing:
            raise Failure("backend_unavailable", f"Required backends are not installed: {missing}", "Run: pat dev setup; an adapter builder comes from --workspace or PAT_BACKEND_ADAPTER_BUILDER")
        plan["adapter_builds"] = []
        # The builder is told the pack's target only in the workspace's own foundation ids: a
        # token the toolkit maps for occupancy ("stock") is not a foundation the builder knows.
        # A member whose declaration named a recipe for this target is already cut for it, so
        # `target_argv` finds nothing to override and the builder hears no flags.
        workspace = getattr(args, "workspace", None)
        from . import targets
        builder_foundation = targets.foundation_for_base(Path(workspace).expanduser(), comp["base"]) if workspace else None
        for m in adapter_modules:
            m["seed"] = adapters.build(m, args, job, workspace, builder_foundation, comp["map"])
            plan["adapter_builds"].append(m["seed"]["report"])
        seed_modules = [by_id[mid] for mid in resolved["order"] if by_id[mid]["seed"]]
        plan["seeds"] = [{"id": m["id"], "package": str(m["seed"]["package"]), "roots": m["seed"]["roots"],
                          "soundbanks": [n for n in m["seed"]["files"] if n != "mod.ff"],
                          "strings": str(m["seed"]["strings"]) if m["seed"].get("strings") else None} for m in seed_modules]
        (job.root / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    built = _build_composition(comp, plan, compiled, loose, seed_modules, loads, decided, header, args, job)
    if adapter_modules:
        built["adapters"] = plan["adapter_builds"]
    return built


def _placement_checks(comp: dict, modules: list[dict], args, job: Job) -> list[dict]:
    """Per target, which declared placements needs a location table can satisfy and which it
    cannot (``docs/target-sets.md``). A check only: no provider module is generated. Without
    ``--target`` the needs are listed against the composition's own map as ``not_counted``."""
    from . import targets as target_sets
    declared = [m for m in modules if m.get("placements")]
    keys = list(getattr(args, "target", None) or [])
    workspace = getattr(args, "workspace", None)
    if not declared and not keys:
        return []
    if keys and not workspace:
        raise Failure(INVALID_ARGUMENTS, "--target needs --workspace: the location tables live under the workspace's registry/locations",
                      "Run: pat target list <workspace> --json")
    root = Path(workspace).expanduser() if workspace else None
    if root is not None and not root.is_dir():
        raise Failure(INPUT_MISSING, f"Workspace directory is missing: {root}")
    if not keys:
        row = target_sets.resolve_placements(declared, None, f"{comp['base']}/{comp['map']}")
        row["detail"] = f"no --target given; {len(row['needs'])} need(s) listed against map {comp['map']}, nothing resolved"
        return [row]
    rows = []
    for entry_id in keys:
        key, _ = target_sets.parse_id(entry_id)
        parts = target_sets.parse_key(key)
        if parts["map"] != comp["map"]:
            raise Failure(INVALID_ARGUMENTS, f"Target {entry_id} is on map {parts['map']} but the composition is planned for {comp['map']}",
                          "A composition is planned for one map; its targets are that map and the survival locations inside it.")
        resolved = target_sets.table_for(root, entry_id)
        table = None
        if resolved["path"]:
            path = root / resolved["path"]
            job.input(path, limit=target_sets.MAX_TABLE_BYTES)
            loaded = target_sets.load_table(path)
            if loaded["errors"]:
                raise Failure(INPUT_INVALID, f"Location table for {entry_id} is invalid; run pat target validate {root} --json",
                              diagnostics=loaded["errors"][:32])
            table = loaded["doc"]
        row = target_sets.resolve_placements(declared, table, entry_id)
        row["route"] = resolved["route"]
        row["table_path"] = resolved["path"]
        rows.append(row)
    return rows


def entry_source(name, members):
    members=[m for m in members if m.get('entry')]
    lines=['// generated by pat module build; do not edit','']
    includes=sorted({m['entry'][key].split('::')[0] for m in members for key in ('replace','register')})
    lines += ['#include '+path.replace('/',chr(92))+';' for path in includes]
    for root,key in (('main','replace'),('init','register')):
        lines += ['',root+'()','{']
        lines += ['    '+m['entry'][key].replace('/',chr(92))+'();' for m in members]
        lines += ['}']
    return '\n'.join(lines)+'\n'


def _generate_entry(comp, modules, by_id, order, loaded, compiled, loose, seed_modules, job):
    """Write the generated entry script and the include root it is compiled against.

    Returns ``None`` when no member owns an entry; otherwise ``{"script": (source, target,
    instance), "plan": {...}}``. The target follows ``titles.script_target`` (T6
    ``scripts/zm/``, IW5 the flat ``scripts/`` namespace) and is reserved case-insensitively
    against every staged recipe/loose target and seed rawfile before anything is written, so
    an existing owner refuses instead of silently outliving the entry. Each entry member's
    recipe source is staged at its target path and its admitted source tree (the same bounded
    ``input_tree`` the recipe already hashed) at the source-relative path, so sibling and
    transitive ``#include`` directives resolve. A reference is matched to its module's recipe
    target case-insensitively and the emitted include and call use that canonical target path;
    a reference that matches no target refuses. Two sources that map to one include path with
    different bytes refuse rather than overwrite.
    """
    entry_modules=[m for m in modules if m.get('entry')]
    if not entry_modules:
        return None
    target=Path(titles.script_target(comp['game'],'zz_'+comp['name']+'_entry'))
    reserved=target.as_posix().casefold()
    owned=[t.as_posix() for _,t,_ in compiled]+[t.as_posix() for _,t,_,_ in loose]
    for m in seed_modules:
        if m['seed'] and not m['seed'].get('private'):
            owned += [row.split(',',1)[1] for row in m['seed']['embedded'] if row.startswith('rawfile,')]
    if any(name.casefold()==reserved for name in owned):
        raise Failure(INPUT_INVALID,f"Generated entry target {target.as_posix()} is already owned by another source",
                      "Rename the colliding script or rawfile target; the build reserves this path for the generated entry.")
    # A reference is normalized to lowercase by `_function`, so match it to the module's recipe
    # target case-insensitively and emit the canonical target path. On a case-sensitive host the
    # emitted #include must name a file that was actually staged; a reference that matches no
    # target is refused instead of compiling against a path nothing provides.
    module_index={m['id']:i for i,m in enumerate(modules)}
    resolved_entries={}
    for m in entry_modules:
        recipe=loaded.get(m['id'])
        if recipe is None:
            raise Failure(INPUT_INVALID,f"Entry-managed module {m['id']} has no recipe script to include",
                          "An entry needs the module's own recipe; point entry at one of its script targets.",
                          field=f"/modules/{module_index[m['id']]}/entry")
        targets={}
        for source,member_target,instance in recipe[1]:
            posix=member_target.as_posix()
            # The generated entry is a server script: only a server .gsc target can own its
            # include and exported function. A plain client target is never a candidate.
            if instance!='server' or Path(posix).suffix.lower()!='.gsc':
                continue
            targets[posix.rsplit('.',1)[0].casefold()]=(source,member_target,posix)
        refs={}
        for key in ('replace','register'):
            path,function=m['entry'][key].split('::')
            match=targets.get(path.casefold())
            if match is None:
                raise Failure(INPUT_INVALID,f"Entry reference {m['entry'][key]} names no server .gsc recipe script target of module {m['id']}",
                              "An entry is generated as a server script; point it at one of the module's server .gsc targets, compared case-insensitively.",
                              field=f"/modules/{module_index[m['id']]}/entry")
            refs[key]=match[2].rsplit('.',1)[0]+'::'+function
        resolved_entries[m['id']]=refs
    root=job.root/'generated-entry'
    root.mkdir(parents=True,exist_ok=True)
    staged={}
    def stage(rel,source,digest):
        key=rel.casefold()
        if key in staged:
            if staged[key][1]!=digest:
                raise Failure(INPUT_INVALID,f"Two entry sources map to {rel} with different bytes: {staged[key][0]} and {source}",
                              "Rename one so the generated entry's include tree is unambiguous.")
            return
        staged[key]=(source,digest,rel)
    for m in entry_modules:
        recipe=loaded.get(m['id'])
        for source,member_target,_ in recipe[1]:
            stage(member_target.as_posix(),source,job.inputs[str(source)])
        for source,_,_ in recipe[1]:
            source_dir=source.parent
            for rel,digest in job.trees.get(str(source_dir),{}).items():
                if Path(rel).suffix.lower() in ('.gsc','.csc'):
                    stage(rel,source_dir/rel,digest)
    if target.name.casefold() in staged:
        raise Failure(INPUT_INVALID,f"Generated entry target {target.as_posix()} collides with a staged include file",
                      "Rename the module script that maps to the entry path.")
    for source,_,rel in staged.values():
        dest=root/rel
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,dest)
    ordered=[{**by_id[mid],'entry':resolved_entries[mid]} if mid in resolved_entries else by_id[mid] for mid in order]
    generated=root/target.name
    generated.write_text(entry_source(comp['name'],ordered),encoding='utf-8')
    return {"script":(generated,target,"server"),
            "plan":{"source":str(generated),"target":target.as_posix(),"sha256":sha256_file(generated),
                    "include_root":str(root),"include_files":len(staged)}}


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
    compiled=list(compiled)
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
    withheld_rows = []
    for row in plan.get("withheld", []):
        key = row["target"].casefold()
        if key in owner_of and owner_of[key] != row["module"]:
            continue
        withheld_rows.append((Path(row["path"]), Path(row["target"])))
    staged_withheld = projects.stage_withheld(raw, withheld_rows)
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
    # An image's pixels are never inside the fastfile; the client reads them from a bank the header
    # names or from images/ in the mod's folder, so the pack's own images travel beside it too.
    staged_images = projects.stage_images(raw, banks)
    # Compiled scripts also travel loose beside the package: on this base the engine executes
    # scripts/zm/*.gsc from the profile folder (`loaded successfully from raw`) and does not run
    # the rawfile copies inside mod.ff. Every accepted stock profile ships them this way.
    loose_scripts = []
    for rel in rawfiles:
        if rel.as_posix().startswith("scripts/") and rel.suffix.lower() in (".gsc", ".csc"):
            dest = banks / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(raw / rel, dest)
            loose_scripts.append(rel.as_posix())
    for m in seed_modules:
        for source, rel in m["seed"].get("loose_scripts", []):
            dest = banks / rel
            if dest.exists() or rel.as_posix() in loose_scripts:
                raise Failure(INPUT_INVALID, f"Two members ship the loose script {rel.as_posix()}; a pack carries one copy of each script",
                              "Record a file decision or drop one member.")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
            loose_scripts.append(rel.as_posix())
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
    return {**link, "unqualified": plan["unqualified"], "plan": "plan.json", "rawfiles_verified": len(rawfiles),
            "images_beside_package": staged_images, "mod_ff": link["packages"][0]["path"],
            "withheld_staged": len(staged_withheld),
            "seed_roots_verified": sum(len(m["seed"]["roots"]) for m in seed_modules),
            "embedded_assets": len(embedded), "referenced_assets": len(referenced), "localized_strings": len(strings),
            "soundbanks": sorted(p.name for p in banks.iterdir() if p.is_file() and p.name != "mod.ff"),
            "loose_scripts": loose_scripts,
            "name": comp["name"], "title": comp["title"], "base": comp["base"], "map": comp["map"], "base_member": plan["base_member"],
            "modules": [{"id": r["id"], "version": r["version"], "order": i + 1, "payload": r["payload"], "role": r["role"],
                         "parameters": r.get("parameters", {})}
                        for i, r in enumerate(plan["modules"])],
            "resource_totals": plan["resource_totals"], "budget": plan["budget"], "decisions": decided, "base_owned_names": base_owned_names,
            "scripts": len(compiled), "assets": len(loose), "seeds": len(seed_modules), "loads": len(loads),
            "install_hint": f"pat game install-mod <output>/{link['packages'][0]['path']} {comp['name']}  (copy the soundbanks under packages/ beside it; loading in game is a separate, authorized step)",
            "verification": "every recipe module's scripts compiled, one mod.ff linked against every seed and load, read back, every rawfile "
                            "byte-compared and every seed root found in the package; fit, budget and decisions come from declarations, not from the game"}
