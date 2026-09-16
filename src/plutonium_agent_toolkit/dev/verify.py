"""``module verify-declaration``: every promise a module declares, beside what its own bytes say.

Inert like ``module inspect``. The route reads one module: its declaration, the payload the
declaration names (a project recipe, a seed manifest or an adapter recipe), its GSC/CSC source,
and -- only when the caller supplies them -- a base's asset listings, a workspace's shelf of
declarations and the shipped per-map tables. It creates no job directory that outlives the call,
runs no backend, opens no network and writes nothing.

Every row says which method it used and how far that method can see: the honest ceiling per
promise is the table in docs/MODULES.md, "What a checker can verify, kind by kind". A row that a
method cannot decide is ``not_counted`` with the reason and, where one exists, the evidence that
would decide it -- never a guess dressed as a verdict.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from bisect import bisect_left
from pathlib import Path, PureWindowsPath

from ..core.errors import INPUT_INVALID, INVALID_ARGUMENTS, Failure
from ..core.jobs import Job
from . import adapters, compositions, ledger, projects, targets

PROTOCOL = "pat.module-verify/1"
OUTCOMES = ("agrees", "declared_not_observed", "observed_not_declared", "partial", "not_counted")

MAX_SOURCE_FILES = 256
MAX_SOURCE_BYTES = 1024 * 1024
MAX_LISTING_FILES = 64

GIT_TIMEOUT = 20
# The evidence rows a version bump is measured from: the ones that carry the hash of a package
# somebody actually built, tested or played. A lineage or an authored row names no package.
VERSION_ROW_TYPES = ("built-alone", "game-tested", "player-accepted")
SEMANTIC_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)\Z")
# What the folder fingerprint leaves out, by module-relative path: a trailing "/" is a top-level
# directory, a trailing "*" a name prefix, anything else an exact name. These are build outputs,
# donor payloads and prose -- not the module's authored bytes -- so a rebuild, a re-fetched donor
# or an edited README must never read as a source change that owes a version bump.
FINGERPRINT_EXCLUDE = ("evidence.json", "build-inputs.json", "inputs.json",
                       "docs/", "prepared/", "assets/", "README*")

# The zone namespaces the base and the map already own scripts and tables in. A staged path under
# one of them that no listing and no table calls base-owned is new, not proven new: it is listed
# under stages.new_in_base_namespace so an author sees what a listing would have judged.
BASE_NAMESPACE = ("maps/", "clientscripts/", "common_scripts/", "codescripts/", "aitype/",
                  "animtrees/", "animstatedefs/", "weapons/")
ENGINE_TABLES = "accuracy/"
ENGINE_TABLE_NOTE = ("No base zone listing carries an accuracy/ row: the engine reads those graphs from its own "
                     "search path when a WeaponDef is compiled, not from a fastfile. A member delivering one as a "
                     "rawfile spends a rawfile slot on a file that overrides nothing the pack can see; withhold it "
                     "with \"deliver\": false when a compiled asset already reads it.")

WEAPON_REGISTRARS = ("include_zombie_weapon", "add_zombie_weapon", "register_tactical_grenade_for_level")
# The call site is matched in masked code (a commented-out registration is not a registration);
# the name it registers is read from the literal the mask blanked, at the same offset.
REGISTRAR_CALL = re.compile(r"(?<![\w])(?:" + "|".join(WEAPON_REGISTRARS) + r")\s*\(", re.I)
HUD_CONSTRUCTORS = r"newclienthudelem|newhudelem|createfontstring|createserverfontstring|createicon"
HUD_CALL = re.compile(r"(?<![\w])(?:" + HUD_CONSTRUCTORS + r")\s*\(", re.I)
QUALIFIED_CALL = re.compile(r"([A-Za-z_][A-Za-z0-9_\\/]*)::[A-Za-z_]")
STRING_REFERENCE = re.compile(r"^\s*REFERENCE\s+([A-Z0-9_]{1,128})\s*$", re.M)

# The kinds whose names a regex can only find as a literal: presence of the id, never proof that
# the id was registered (registration goes through another module's function with the id as one
# argument). Every row for these is `partial` or `declared_not_observed`, never `agrees`.
NAME_KINDS = ("perks", "gobblegums", "powerups", "equipment")
# The provides kinds a proposal may widen: the ones whose method sees the whole truth.
FULL_KINDS = ("scripts", "rawfiles", "localize", "soundbanks")
# Path-valued kinds are compared casefolded: a declaration's zone paths are lowercased by the
# validator and a recipe target keeps the spelling its author wrote.

# A role's footprint in bytes, in one place so it is read and extended as data. `source` matches
# comment-masked source, `functions` a replaced function target, `staged` a staged target or asset
# name. A footprint is never proof that the module should *own* the role; that stays the author's
# promise, and a declared role with its footprint present is `partial`.
ROLE_FOOTPRINTS = {
    "hud": {"how": "HUD element constructors in source, or a staged .menu",
            "source": re.compile(r"(?<![\w])(?:" + HUD_CONSTRUCTORS + r")\s*\(", re.I),
            "staged": re.compile(r"\.menu\Z", re.I)},
    "box": {"how": "a replaced _zm_magicbox function, the box weight hook, or a treasure_chest_ call",
            "source": re.compile(r"level\.customrandomweaponweights|(?<![\w])treasure_chest_[a-z0-9_]*\s*\(", re.I),
            "functions": re.compile(r"^maps/mp/zombies/_zm_magicbox::")},
    "loadscreen": {"how": "a staged target or asset name naming a load screen",
                   "staged": re.compile(r"loadscreen", re.I)},
    "boss": {"how": "a replaced _zm_ai_ function or a staged aitype/ target",
             "functions": re.compile(r"^[a-z0-9_/]*_zm_ai_[a-z0-9_]*::"),
             "staged": re.compile(r"^aitype/", re.I)},
    "perk-machines": {"how": "a replaced _zm_perks function, or a staged rotation or Wunderfizz script",
                      "functions": re.compile(r"^maps/mp/zombies/_zm_perks::"),
                      "staged": re.compile(r"(?:^|/)[a-z0-9_]*(?:rotation|wunderfizz)[a-z0-9_]*\.(?:gsc|csc)\Z", re.I)},
    "perk-art": {"how": "a level. name defining perk art or a perk shader",
                 "source": re.compile(r"level\.[a-z0-9_]*(?:perk_art|perk_shader)[a-z0-9_]*", re.I)},
}

# One row per field this route reads nothing for, with the reason from docs/MODULES.md.
UNREAD_FIELDS = {
    "menu_route": "nothing in this route reads a menu tree",
    "tags": "nothing in this route: a tag is a label a person chose, not a byte",
    "placements": "nothing in this route reads a location table (docs/target-sets.md)",
    "parameters": "nothing in this route: what consumes a parameter is a build fact",
    "bases": "nothing in this route: a base fit is a receipt, not a declaration read",
    "maps": "nothing in this route: a map fit is a receipt, not a declaration read",
}


# ----- lexical helpers ---------------------------------------------------------------------

def _code_strings(text: str) -> list[tuple[int, str]]:
    """Every string literal that is code, with the offset of its opening quote.

    The same lexical rules as ``compositions.mask_gsc``, which blanks a literal's own bytes: a
    caller that must read the value (a weapon name, a localized reference, a power-up id) reads it
    here, and a caller that must see only executable code masks there. A literal inside a comment
    is not code and is not returned.
    """
    out: list[tuple[int, str]] = []
    index, length = 0, len(text)
    while index < length:
        char = text[index]
        if char == "/" and index + 1 < length and text[index + 1] == "/":
            index += 2
            while index < length and text[index] != "\n":
                index += 1
        elif char == "/" and index + 1 < length and text[index + 1] == "*":
            index += 2
            while index < length and not (text[index] == "*" and index + 1 < length and text[index + 1] == "/"):
                index += 1
            index += 2
        elif char in ('"', "'"):
            quote, start, chars = char, index, []
            index += 1
            while index < length and text[index] != quote:
                if text[index] == "\\" and index + 1 < length:
                    chars.append(text[index + 1])
                    index += 2
                    continue
                chars.append(text[index])
                index += 1
            index += 1
            out.append((start, "".join(chars)))
        else:
            index += 1
    return out


class Source:
    """One module's readable source, masked once: every scan reads these, never the files again."""

    def __init__(self, files: list[tuple[str, str]]):
        self.files = files
        self.masked = [(name, compositions.mask_gsc(text)) for name, text in files]
        self.literals: set[str] = set()
        self.localize: set[str] = set()
        self.weapons: set[str] = set()
        self.hud = 0
        self.calls: set[str] = set()
        for (name, text), (_, masked) in zip(files, self.masked):
            strings = _code_strings(text)
            positions = {start: value for start, value in strings}
            self.literals.update(value for _, value in strings)
            for start, value in strings:
                if start and masked[start - 1] == "&":
                    self.localize.add(value)
            starts = sorted(positions)
            for match in REGISTRAR_CALL.finditer(masked):
                index = bisect_left(starts, match.end())
                if index < len(starts) and not text[match.end():starts[index]].strip():
                    # The first argument, and only when nothing but whitespace stands before it.
                    self.weapons.add(positions[starts[index]])
            self.hud += len(HUD_CALL.findall(masked))
            for path in QUALIFIED_CALL.findall(masked):
                self.calls.add(path.replace("\\", "/").casefold())

    @property
    def literal_text(self) -> str:
        """Every code literal as one blob: a path named inside a longer string is found here, and a
        path named in a comment is not there to find."""
        return "\n".join(sorted(self.literals))

    def replacements(self) -> set[str]:
        found: set[str] = set()
        for _, text in self.files:
            found |= compositions.scan_replacements(text)
        return found

    def matches(self, pattern) -> bool:
        return any(pattern.search(masked) for _, masked in self.masked)


def _read_source(paths: list[Path]) -> tuple[list[tuple[str, str]], list[str]]:
    """Read at most ``MAX_SOURCE_FILES`` scripts of at most ``MAX_SOURCE_BYTES`` each; what was
    left out is reported, never silently dropped."""
    files: list[tuple[str, str]] = []
    skipped: list[str] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if len(files) >= MAX_SOURCE_FILES:
            skipped.append(f"{path.name}: more than {MAX_SOURCE_FILES} source files")
            continue
        try:
            if path.is_symlink() or not path.is_file():
                continue
            if path.stat().st_size > MAX_SOURCE_BYTES:
                skipped.append(f"{path.name}: larger than {MAX_SOURCE_BYTES} bytes")
                continue
            files.append((path.name, path.read_text(encoding="utf-8", errors="replace")))
        except OSError as exc:
            skipped.append(f"{path.name}: {exc.strerror or exc}")
    return files, skipped


def _source_tree(directory: Path) -> list[Path]:
    """Every ``*.gsc``/``*.csc`` under the module's own ``src/``, sorted; links are not followed."""
    root = directory / "src"
    if root.is_symlink() or not root.is_dir():
        return []
    found = [p for p in sorted(root.rglob("*")) if p.suffix.lower() in (".gsc", ".csc")]
    return found[:MAX_SOURCE_FILES + 1]


# ----- rows --------------------------------------------------------------------------------

def _row(field: str, declared, observed, how: str, outcome: str, note: str | None = None) -> dict:
    row = {"field": field, "declared": declared, "observed": observed, "how": how, "outcome": outcome}
    if note:
        row["note"] = note
    return row


def _compare(rows: list[dict], field: str, declared, observed, how: str, *, matched: str = "agrees",
             note: str | None = None, unavailable: str | None = None, casefold: bool = False) -> None:
    """One row per direction the two lists differ in, plus one row for what matched, so a gate
    reading the result sees every field this route checked and not only its complaints."""
    declared = list(declared)
    if unavailable:
        rows.append(_row(field, sorted(declared), [], how, "not_counted", unavailable))
        return
    left = {(n.casefold() if casefold else n) for n in declared}
    right = {(n.casefold() if casefold else n) for n in observed}
    both, missing, extra = sorted(left & right), sorted(left - right), sorted(right - left)
    if both:
        rows.append(_row(field, both, both, how, matched, note))
    if missing:
        rows.append(_row(field, missing, [], how, "declared_not_observed", note))
    if extra:
        rows.append(_row(field, [], extra, how, "observed_not_declared", note))


# ----- the shelf ---------------------------------------------------------------------------

def _shelf(workspace: str | None) -> dict[str, dict]:
    """Every declaration under ``<workspace>/modules``, by id: the same bounded, declaration-only
    read ``compositions.shelf_services`` does, keeping the whole metadata because a dependency's
    kind is judged against its scripts, its registered names and its banks alike."""
    if not workspace:
        return {}
    root = Path(workspace).expanduser() / "modules"
    if not root.is_dir():
        return {}
    rows: dict[str, dict] = {}
    for index, child in enumerate(sorted(root.iterdir())):
        if index >= compositions.MAX_SHELF_ENTRIES:
            break
        path = child / "module.json"
        if child.is_symlink() or not path.is_file() or path.is_symlink():
            continue
        try:
            if path.stat().st_size > compositions.MAX_DECLARATION_BYTES:
                continue
            meta = compositions.validate_declaration_metadata(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, Failure):
            continue
        rows.setdefault(meta["id"], meta)
    return rows


# ----- observation -------------------------------------------------------------------------

def _listing_files(directories: list[Path]) -> list[Path]:
    found: list[Path] = []
    for directory in directories:
        if directory.is_symlink() or not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if len(found) >= MAX_LISTING_FILES:
                return found
            if path.is_symlink() or not path.is_file():
                continue
            if path.suffix.lower() in (".txt", ".csv"):
                found.append(path)
    return found


def _classify(staged: list[str], base_names: set[str], map_scripts: set[str], native: set[str],
              have_listing: bool, have_table: bool) -> tuple[list[dict], list[dict], list[str], list[str]]:
    """Every staged target against the two sources of fact: the base's own listings and the
    shipped per-map tables. Returns the base-owned rows with their evidence, the engine tables,
    the paths that are new in a base namespace, and the paths nothing on this machine can decide."""
    owned: list[dict] = []
    engine: list[dict] = []
    new: list[str] = []
    undecided: list[str] = []
    for path in staged:
        key = path.casefold()
        if key.startswith(ENGINE_TABLES):
            engine.append({"path": path, "note": ENGINE_TABLE_NOTE})
            continue
        if have_listing and (f"rawfile,{key}" in base_names or f"script,{key}" in base_names):
            owned.append({"path": path, "owner": "base", "evidence": "listing"})
            continue
        if key in map_scripts:
            owned.append({"path": path, "owner": "map", "evidence": "table"})
            continue
        if key.startswith("weapons/") and key.split("/")[-1] in native:
            owned.append({"path": path, "owner": "map", "evidence": "table"})
            continue
        if key.startswith(BASE_NAMESPACE):
            # Listed regardless: a path no source calls base-owned is new in a namespace the base
            # owns, and when nothing on this machine could have decided it, it is also undecided.
            new.append(path)
            if not (have_listing or have_table):
                undecided.append(path)
    return owned, engine, new, undecided


def _staged(payload: str, compiled, loose, seed, adapter) -> tuple[list[str], list[str], list[str], list[str]]:
    """What this module puts in a zone: the script targets it compiles, the loose targets it
    delivers, and -- as ownership reads them -- an adapter's or a seed's script and rawfile roots.
    Also the asset names, which is where a load screen shows up."""
    staged: list[str] = []
    names: list[str] = []
    banks: list[str] = []
    aliases: list[str] = []
    if payload == "recipe" and compiled is not None:
        staged += [target.as_posix() for _source, target, _instance in compiled]
        for source, target, asset_type, name in loose:
            staged.append(target.as_posix())
            names.append(name)
            if asset_type == "soundbank":
                banks.append(name)
                if Path(source).suffix.lower() == ".csv":
                    aliases += adapters.read_aliases(Path(source), "verify")
    elif payload == "adapter" and adapter is not None:
        staged += [row["target"] for row in adapter["scripts"]] + list(adapter["rawfiles"])
        names += list(adapter["provides"].get("models", [])) + list(adapter["provides"].get("effects", []))
        if adapter["soundbank"]:
            banks.append(adapter["soundbank"])
        aliases += list(adapter["aliases"])
    elif payload == "seed" and seed is not None:
        for row in seed.get("roots", []):
            kind, _, name = row.partition(",")
            if kind in ("rawfile", "script"):
                staged.append(name)
            names.append(name)
        banks += list(seed.get("provides", {}).get("soundbanks", []))
    return sorted(set(staged)), sorted(set(names)), sorted(set(banks)), sorted(set(aliases))


def _observed_provides(payload: str, compiled, loose, seed, adapter, source: Source) -> dict[str, set[str]]:
    """What the payload and the source say this module provides, by kind."""
    out: dict[str, set[str]] = {kind: set() for kind in compositions.PROVIDES_KINDS}
    if payload == "recipe" and compiled is not None:
        out["scripts"].update(target.as_posix() for _s, target, _i in compiled)
        for path, target, asset_type, name in loose:
            if asset_type == "script":
                out["scripts"].add(name)
            elif asset_type == "rawfile":
                out["rawfiles"].add(target.as_posix())
                if target.suffix.lower() in (".gsc", ".csc"):
                    out["scripts"].add(target.as_posix())
            elif asset_type == "weapon":
                out["weapons"].add(name if name else target.stem)
            elif asset_type == "localize":
                try:
                    text = Path(path).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                out["localize"].update(STRING_REFERENCE.findall(text))
            elif asset_type == "soundbank":
                out["soundbanks"].add(name)
                if Path(path).suffix.lower() == ".csv":
                    out["aliases"].update(adapters.read_aliases(Path(path), "verify"))
            elif asset_type == "xmodel":
                out["models"].add(name)
            elif asset_type == "fx":
                out["effects"].add(name)
    elif payload == "adapter" and adapter is not None:
        for kind, names in adapter["provides"].items():
            out.setdefault(kind, set()).update(names)
        out["weapons"].update(adapter["weapons"])
        out["localize"].update(adapter["localize"])
        if adapter["soundbank"]:
            out["soundbanks"].add(adapter["soundbank"])
        out["aliases"].update(adapter["aliases"])
    elif payload == "seed" and seed is not None:
        for kind, names in seed.get("provides", {}).items():
            out.setdefault(kind, set()).update(names)
        for row in seed.get("roots", []):
            kind, _, name = row.partition(",")
            if kind == "script" or (kind == "rawfile" and name.lower().endswith((".gsc", ".csc"))):
                out["scripts"].add(name)
    out["weapons"].update(source.weapons)
    out["localize"].update(source.localize)
    return out


# ----- the version, against the newest evidence row ----------------------------------------

def _excluded(name: str) -> bool:
    """True when a module-relative path is one FINGERPRINT_EXCLUDE names."""
    for rule in FINGERPRINT_EXCLUDE:
        if rule.endswith("/"):
            if name.startswith(rule):
                return True
        elif rule.endswith("*"):
            if name.rpartition("/")[2].startswith(rule[:-1]):
                return True
        elif name == rule:
            return True
    return False


def _inside(value) -> bool:
    """A forward-slash relative path that stays inside the module directory."""
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = Path(value)
    return not (path.is_absolute() or PureWindowsPath(value).anchor or ".." in path.parts)


def _json(raw: bytes | None):
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError, UnicodeError):
        return None


def _fingerprint_names(declaration: dict, recipe, src: list[str], present) -> list[str]:
    """The module-relative paths one fingerprint covers, sorted: the declaration, the payload it
    names, the sources a recipe names inside the module, everything under ``src/`` and the test
    contract, minus FINGERPRINT_EXCLUDE and minus whatever ``present`` says is not there."""
    names = {"module.json", "test-contract.json"}
    for key in ("recipe", "seed", "tests"):
        if _inside(declaration.get(key)):
            names.add(declaration[key])
    for key in ("scripts", "assets"):
        for row in (recipe or {}).get(key, []) if isinstance(recipe, dict) else []:
            if isinstance(row, dict) and _inside(row.get("source")):
                names.add(row["source"])
    names.update(src)
    return sorted(n for n in names if not _excluded(n) and present(n))


def _pairs_digest(pairs: list[tuple[str, str]]) -> str:
    return hashlib.sha256("\n".join(f"{name}\x00{digest}" for name, digest in pairs).encode("utf-8")).hexdigest()


def _bounded_read(path: Path) -> bytes | None:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
            return None
        return path.read_bytes()
    except OSError:
        return None


def _src_tree(directory: Path) -> tuple[list[str], str | None]:
    """Every file under the module's own ``src/``, module-relative; links are not followed and
    symlinked directories are not descended into."""
    root = directory / "src"
    if root.is_symlink() or not root.is_dir():
        return [], None
    found: list[str] = []
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs.sort()
        for name in sorted(files):
            path = Path(base) / name
            if path.is_symlink() or not path.is_file():
                continue
            if len(found) >= MAX_SOURCE_FILES:
                return [], f"more than {MAX_SOURCE_FILES} files under src/"
            found.append(path.relative_to(directory).as_posix())
    return sorted(found), None


def folder_fingerprint(directory: Path) -> dict:
    """The module's authored bytes as one digest.

    SHA-256 over the sorted list of (module-relative path, that file's SHA-256) for the files
    ``_fingerprint_names`` selects. Returns ``{"sha256", "files"}``; when a bound is hit (more
    than ``MAX_SOURCE_FILES`` files under ``src/``, or a file larger than ``MAX_SOURCE_BYTES``)
    ``sha256`` is None and ``reason`` says which, because half a folder is not a fingerprint.
    """
    directory = Path(directory)
    declaration = _json(_bounded_read(directory / "module.json")) or {}
    recipe = _json(_bounded_read(directory / declaration["recipe"])) if _inside(declaration.get("recipe")) else None
    src, reason = _src_tree(directory)
    if reason:
        return {"sha256": None, "files": 0, "reason": reason}

    def here(name: str) -> bool:
        path = directory / name
        return path.is_file() and not path.is_symlink()

    pairs = []
    for name in _fingerprint_names(declaration, recipe, src, here):
        data = _bounded_read(directory / name)
        if data is None:
            return {"sha256": None, "files": 0, "reason": f"{name} could not be read within {MAX_SOURCE_BYTES} bytes"}
        pairs.append((name, hashlib.sha256(data).hexdigest()))
    return {"sha256": _pairs_digest(pairs), "files": len(pairs)}


def _git(directory: Path, args: list[str]) -> bytes | None:
    """One bounded ``git`` run, captured, never raising: None when git fails, times out or is not
    there. Nothing here writes to the repository."""
    try:
        done = subprocess.run(["git", "-C", str(directory), *args], capture_output=True, timeout=GIT_TIMEOUT)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _git_text(directory: Path, args: list[str]) -> str | None:
    out = _git(directory, args)
    return None if out is None else out.decode("utf-8", errors="replace")


def _commit_fingerprint(directory: Path, prefix: str, commit: str) -> dict:
    """The same fingerprint, over the module directory as one commit recorded it. Git's blob ids
    are SHA-1 of a different preimage, so every file's content is read back and hashed here."""
    listing = _git(directory, ["ls-tree", "-r", "-z", "--full-tree", commit,
                               *(["--", prefix.rstrip("/")] if prefix else [])])
    if listing is None:
        return {"sha256": None, "files": 0, "reason": f"commit {commit[:8]} has no readable tree here"}
    blobs: dict[str, str] = {}
    for record in listing.decode("utf-8", errors="replace").split("\0"):
        meta, _, path = record.partition("\t")
        parts = meta.split()
        # Regular files only: a symlink, a gitlink or a submodule is not a byte of this module.
        if len(parts) != 3 or parts[1] != "blob" or parts[0] not in ("100644", "100755"):
            continue
        if not path.startswith(prefix):
            continue
        blobs[path[len(prefix):]] = parts[2]
    declaration = _json(_git(directory, ["cat-file", "-p", blobs["module.json"]])) if "module.json" in blobs else None
    declaration = declaration if isinstance(declaration, dict) else {}
    recipe_path = declaration.get("recipe")
    recipe = (_json(_git(directory, ["cat-file", "-p", blobs[recipe_path]]))
              if _inside(recipe_path) and recipe_path in blobs else None)
    src = sorted(n for n in blobs if n.startswith("src/"))
    if len(src) > MAX_SOURCE_FILES:
        return {"sha256": None, "files": 0, "reason": f"more than {MAX_SOURCE_FILES} files under src/ at {commit[:8]}"}
    pairs = []
    for name in _fingerprint_names(declaration, recipe, src, blobs.__contains__):
        data = _git(directory, ["cat-file", "-p", blobs[name]])
        if data is None or len(data) > MAX_SOURCE_BYTES:
            return {"sha256": None, "files": 0, "reason": f"{name} at {commit[:8]} could not be read within {MAX_SOURCE_BYTES} bytes"}
        pairs.append((name, hashlib.sha256(data).hexdigest()))
    return {"sha256": _pairs_digest(pairs), "files": len(pairs)}


def _newest_packaged_row(directory: Path) -> tuple[dict | None, str | None]:
    """The newest ledger row carrying a ``package_sha256`` of a type that names a real package,
    newest by ``at`` and, where two share one, by row order. A module with no ledger is not a
    fault: it is a row this route could not count, with the reason."""
    path = directory / ledger.FILENAME
    if path.is_symlink() or not path.is_file():
        return None, "no ledger"
    try:
        _raw, data = ledger.read(path)
    except Failure as exc:
        return None, f"the ledger could not be read: {exc.message[:200]}"
    book, _diagnostics = ledger.validate(data)
    rows = (book or {}).get("rows", [])
    candidates = [(index, row) for index, row in enumerate(rows)
                  if row.get("type") in VERSION_ROW_TYPES and row.get("package_sha256")]
    if not candidates:
        return None, f"no {', '.join(VERSION_ROW_TYPES)} row in the ledger carries a package_sha256"
    return max(candidates, key=lambda pair: (pair[1].get("at", ""), pair[0]))[1], None


def version_row(directory: Path, metadata: dict, rows: list[dict], propose: bool) -> tuple[str | None, str | None]:
    """The declared version against the commit that introduced the newest evidence row.

    A fix that lands must be visible. When the module's authored bytes have moved since the commit
    that first carried the newest ``package_sha256`` in its ledger, and ``version`` still reads
    what it read at that commit, the row is ``declared_not_observed`` and says to bump it. Every
    way this cannot be decided -- no ledger, no git, no repository, no such commit -- is
    ``not_counted`` with the reason, never a guess. Returns the proposed version and the proposal
    note ``--propose`` should carry, either of which may be None.
    """
    field, declared = "/version", metadata["version"]
    how = "the folder's fingerprint against the commit that introduced the newest evidence row carrying a package_sha256"

    def not_counted(reason: str) -> tuple[None, None]:
        rows.append(_row(field, [declared], [], how, "not_counted", reason))
        return None, None

    row, reason = _newest_packaged_row(directory)
    if row is None:
        return not_counted(reason)
    package = row["package_sha256"]
    if shutil.which("git") is None:
        return not_counted("git is not on this machine")
    prefix = _git_text(directory, ["rev-parse", "--show-prefix"])
    if prefix is None:
        return not_counted("the module directory is not inside a git repository")
    prefix = prefix.strip()
    # --reverse, so a ledger that was rewritten still points at the commit that first added the row.
    log = _git_text(directory, ["log", "--format=%H", "--reverse", "-S", package, "--", ledger.FILENAME])
    commits = (log or "").split()
    if not commits:
        return not_counted(f"no commit in this repository added the evidence row's package_sha256 ({package[:8]})")
    commit, short = commits[0], commits[0][:8]
    reference = _json(_git(directory, ["show", f"{commit}:{prefix}module.json"]))
    if not isinstance(reference, dict) or not isinstance(reference.get("version"), str):
        return not_counted(f"commit {short} carries no readable module.json for this directory")
    was = reference["version"]
    now, then = folder_fingerprint(directory), _commit_fingerprint(directory, prefix, commit)
    if now["sha256"] is None:
        return not_counted(f"the folder could not be fingerprinted: {now['reason']}")
    if then["sha256"] is None:
        return not_counted(f"the folder at {short} could not be fingerprinted: {then['reason']}")
    if now["sha256"] == then["sha256"]:
        rows.append(_row(field, [declared], [declared], how, "agrees",
                         f"the folder's bytes are the bytes of commit {short}"))
        return None, None
    observed = [f"{was} at {short}"]
    if declared != was:
        rows.append(_row(field, [declared], observed, how, "agrees", f"version moved since {short}"))
        return None, None
    rows.append(_row(field, [declared], observed, how, "declared_not_observed",
                     f"the folder's bytes changed since the newest evidence row ({package[:8]}, commit {short}) "
                     "and version did not move: bump it"))
    if not propose:
        return None, None
    match = SEMANTIC_VERSION.match(declared)
    if not match:
        return None, (f"version: {declared!r} is not MAJOR.MINOR.PATCH, so no bump is proposed; give the "
                      "module a semantic version and move it by hand")
    return f"{match[1]}.{match[2]}.{int(match[3]) + 1}", None


# ----- the route ---------------------------------------------------------------------------

def _target(value: str | None) -> tuple[str, str] | None:
    if value is None:
        return None
    if not compositions.RECIPE_TARGET.match(value):
        raise Failure(INVALID_ARGUMENTS, "--target is '<foundation>/<map>', the foundation id as foundations/<id>.json names it",
                      "Example: --target stock/zm_transit")
    foundation, _, map_id = value.partition("/")
    return foundation, map_id


def verify(directory: Path, *, workspace: str | None = None, base_listings=(), target: str | None = None,
           propose: bool = False) -> dict:
    """One module's promises beside its own bytes. Writes nothing; returns the report."""
    directory = Path(directory).expanduser().absolute()
    pair = _target(target)
    path = directory / "module.json"
    raw = compositions._read_inspection(path)
    digest = hashlib.sha256(raw).hexdigest()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError) as exc:
        raise Failure(INPUT_INVALID, f"Declaration is not valid JSON: {path}", field="/") from exc
    metadata = compositions.validate_declaration_metadata(data, where=f"module.json in {directory.name}")

    # An inert route with a loader that takes a Job: the payload loaders hash what they read into a
    # Job, and a Job owns one output directory. The directory is a temporary one that is removed
    # before this function returns, its receipt is never finished and nothing it holds is reported,
    # so the route still writes nothing that survives the call.
    payload = metadata["payload"]
    recipe_data = compiled = loose = seed = adapter = None
    unavailable = None
    with tempfile.TemporaryDirectory(prefix="pat-verify-") as scratch:
        job = Job(Path(scratch) / "job", "module verify-declaration", ["pat", "module", "verify-declaration"], timeout=600)
        source_paths: list[Path] = []
        try:
            loaded = compositions.load_declaration(directory, job, pair)
            if loaded["adapter"] is not None:
                payload, adapter = "adapter", loaded["adapter"]
                source_paths += [Path(row["source"]) for row in adapter["scripts"]]
            elif loaded["recipe"] is not None:
                payload = "recipe"
                recipe_data, compiled, loose, _loads = projects.load_recipe(loaded["recipe"], job)
                source_paths += [Path(p) for p, _t, _i in compiled]
            else:
                payload, seed = "seed", loaded["seed"]
        except Failure as exc:
            # A private module whose package is on another machine, or a recipe input that is not
            # here: the declaration-side rows are still worth reporting, and every observation the
            # payload would have supplied says why it was not counted.
            unavailable = f"recipe inputs are not on this machine ({exc.message[:200]})"
        source_paths += _source_tree(directory)
        files, skipped = _read_source(source_paths)
    source = Source(files)

    listing_dirs = [Path(d).expanduser() for d in base_listings]
    if workspace and pair:
        listing_dirs += targets.base_listing_dirs(Path(workspace).expanduser(), pair[0])
    listings = _listing_files(listing_dirs)
    base_names: set[str] = set()
    if listings:
        base_names, _shadowable, _zones = compositions._base_owned(listings)
    map_scripts: set[str] = set()
    native: set[str] = set()
    if pair:
        from . import knowledge
        try:
            row = knowledge.load("map-scripts.json")["maps"].get(pair[1])
        except Failure:
            row = None
        if row and row.get("foundation") == pair[0]:
            map_scripts = {p.casefold() for p in row["scripts"]}
        native = {w.partition(",")[2] for w in compositions.native_weapons(pair[1], pair[0])}

    staged, asset_names, banks, aliases = _staged(payload, compiled, loose, seed, adapter)
    observed = _observed_provides(payload, compiled, loose, seed, adapter, source)
    owned, engine, new_paths, undecided = _classify(staged, base_names, map_scripts, native,
                                                    bool(listings), bool(map_scripts or native))
    shelf = _shelf(workspace)
    rows: list[dict] = []
    declared = metadata["provides"]
    payload_note = None if not unavailable else unavailable
    no_source = "no GSC or CSC source is on this machine" if not files else None

    # ----- provides --------------------------------------------------------------------
    _compare(rows, "/provides/scripts", declared.get("scripts", []), observed["scripts"],
             "recipe script and loose-script targets, seed or adapter script roots",
             unavailable=payload_note, casefold=True)
    _compare(rows, "/provides/rawfiles", declared.get("rawfiles", []), observed["rawfiles"],
             "delivered rawfile targets, seed and adapter rawfile roots", unavailable=payload_note, casefold=True)
    _compare(rows, "/provides/weapons", declared.get("weapons", []), observed["weapons"],
             "recipe weapon rows, adapter weapons, seed weapon roots and the registration literals in source",
             matched="agrees" if payload in ("seed", "adapter") else "partial",
             note=None if payload in ("seed", "adapter") else "a weapon registered through a computed name is invisible to this method",
             unavailable=payload_note)
    _compare(rows, "/provides/localize", declared.get("localize", []), observed["localize"],
             "the REFERENCE lines of every .str the payload names, the adapter localize map, &\"NAME\" in source",
             unavailable=payload_note)
    _compare(rows, "/provides/soundbanks", declared.get("soundbanks", []), observed["soundbanks"],
             "recipe soundbank rows, adapter bank, seed bank names", unavailable=payload_note)
    _compare(rows, "/provides/aliases", declared.get("aliases", []), observed["aliases"],
             "the alias CSV of every soundbank row",
             unavailable=payload_note or (None if observed["aliases"] or not declared.get("aliases")
                                          else "no alias CSV is on this machine"))
    for kind in ("models", "effects"):
        _compare(rows, f"/provides/{kind}", declared.get(kind, []), observed[kind],
                 f"recipe asset rows of type {'xmodel' if kind == 'models' else 'fx'}, seed manifest",
                 matched="agrees" if payload == "seed" else "partial",
                 note=None if payload == "seed" else f"a recipe's {kind} pulled in by a WeaponDef rather than rooted are invisible to this method",
                 unavailable=payload_note)
    for kind in NAME_KINDS:
        names = declared.get(kind, [])
        if not names:
            continue
        if no_source:
            rows.append(_row(f"/provides/{kind}", sorted(names), [], "the id as a string literal in source", "not_counted", no_source))
            continue
        present = sorted(n for n in names if n in source.literals)
        absent = sorted(n for n in names if n not in source.literals)
        if present:
            rows.append(_row(f"/provides/{kind}", present, present, "the id as a string literal in source", "partial",
                             "presence of the id, not proof it was registered"))
        if absent:
            rows.append(_row(f"/provides/{kind}", absent, [], "the id as a string literal in source", "declared_not_observed"))

    # ----- replacement -----------------------------------------------------------------
    _compare(rows, "/replaces/functions", metadata["replaces"]["functions"], source.replacements(),
             "replaceFunc(path::fn in comment- and string-masked source, both directions",
             unavailable=no_source,
             note="a computed target is invisible, as it is to the planner")

    files_field = "/replaces/files"
    declared_files = [p.casefold() for p in metadata["replaces"]["files"]]
    owned_paths = {row["path"].casefold() for row in owned}
    staged_keys = {p.casefold() for p in staged}
    undecided_keys = {p.casefold() for p in undecided}
    how_files = "every staged target classified base-owned by a base listing or a shipped per-map table"
    if unavailable:
        rows.append(_row(files_field, sorted(declared_files), [], how_files, "not_counted", unavailable))
    else:
        agreed = sorted(p for p in declared_files if p in owned_paths)
        missing = sorted(p for p in declared_files if p not in owned_paths and p not in undecided_keys)
        extra = sorted(p for p in owned_paths if p not in declared_files)
        if agreed:
            rows.append(_row(files_field, agreed, agreed, how_files, "agrees"))
        if missing:
            rows.append(_row(files_field, missing, [], how_files, "declared_not_observed",
                             "no staged target of this module carries the path, or the evidence says the base does not"))
        if extra:
            rows.append(_row(files_field, [], extra, how_files, "observed_not_declared",
                             "a staged path the base or the map already carries must be declared under replaces.files"))
        for p in sorted(undecided_keys):
            # Staged in a namespace the base owns, with neither a listing nor a table here to say
            # whether the base carries it. The row names the evidence that would decide it.
            rows.append(_row(files_field, [p] if p in declared_files else [], [] if p in declared_files else [p],
                             how_files, "not_counted",
                             "no base listing and no per-map table on this machine covers this path; a listing of "
                             "the base's zones (--base-listings) or --target <foundation>/<map> would decide it"))

    # ----- dependencies ----------------------------------------------------------------
    payload_text = ""
    if recipe_data is not None:
        payload_text = json.dumps(recipe_data)
    elif adapter is not None:
        payload_text = json.dumps(adapter["provides"])
    for index, dep in enumerate(metadata["dependencies"]):
        field = f"/dependencies/{index}"
        kind = metadata["dependency_kinds"].get(dep, {}).get("kind")
        note = f"dependency {dep}"
        how = "the dependency's own declaration under --workspace, against this module's source and staged targets"
        if kind == "runtime":
            rows.append(_row(field, ["runtime"], [], "nothing; a runtime edge is what only the engine shows",
                             "not_counted", f"{note}: declaration-only, and why is required"))
            continue
        if not workspace:
            rows.append(_row(field, [kind] if kind else [], [], how, "not_counted",
                             f"{note}: dependency declarations need --workspace"))
            continue
        other = shelf.get(dep)
        if other is None:
            rows.append(_row(field, [kind] if kind else [], [], how, "not_counted",
                             f"{note}: no declaration for it under <workspace>/modules"))
            continue
        provides = other["provides"]
        stems = {Path(s).stem.casefold() for s in provides.get("scripts", [])}
        paths = {Path(s).with_suffix("").as_posix().casefold() for s in provides.get("scripts", [])}
        call = bool(source.calls & (stems | paths))
        registered = {n for key in NAME_KINDS + ("weapons", "localize") for n in provides.get(key, [])}
        named = any(n in source.literals or (payload_text and f'"{n}"' in payload_text) for n in registered)
        shared = {n for key in compositions.SHAREABLE_KINDS for n in provides.get(key, [])}
        mine = staged_keys | {b.casefold() for b in banks} | {a.casefold() for a in aliases}
        copied = {n for n in shared if n.casefold() in mine}
        blob = source.literal_text
        referenced = any(n in blob for key in ("rawfiles", "soundbanks", "aliases") for n in provides.get(key, []))
        service = not copied and (call or referenced)
        found = sorted({k for k, seen in (("call", call), ("name", named), ("service", service)) if seen})
        if kind is None:
            rows.append(_row(field, [], found, how, "agrees" if found else "declared_not_observed",
                             f"{note}: an entry with no kind is checked against all three observable kinds"))
        else:
            rows.append(_row(field, [kind], found, how, "agrees" if kind in found else "declared_not_observed", note))

    # ----- roles, service, contract, conflicts -----------------------------------------
    declared_roles = set(metadata["exclusive"])
    replaced = set(metadata["replaces"]["functions"]) | source.replacements()
    footprint_notes: list[str] = []
    for role, rules in ROLE_FOOTPRINTS.items():
        evidence: list[str] = []
        if "source" in rules and source.matches(rules["source"]):
            evidence.append("source")
        if "functions" in rules and any(rules["functions"].search(t) for t in replaced):
            evidence.append("replaces.functions")
        if "staged" in rules and any(rules["staged"].search(t) for t in staged + asset_names):
            evidence.append("staged")
        field = "/exclusive"
        if role in declared_roles and evidence:
            footprint_notes.append(f"{role}: {rules['how']}")
            rows.append(_row(field, [role], [role], rules["how"], "partial",
                             f"the footprint is present ({', '.join(evidence)}); that the module should own the role stays its author's promise"))
        elif role in declared_roles:
            rows.append(_row(field, [role], [], rules["how"], "declared_not_observed"))
        elif evidence:
            footprint_notes.append(f"{role}: {rules['how']}")
            rows.append(_row(field, [], [role], rules["how"], "observed_not_declared",
                             f"this looks like a {role} owner ({', '.join(evidence)})"))

    shareable = any(declared.get(kind) for kind in compositions.SHAREABLE_KINDS)
    if metadata["service"]:
        rows.append(_row("/service", [True], [True],
                         "shareable provides present, no weapon provided",
                         "agrees" if (shareable or metadata["exclusive"]) and not declared.get("weapons") else "declared_not_observed",
                         "the rule is checked; the intent is declaration-only"))
    elif "shared-service" in metadata["tags"]:
        rows.append(_row("/service", [], [True], "the older shared-service tag, read as the same mark for one release",
                         "observed_not_declared", "declare service: true; the tag is read for one more release"))

    hud_declared = metadata["resource_contract"].get("hud", 0)
    if no_source:
        rows.append(_row("/resource_contract/hud", [hud_declared], [], "count of HUD-element constructors in source",
                         "not_counted", no_source))
    else:
        rows.append(_row("/resource_contract/hud", [hud_declared], [source.hud],
                         "count of HUD-element constructors in source, as a floor",
                         "observed_not_declared" if hud_declared == 0 and source.hud else "partial",
                         "a floor, never the total"))

    for index, other_id in enumerate(metadata["conflicts"]):
        field = f"/conflicts/{index}"
        other = shelf.get(other_id)
        shared_roles = sorted(declared_roles & set(other["exclusive"])) if other else []
        if shared_roles:
            rows.append(_row(field, [other_id], shared_roles, "both ends declaring the same exclusive role", "agrees",
                             f"redundant: the role covers it ({', '.join(shared_roles)})"))
        else:
            rows.append(_row(field, [other_id], [], "both ends declaring the same exclusive role", "not_counted",
                             "no exclusive role covers the pair" if workspace else "the other declaration needs --workspace"))

    # ----- the registration line --------------------------------------------------------
    # `self`: the literal must be in a server script. `entry`: the build prints it, so source is
    # not consulted and the entry field is the fact. `none`: nothing should print it. Absent: the
    # declaration does not say; the observation is reported and --propose fills the word.
    reg_field, reg_declared = "/registration", metadata.get("registration")
    reg_how = 'a println literal beginning "<id> >> registered" in a server script'
    line = compositions.registration_line(metadata["id"])
    reg_lines = sorted({value for value in source.literals if value.startswith(line)})
    other_spellings = sorted({value for value in source.literals
                              if compositions.REGISTRATION_SUFFIX.strip() in value and value not in reg_lines})[:8]
    printed = bool(reg_lines)
    if reg_declared == "entry":
        rows.append(_row(reg_field, ["entry"], ["entry"] if metadata["entry"] else [], "the entry field; the generated entry prints the line",
                         "agrees" if metadata["entry"] else "declared_not_observed"))
    elif no_source and reg_declared != "none":
        rows.append(_row(reg_field, [reg_declared] if reg_declared else [], [], reg_how, "not_counted", no_source))
    elif reg_declared == "self":
        rows.append(_row(reg_field, ["self"], ["self"] if printed else [], reg_how,
                         "partial" if printed else "declared_not_observed",
                         "the literal is present; that the path printing it runs is the console's proof" if printed
                         else "the fix is a source edit: print the line from the registration path"
                         + (f"; seen instead: {other_spellings}" if other_spellings else "")))
    elif reg_declared == "none":
        rows.append(_row(reg_field, ["none"], ["self"] if printed else [], reg_how,
                         "observed_not_declared" if printed else "agrees",
                         "the module prints the line and says it does not" if printed else None))
    else:
        rows.append(_row(reg_field, [], ["self"] if printed else [], reg_how,
                         "observed_not_declared" if printed else "not_counted",
                         None if printed else "the declaration does not say and the script prints no registration line"
                         + (f"; seen instead: {other_spellings}" if other_spellings else "")))
    registration_proposal = None
    if reg_declared is None:
        registration_proposal = "self" if printed else ("entry" if metadata["entry"] else None)
    registration_note = None if reg_declared or printed or metadata["entry"] else \
        "registration: no line in source; the edit an author would make is println(\"" + line + "\") from the registration path, then registration: self"

    version_proposal, version_note = version_row(directory, metadata, rows, propose)

    for field, reason in UNREAD_FIELDS.items():
        rows.append(_row("/" + field, [], [], "nothing in this route", "not_counted", reason))

    for note in skipped:
        rows.append(_row("/", [], [], "reading the module's source", "not_counted", f"source not read: {note}"))

    result = {
        "protocol": PROTOCOL, "module": metadata["id"], "directory": str(directory),
        "declaration_sha256": digest, "payload": payload, "rows": rows,
        "stages": {"base_owned": owned, "engine_tables": engine, "new_in_base_namespace": sorted(new_paths)},
        "summary": {outcome: sum(1 for row in rows if row["outcome"] == outcome) for outcome in OUTCOMES},
        "inputs": {"workspace": workspace, "base_listings": [str(p) for p in listing_dirs], "target": target},
    }
    if propose:
        result["proposal"], result["proposal_notes"] = _proposal(metadata, owned, observed, rows, payload, footprint_notes)
        if registration_proposal:
            result["proposal"]["registration"] = registration_proposal
        if registration_note:
            result["proposal_notes"].append(registration_note)
        if version_proposal:
            result["proposal"]["version"] = version_proposal
        if version_note:
            result["proposal_notes"].append(version_note)
    return result


def _proposal(metadata: dict, owned: list[dict], observed: dict, rows: list[dict], payload: str,
              footprint_notes: list[str]) -> tuple[dict, list[str]]:
    """The declaration fields the observed side would fill. An observation, not a verdict: a
    declared name is never removed, and a role or a service stays the author's decision."""
    proposal: dict = {}
    files = sorted(set(metadata["replaces"]["files"]) | {row["path"].casefold() for row in owned})
    if files:
        proposal["replaces"] = {"files": files}
    kinds = list(FULL_KINDS) + (["weapons"] if payload in ("seed", "adapter") else [])
    provides: dict[str, list[str]] = {}
    for kind in compositions.PROVIDES_KINDS:
        declared = metadata["provides"].get(kind, [])
        names = set(declared) | (set(observed.get(kind, ())) if kind in kinds else set())
        if names:
            provides[kind] = sorted(names)
    if provides:
        proposal["provides"] = provides
    found: dict[str, list[str]] = {}
    for row in rows:
        if row["field"].startswith("/dependencies/") and row["observed"]:
            found[row["field"]] = row["observed"]
    dependencies = []
    for index, dep in enumerate(metadata["dependencies"]):
        kind = metadata["dependency_kinds"].get(dep, {}).get("kind")
        why = metadata["dependency_kinds"].get(dep, {}).get("why")
        observed_kinds = found.get(f"/dependencies/{index}", [])
        if kind is None and observed_kinds:
            kind = observed_kinds[0]
        entry = {"id": dep, "kind": kind} if kind else dep
        if isinstance(entry, dict) and why:
            entry["why"] = why
        dependencies.append(entry)
    if dependencies:
        proposal["dependencies"] = dependencies
    notes = list(footprint_notes)
    notes.append("exclusive and service are not proposed: a role and a service are the author's promise, not an observation.")
    return proposal, notes


def run(args) -> dict:
    """The CLI entry: the report, and with ``--strict`` a failure carrying it when a row differs."""
    result = verify(Path(args.directory), workspace=args.workspace, base_listings=args.base_listings,
                    target=args.target, propose=args.propose)
    if args.strict:
        differing = [row for row in result["rows"] if row["outcome"] in ("declared_not_observed", "observed_not_declared")]
        if differing:
            raise Failure(INPUT_INVALID,
                          f"{len(differing)} promise(s) of {result['module']} differ from what its bytes say",
                          "Each row names the field, what was declared, what was observed and the method. "
                          "Declare what the bytes show, or change the bytes; --propose prints the fields the "
                          "observed side would fill.", report=result)
    return result
