"""Target sets: maps, survival locations and their location tables (``docs/target-sets.md``).

A **target** is one place a composition can be planned, built, checked and played, keyed
``<foundation>/<map>/<mode>[/<location>]``. Stock and DLC5 maps come from a workspace's
``foundations/*.json``; survival locations (a fenced area of a stock map with its own route,
such as the Diner or the Crazy Place) come from the workspace's target file. Each target may
own one **location table**, ``registry/locations/<target>.json``, whose rows are the perk
machines, Pack-a-Punch, wall buys, GobbleGum sites, rotation slots and fences a community route
placed there, each cited to its source with a hash and a confidence.

Everything here reads workspace files and nothing else: no game, no network, no build. A table
is source data; its six facts are always ``false`` and it can never promote a rung. The
validation rules are the workspace's own ``location_table.py`` rules made public, so a private
table validates against a public schema.

``list_targets``, ``inspect_target`` and ``validate_workspace`` back ``pat target list``,
``pat target inspect`` and ``pat target validate``; ``resolve_placements`` is the plan-time
check ``pat module plan`` runs when a member declares ``placements``.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path, PureWindowsPath

from ..core.errors import INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING, INVALID_ARGUMENTS, Failure

PROTOCOL = "pat.target/1"
TARGETS_FILE = "registry/targets.json"
TABLES_DIR = "registry/locations"
MAX_TABLE_BYTES = 4 * 1024 * 1024
MAX_TARGETS_BYTES = 4 * 1024 * 1024
MAX_ROWS = 4096
MAX_TARGETS = 1024
MAX_NOTE = 2000

# Row kinds a location table may hold, and the kinds a module may declare it needs.
KINDS = ("perk-machine", "pack-a-punch", "wall-buy", "gobblegum", "wunderfizz", "mystery-box",
         "rotation-slot", "player-spawn", "zone-fence", "buildable-table", "power-switch")
# The five target kinds (docs/target-sets.md).
TARGET_KINDS = ("stock-map", "stock-location", "survival-location", "dlc5-map", "custom-map")
MODES = ("zclassic", "zsurvival", "zgrief", "zcleansed", "zencounter")
CONFIDENCE = ("high", "medium", "unknown")
# The six facts as the table format spells them (the workspace's proof table wrote them so).
TABLE_FACTS = ("offline_verified", "installed", "launched", "loaded_playable", "captured", "player_accepted")
FALLBACKS = ("refuse", "rotation-slot", "wunderfizz", "spawn-room-default", "omit")
SOURCE_REQUIRED = ("provider", "record", "citation", "file", "line", "sha256", "text")
# Phrases a table note may not use: they claim a T6 fact, and tables hold source data only.
T6_CLAIMS = ("verified on T6", "accepted on Beta 2", "playable")

IDENT = re.compile(r"^[a-z0-9]+([._-][a-z0-9]+)*\Z")
LOCATION = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}\Z")
MAP = re.compile(r"^zm_[a-z0-9_]{1,60}\Z")
FOUNDATION = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}\Z")
SHA256 = re.compile(r"^[0-9a-f]{64}\Z")
TARGET_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}/zm_[a-z0-9_]{1,60}/(zclassic|zsurvival|zgrief|zcleansed|zencounter)(/[a-z0-9][a-z0-9_]{0,63})?\Z")
# A route provider id: the engine's own route is ``stock``; a community route or a workspace
# adapter is any other id. Neither a key nor a route may hold a dot, so ``<location>.<route>``
# splits without ambiguity.
ROUTE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}\Z")
STOCK_ROUTE = "stock"
# ``file:line``, as a fence cites the route script it was read from.
CITATION = re.compile(r"^\S.*:[0-9]{1,9}\Z")


# ----- keys ------------------------------------------------------------------------------

def target_key(foundation: str, map_id: str, mode: str, location: str | None = None) -> str:
    return f"{foundation}/{map_id}/{mode}" + (f"/{location}" if location else "")


def parse_key(key: str) -> dict:
    """Split ``<foundation>/<map>/<mode>[/<location>]``; refuse anything else."""
    if not isinstance(key, str) or not TARGET_KEY.match(key):
        raise Failure(INVALID_ARGUMENTS, f"A target key is <foundation>/<map>/<mode>[/<location>]: {key!r}",
                      "Modes: " + ", ".join(MODES) + ". Run: pat target list <workspace> --json")
    parts = key.split("/")
    return {"foundation": parts[0], "map": parts[1], "mode": parts[2], "location": parts[3] if len(parts) == 4 else None}


def parse_id(entry_id: str) -> tuple[str, str | None]:
    """Split a target-set entry id ``<key>`` or ``<key>@<route>`` into the two. The key names
    the place; the route names which provider implements it. A location two providers both
    implement has one key and two ids, and the file keeps both: choosing between them is a
    composition's decision, not the registry's."""
    if not isinstance(entry_id, str):
        raise Failure(INVALID_ARGUMENTS, f"A target id is <foundation>/<map>/<mode>[/<location>][@<route>]: {entry_id!r}")
    key, _, route = entry_id.partition("@")
    if not TARGET_KEY.match(key) or (_ and not ROUTE.match(route)):
        raise Failure(INVALID_ARGUMENTS, f"A target id is <foundation>/<map>/<mode>[/<location>][@<route>]: {entry_id!r}",
                      "Modes: " + ", ".join(MODES) + ". Run: pat target list <workspace> --json")
    return key, (route or None)


def target_id(key: str, route: str | None) -> str:
    """The entry id for a key on a route. The engine's own route needs no discriminator."""
    return key if route in (None, STOCK_ROUTE) else f"{key}@{route}"


def table_relpath(key: str, route: str | None = None) -> str:
    """``registry/locations/<key>[.<route>].json``. A stock route writes the bare name; a
    community route writes ``<location>.<route>.json``, so two providers never share a file."""
    suffix = "" if route in (None, STOCK_ROUTE) else f".{route}"
    return f"{TABLES_DIR}/{key}{suffix}.json"


def parse_table_relpath(relative: str) -> tuple[str, str | None]:
    """The inverse: the key and the route suffix a table's path under ``registry/locations``
    declares. ``diner.t6-qol`` is the ``diner`` key on route ``t6-qol``."""
    head, _, last = relative.rpartition("/")
    stem = last[: -len(".json")] if last.endswith(".json") else last
    name, _, route = stem.partition(".")
    key = f"{head}/{name}" if head else name
    return key, (route or None)


def table_path(root: Path, key: str, route: str | None = None) -> Path:
    return root / table_relpath(key, route)


# ----- location tables -------------------------------------------------------------------

def _vector(value, name, errors, where):
    if not (isinstance(value, list) and len(value) == 3
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)):
        errors.append({"where": where, "message": f"{name} must be a three-number list, got {value!r}"})


def _relative(text) -> bool:
    if not isinstance(text, str) or not text or "\\" in text:
        return False
    p = Path(text)
    return not (p.is_absolute() or PureWindowsPath(text).anchor or ".." in p.parts)


def validate_table(doc, path: str = "<table>") -> list[dict]:
    """The workspace's rules: shape, target string equals its parts, a survival target names
    its location, one named route, all six facts false, every row a literal or an expression,
    vectors of three numbers, unique ids, cited record listed, high confidence with file and
    line, literal origin equal to the cited text, notes that claim no T6 fact. Returns one
    diagnostic per defect; an empty list means the table is well formed. Nothing here checks
    that a coordinate is inside the map or that anything about T6 is true."""
    errors: list[dict] = []

    def err(where, message):
        errors.append({"where": where, "message": message})

    if not isinstance(doc, dict):
        return [{"where": path, "message": "table must be a JSON object"}]
    if doc.get("schema") != 1:
        err(path, "schema must be 1")
    for key in ("target", "foundation", "map", "mode", "title", "records", "facts", "placements"):
        if key not in doc:
            err(path, f"missing {key}")
    if errors:
        return errors
    foundation, mapname, mode, location = doc["foundation"], doc["map"], doc["mode"], doc.get("location")
    if not isinstance(foundation, str) or not FOUNDATION.match(foundation):
        err(path, f"foundation id {foundation!r} is not an identifier")
    if not isinstance(mapname, str) or not MAP.match(mapname):
        err(path, f"map {mapname!r} must look like zm_<name>")
    if mode not in MODES:
        err(path, f"mode {mode!r} not in {MODES}")
    if location is not None and (not isinstance(location, str) or not LOCATION.match(location)):
        err(path, f"location {location!r} is not an identifier")
    expected = f"{foundation}/{mapname}/{mode}" + (f"/{location}" if location else "")
    if doc["target"] != expected:
        err(path, f"target {doc['target']!r} must equal {expected!r}")
    if location is None and mode == "zsurvival":
        err(path, "a zsurvival target names its location")
    if not isinstance(doc["title"], str) or not doc["title"].strip() or len(doc["title"]) > 120:
        err(path, "title is a non-empty string of at most 120 characters")
    records = doc["records"]
    if not (isinstance(records, list) and records and all(isinstance(r, str) for r in records)):
        err(path, "records must be a non-empty list of workspace-relative paths")
        records = [r for r in records if isinstance(r, str)] if isinstance(records, list) else []
    else:
        for record in records:
            if not _relative(record):
                err(path, f"record {record!r} must be workspace-relative")
    if "coordinate_note" in doc and not isinstance(doc["coordinate_note"], str):
        err(path, "coordinate_note must be a string")
    route = doc.get("route", STOCK_ROUTE)
    if not isinstance(route, str) or not ROUTE.match(route):
        err(path, f"route {route!r} names one provider: {STOCK_ROUTE!r} for the engine's own route, "
                  "or a community route or workspace adapter id")
    shelf = doc.get("shelf")
    if shelf is not None and not (isinstance(shelf, dict)
                                  and all(isinstance(v, (str, type(None))) for v in shelf.values())):
        err(path, "shelf is an object of caption and preview strings, or null")
    notes = doc.get("source_notes")
    if notes is not None and not (isinstance(notes, list) and all(isinstance(n, str) for n in notes)):
        err(path, "source_notes must be a list of strings")
    facts = doc["facts"]
    if not isinstance(facts, dict) or set(facts) != set(TABLE_FACTS):
        err(path, f"facts must name exactly {TABLE_FACTS}")
    else:
        for fact, value in facts.items():
            if value is not False:
                err(path, f"fact {fact} must be false; a location table is source data, not evidence")
    rows = doc["placements"]
    if not isinstance(rows, list) or not rows:
        err(path, "placements must be a non-empty list")
        return errors
    if len(rows) > MAX_ROWS:
        err(path, f"placements holds at most {MAX_ROWS} rows")
        return errors
    seen: Counter = Counter()
    for index, row in enumerate(rows):
        where = f"{path}#{index}"
        if not isinstance(row, dict):
            err(where, "row must be an object")
            continue
        rid = row.get("id")
        if not isinstance(rid, str) or not IDENT.match(rid):
            err(where, f"id {rid!r} is not an identifier")
        else:
            seen[rid] += 1
            where = f"{path}#{rid}"
        if row.get("kind") not in KINDS:
            err(where, f"kind {row.get('kind')!r} not in {KINDS}")
        if row.get("confidence") not in CONFIDENCE:
            err(where, f"confidence {row.get('confidence')!r} not in {CONFIDENCE}")
        for key in ("site", "occupant"):
            if key in row and row[key] is not None and not isinstance(row[key], str):
                err(where, f"{key} is a string or null")
        origin, angles, expression = row.get("origin"), row.get("angles"), row.get("expression")
        if origin is None and angles is None:
            if not (isinstance(expression, dict) and isinstance(expression.get("origin"), str) and expression["origin"].strip()):
                err(where, "a row without a literal origin must carry expression.origin naming the source relation")
        else:
            if origin is not None:
                _vector(origin, "origin", errors, where)
            if angles is not None:
                _vector(angles, "angles", errors, where)
            if origin is None:
                err(where, "angles without an origin")
        if expression is not None and not (isinstance(expression, dict)
                                           and all(isinstance(v, (str, type(None))) for v in expression.values())):
            err(where, "expression is an object of strings or nulls (origin, angles)")
        if row.get("kind") == "rotation-slot" and origin is None and expression is None:
            err(where, "a rotation slot needs a literal or symbolic transform")
        source = row.get("source")
        if not isinstance(source, dict):
            err(where, "source must be an object")
        else:
            for key in SOURCE_REQUIRED:
                if key not in source:
                    err(where, f"source.{key} missing")
            provider, record = source.get("provider"), source.get("record")
            if not isinstance(provider, str) or not IDENT.match(provider):
                err(where, f"source.provider {provider!r} is not an identifier")
            if record not in records:
                err(where, f"source.record {record!r} is not listed in records")
            line = source.get("line")
            if line is not None and (not isinstance(line, int) or isinstance(line, bool) or line < 1):
                err(where, "source.line must be a positive integer or null")
            sha = source.get("sha256")
            if sha is not None and not (isinstance(sha, str) and SHA256.match(sha)):
                err(where, "source.sha256 must be 64 hex characters or null")
            if row.get("confidence") == "high" and (line is None or source.get("file") is None):
                err(where, "high confidence requires a source file and line")
            text = source.get("text")
            if origin is not None and isinstance(text, str) and text.strip().startswith("(") \
                    and "Accepted" not in str(source.get("citation", "")):
                try:
                    literal = [float(v) for v in text.strip().strip("()").split(",")]
                except ValueError:
                    literal = None
                if literal is not None and isinstance(origin, list) and len(origin) == 3 \
                        and all(isinstance(v, (int, float)) for v in origin) and literal != [float(v) for v in origin]:
                    err(where, f"origin {origin} does not match cited text {text!r}")
        note = row.get("note")
        if note is not None and (not isinstance(note, str) or len(note) > MAX_NOTE):
            err(where, f"note must be a string of at most {MAX_NOTE} characters")
        for phrase in T6_CLAIMS:
            if isinstance(note, str) and phrase.lower() in note.lower():
                err(where, f"note claims a T6 fact ({phrase!r}); tables hold source data only")
    for rid, count in seen.items():
        if count > 1:
            err(path, f"duplicate placement id {rid!r} ({count} rows)")
    return errors


def summarize_table(doc: dict) -> dict:
    rows = doc.get("placements", []) if isinstance(doc, dict) else []
    rows = [r for r in rows if isinstance(r, dict)]
    return {
        "target": doc.get("target") if isinstance(doc, dict) else None,
        "title": doc.get("title") if isinstance(doc, dict) else None,
        "placements": len(rows),
        "by_kind": dict(sorted(Counter(r.get("kind") for r in rows).items(), key=lambda kv: str(kv[0]))),
        "literal": sum(1 for r in rows if r.get("origin") is not None),
        "expression": sum(1 for r in rows if r.get("origin") is None),
        "by_confidence": dict(sorted(Counter(r.get("confidence") for r in rows).items(), key=lambda kv: str(kv[0]))),
        "providers": dict(sorted(Counter((r.get("source") or {}).get("provider") if isinstance(r.get("source"), dict) else None
                                         for r in rows).items(), key=lambda kv: str(kv[0]))),
        "records": list(doc.get("records", [])) if isinstance(doc, dict) and isinstance(doc.get("records"), list) else [],
    }


def read_json(path: Path, limit: int):
    """Read one JSON file with a size bound; a missing or unreadable file is a Failure."""
    if path.is_symlink() or not path.is_file():
        raise Failure(INPUT_MISSING, f"File is missing: {path}")
    size = path.stat().st_size
    if size > limit:
        raise Failure(INPUT_LIMIT, f"{path.name} is {size} bytes; the limit is {limit}")
    raw = path.read_bytes()
    try:
        return raw, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Failure(INPUT_INVALID, f"{path} is not valid UTF-8 JSON: {str(exc)[:200]}") from exc


def load_table(path: Path) -> dict:
    raw, doc = read_json(path, MAX_TABLE_BYTES)
    return {"path": path, "sha256": hashlib.sha256(raw).hexdigest(), "doc": doc, "errors": validate_table(doc, path.name)}


# ----- the target file --------------------------------------------------------------------

ENTRY_FIELDS = {"id", "target", "kind", "foundation", "map", "mode", "location", "parent", "title", "caption", "fence",
                "route", "location_table", "placements", "vanilla_profile", "art", "ledger", "note"}


def validate_entry(entry, index: int) -> tuple[dict | None, list[dict]]:
    """One target-set entry (docs/target-sets.md): the id is a key with an optional ``@route``
    discriminator, the key's parts are repeated and must agree, the kind fits the parts, a
    location names the parent map it fences, and the route the id names is the route the entry
    declares."""
    where = f"targets#{index}"
    errors: list[dict] = []

    def err(message, where=where):
        errors.append({"where": where, "message": message})

    if not isinstance(entry, dict):
        return None, [{"where": where, "message": "entry must be an object"}]
    unknown = sorted(set(entry) - ENTRY_FIELDS)
    if unknown:
        err(f"unknown fields {unknown}")
    entry_id = entry.get("id")
    try:
        key, id_route = parse_id(entry_id)
    except Failure:
        err(f"id {entry_id!r} is not <foundation>/<map>/<mode>[/<location>][@<route>]")
        return None, errors
    where = f"targets#{entry_id}"
    parts = parse_key(key)
    if "target" in entry and entry["target"] != key:
        err(f"target {entry['target']!r} must equal the id's key {key!r}", where)
    for name in ("foundation", "map", "mode"):
        if entry.get(name) != parts[name]:
            err(f"{name} {entry.get(name)!r} must equal the id's {parts[name]!r}", where)
    if entry.get("location") != parts["location"]:
        err(f"location {entry.get('location')!r} must equal the id's {parts['location']!r}", where)
    kind = entry.get("kind")
    if kind not in TARGET_KINDS:
        err(f"kind {kind!r} not in {TARGET_KINDS}", where)
    located = parts["location"] is not None
    if kind in ("stock-location", "survival-location") and not located:
        err(f"kind {kind} names a location in its id", where)
    if kind in ("stock-map", "dlc5-map", "custom-map") and located:
        err(f"kind {kind} has no location in its id", where)
    route = entry.get("route")
    if not isinstance(route, str) or not ROUTE.match(route):
        err(f"route {route!r} names exactly one provider ({STOCK_ROUTE!r} for the engine's own route, "
            "a community route such as a location script's, or a workspace adapter id)", where)
    elif id_route is not None and id_route != route:
        err(f"id names route {id_route!r} but the entry declares {route!r}", where)
    elif id_route is None and route != STOCK_ROUTE:
        err(f"route {route!r} is not the engine's own route, so the id carries it: {target_id(key, route)!r}", where)
    parent = entry.get("parent")
    if located:
        if parent is not None and (not isinstance(parent, str) or not TARGET_KEY.match(parent)
                                   or parse_key(parent)["map"] != parts["map"]
                                   or parse_key(parent)["location"] is not None
                                   or parse_key(parent)["foundation"] != parts["foundation"]):
            err("a location's parent is its map's target on the same foundation, without a location", where)
        if parent is None and kind == "survival-location":
            err("a community survival location fences a map, so it names that map's target as its parent", where)
    elif parent is not None:
        err("a map has no parent", where)
    for name, limit in (("title", 120), ("caption", 200)):
        if name in entry and entry[name] is not None and (not isinstance(entry[name], str) or len(entry[name]) > limit):
            err(f"{name} is a string of at most {limit} characters", where)
    fence = entry.get("fence")
    if located and kind == "survival-location":
        if not isinstance(fence, dict):
            err("a survival location carries a fence object cited to its route script", where)
        else:
            errors += _fence_errors(fence, where)
    elif fence is not None:
        if not isinstance(fence, dict):
            err("fence is an object or null", where)
        else:
            errors += _fence_errors(fence, where)
    for name in ("location_table", "vanilla_profile"):
        if entry.get(name) is not None and not _relative(entry[name]):
            err(f"{name} is a workspace-relative path or null", where)
    expected_table = table_relpath(key, route if isinstance(route, str) else None)
    if entry.get("location_table") is not None and entry["location_table"] != expected_table:
        err(f"location_table must be {expected_table!r}, the path this id and route name", where)
    rows = entry.get("placements")
    if rows is not None and (not isinstance(rows, int) or isinstance(rows, bool) or rows < 0):
        err("placements is the table's row count: a non-negative integer or null", where)
    art = entry.get("art")
    if art is not None and not (isinstance(art, dict) and all(isinstance(v, (str, type(None))) for v in art.values())):
        err("art is an object of material names or null", where)
    ledger = entry.get("ledger", [])
    if not isinstance(ledger, list) or not all(isinstance(r, dict) and isinstance(r.get("module"), str) for r in ledger):
        err("ledger is a list of {module, rung, receipt} rows; the module's own evidence.json is the authority", where)
    return ({"id": entry_id, "target": key, **parts, "kind": kind, "parent": parent, "title": entry.get("title"),
             "caption": entry.get("caption"), "route": route, "fence": fence if isinstance(fence, dict) else None,
             "location_table": entry.get("location_table"), "placements": rows if isinstance(rows, int) and not isinstance(rows, bool) else None,
             "vanilla_profile": entry.get("vanilla_profile"),
             "art": art if isinstance(art, dict) else None, "ledger_rows": len(ledger) if isinstance(ledger, list) else 0,
             "note": entry.get("note") if isinstance(entry.get("note"), str) else None}, errors)


def _fence_errors(fence: dict, where: str) -> list[dict]:
    """A fence names the zones a route enables and cites the script lines it was read from.
    A wiki room label is not a fence."""
    errors = []
    for name in ("zones", "barriers", "disabled_spawns", "citations"):
        if name in fence and not (isinstance(fence[name], list) and all(isinstance(v, str) for v in fence[name])):
            errors.append({"where": where, "message": f"fence.{name} is a list of strings"})
    if "rows" in fence and (not isinstance(fence["rows"], int) or isinstance(fence["rows"], bool) or fence["rows"] < 0):
        errors.append({"where": where, "message": "fence.rows is the number of cited registrations: a non-negative integer"})
    citations = fence.get("citations")
    source = fence.get("source")
    cited = isinstance(citations, list) and citations and all(isinstance(c, str) and CITATION.match(c) for c in citations)
    sourced = isinstance(source, dict) and isinstance(source.get("file"), str)
    if not cited and not sourced:
        errors.append({"where": where, "message": "a fence cites the route script it was read from: citations of "
                                                  "\"file:line\" or a source object naming the file; a wiki room label is not a fence"})
    return errors


def load_targets_file(path: Path) -> dict:
    """The workspace's target file: ``{"schema": 1, "entries": [entry, ...]}`` with an optional
    ``targets`` count of the distinct target keys. Returns the valid entries, one diagnostic
    per defect, and the hash of the bytes read.

    One entry is one ``(target, route)`` pair. A location two providers both implement is two
    entries with one key: the file records the pair and never picks between them, so the
    choice stays with the composition that plans the target."""
    raw, data = read_json(path, MAX_TARGETS_BYTES)
    result = {"path": path, "sha256": hashlib.sha256(raw).hexdigest(), "entries": [], "errors": [], "route_choices": {}}
    if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("entries"), list):
        result["errors"].append({"where": path.name, "message": 'target file is {"schema": 1, "entries": [...]}'})
        return result
    if len(data["entries"]) > MAX_TARGETS:
        result["errors"].append({"where": path.name, "message": f"entries holds at most {MAX_TARGETS} entries"})
        return result
    seen: Counter = Counter()
    routes: dict[str, list] = {}
    for index, entry in enumerate(data["entries"]):
        parsed, errors = validate_entry(entry, index)
        result["errors"] += errors
        if parsed is None:
            continue
        seen[parsed["id"]] += 1
        routes.setdefault(parsed["target"], []).append(parsed["route"])
        result["entries"].append(parsed)
    for key, count in seen.items():
        if count > 1:
            result["errors"].append({"where": f"targets#{key}",
                                     "message": f"duplicate target id ({count} entries); one entry is one target on one route"})
    for target, provided in sorted(routes.items()):
        # A malformed entry's route is already a diagnostic; keep it comparable so one bad
        # value cannot crash the listing.
        provided = [r if isinstance(r, str) else repr(r) for r in provided]
        duplicated = sorted({r for r in provided if provided.count(r) > 1})
        if duplicated:
            result["errors"].append({"where": f"targets#{target}",
                                     "message": f"route(s) {duplicated} provide {target!r} more than once; one entry is one target on one route"})
        if len(set(provided)) > 1:
            result["route_choices"][target] = sorted(set(provided))
    keys = {e["target"] for e in result["entries"]}
    ids = {e["id"] for e in result["entries"]}
    for entry in result["entries"]:
        if entry["parent"] is not None and entry["parent"] not in keys and entry["parent"] not in ids:
            result["errors"].append({"where": f"targets#{entry['id']}",
                                     "message": f"parent {entry['parent']!r} is not a target in this file"})
        if entry["parent"] is None and entry["location"] is not None:
            sibling = target_key(entry["foundation"], entry["map"], "zclassic")
            if sibling in keys:
                result["errors"].append({"where": f"targets#{entry['id']}",
                                         "message": f"a location with no parent may not sit beside {sibling!r}; "
                                                    "only a map with no classic target of its own is a top-level location"})
    count = data.get("targets")
    if count is not None and (not isinstance(count, int) or isinstance(count, bool) or count != len(keys)):
        result["errors"].append({"where": path.name,
                                 "message": f"targets counts the distinct target keys: {len(keys)}, not {count!r}"})
    return result


# ----- the workspace view -----------------------------------------------------------------

def _workspace(path: str) -> Path:
    root = Path(path).expanduser()
    if not root.is_dir():
        raise Failure(INPUT_MISSING, f"Workspace directory is missing: {root}")
    return root


def foundations(root: Path) -> dict[str, dict]:
    """``foundations/*.json`` by id: the base token and the maps each foundation stages."""
    result: dict[str, dict] = {}
    directory = root / "foundations"
    if not directory.is_dir():
        return result
    for file in sorted(directory.glob("*.json")):
        try:
            _, info = read_json(file, MAX_TARGETS_BYTES)
        except Failure:
            continue
        if not isinstance(info, dict) or not isinstance(info.get("id"), str) or not FOUNDATION.match(info["id"]):
            continue
        maps = info.get("maps")
        names = sorted(m for m in maps if isinstance(m, str) and MAP.match(m)) if isinstance(maps, dict) else []
        listings = info.get("base_listings")
        result[info["id"]] = {"id": info["id"], "base": info.get("profile_prefix") if isinstance(info.get("profile_prefix"), str) else None,
                              "maps": names, "file": file.name,
                              "base_listings": [d for d in ([listings] if isinstance(listings, str) else listings if isinstance(listings, list) else [])
                                                if isinstance(d, str) and d]}
    return result


def base_zone_names(root: Path, foundation_id: str, map_id: str) -> list[str]:
    """The zone names a foundation says a module links against on one map
    (``foundations/<id>.json``, ``maps.<map>.link_loads``). Those zones are the base, so a load that
    is one of them is never a donor even when no asset listing for it is on this machine."""
    info = foundations(root).get(foundation_id)
    if not info:
        return []
    # foundations() already picked the descriptor that carries the maps; a private companion file
    # beside it may share the id and carry none.
    try:
        _, record = read_json(root / "foundations" / info["file"], MAX_TARGETS_BYTES)
    except Failure:
        return []
    maps = record.get("maps") if isinstance(record, dict) else None
    per_map = maps.get(map_id) if isinstance(maps, dict) else None
    rows = per_map.get("link_loads") if isinstance(per_map, dict) else None
    return [name for name in rows if isinstance(name, str) and name] if isinstance(rows, list) else []


def base_listing_dirs(root: Path, foundation_id: str) -> list[Path]:
    """Directories of base asset listings a workspace's ``foundations/<id>.json`` names under
    ``base_listings``, resolved against the workspace root. A foundation that does not name any
    returns nothing: the composer then needs ``--base-listings`` on the command line."""
    info = foundations(root).get(foundation_id)
    if not info:
        return []
    found = []
    for entry in info["base_listings"]:
        path = Path(entry).expanduser()
        path = path if path.is_absolute() else (root / path)
        if path.is_dir():
            found.append(path)
    return found


def _catalog() -> dict[str, dict]:
    path = Path(__file__).resolve().parent.parent / "game" / "maps.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    result: dict[str, dict] = {}
    for row in rows.values():
        if isinstance(row, dict) and isinstance(row.get("map"), str) and row["map"] not in result and row.get("group") == "zclassic":
            result[row["map"]] = row
    for row in rows.values():
        if isinstance(row, dict) and isinstance(row.get("map"), str):
            result.setdefault(row["map"], row)
    return result


def list_targets(workspace: str, targets_file: str | None = None) -> dict:
    """Stock and DLC5 maps from the foundations, survival locations from the target file, each
    with its route and whether a location table exists, grouped by parent map for the app's
    maps filter. A target two routes provide appears once per route and once in
    ``route_choices``; the listing never picks between them."""
    root = _workspace(workspace)
    found = foundations(root)
    catalog = _catalog()
    rows: dict[str, dict] = {}
    for fid, info in found.items():
        for map_id in info["maps"]:
            key = target_key(fid, map_id, "zclassic")
            known = catalog.get(map_id)
            kind = "custom-map" if known is None else "dlc5-map" if known.get("dlc5") else "stock-map"
            rows[key] = {"id": key, "target": key, "kind": kind, "foundation": fid, "map": map_id, "mode": "zclassic",
                         "location": None, "parent": None, "title": known.get("label") if known else None,
                         "route": STOCK_ROUTE, "source": f"foundations/{info['file']}", "base": info["base"]}
    file_path = Path(targets_file).expanduser() if targets_file else root / TARGETS_FILE
    loaded = None
    errors: list[dict] = []
    choices: dict[str, list] = {}
    if file_path.is_file():
        loaded = load_targets_file(file_path)
        errors = loaded["errors"]
        choices = loaded["route_choices"]
        source = file_path.relative_to(root).as_posix() if file_path.is_relative_to(root) else str(file_path)
        for entry in loaded["entries"]:
            row = {"id": entry["id"], "target": entry["target"], "kind": entry["kind"], "foundation": entry["foundation"],
                   "map": entry["map"], "mode": entry["mode"], "location": entry["location"], "parent": entry["parent"],
                   "title": entry["title"], "caption": entry["caption"], "route": entry["route"], "source": source,
                   "base": found.get(entry["foundation"], {}).get("base"),
                   "location_table": entry["location_table"], "declared_table": entry["location_table"],
                   "listed_placements": entry["placements"], "from_file": True}
            if entry["id"] in rows and entry["location"] is None:
                rows[entry["id"]].update({k: v for k, v in row.items() if v is not None})
            else:
                rows[entry["id"]] = row
    for row in rows.values():
        # The table the id and route name; an entry that named none is still probed for one.
        relative = row.get("location_table") or table_relpath(row["target"], row.get("route"))
        row["location_table"] = relative if (root / relative).is_file() else None
        row["foundation_known"] = row["foundation"] in found
        row["route_choices"] = choices.get(row["target"], [])
    ordered = [rows[k] for k in sorted(rows)]
    groups: dict[str, dict] = {}
    for row in ordered:
        parent_key = row["parent"] or row["target"]
        group = groups.setdefault(parent_key, {"parent": parent_key, "map": row["map"], "foundation": row["foundation"],
                                               "title": None, "children": []})
        if row["location"] is None and row["target"] == parent_key:
            group["title"] = row["title"]
        else:
            group["children"].append({"id": row["id"], "target": row["target"], "title": row["title"],
                                      "route": row["route"], "location": row["location"],
                                      "location_table": row["location_table"] is not None})
        if group["title"] is None and row["target"] == parent_key:
            group["title"] = row["title"]
    return {"protocol": PROTOCOL, "workspace": str(root), "targets_file": str(file_path) if loaded else None,
            "targets_file_sha256": loaded["sha256"] if loaded else None,
            "foundations": {fid: {"base": info["base"], "maps": info["maps"]} for fid, info in found.items()},
            "targets": ordered, "groups": [groups[k] for k in sorted(groups)],
            "route_choices": [{"target": k, "routes": v} for k, v in sorted(choices.items())],
            "counts": {"entries": len(ordered), "targets": len({r["target"] for r in ordered}),
                       "with_location_table": sum(1 for r in ordered if r["location_table"]),
                       "route_choices": len(choices),
                       **{kind: sum(1 for r in ordered if r["kind"] == kind) for kind in TARGET_KINDS}},
            "diagnostics": errors, "verification": "workspace files read; no coordinate, fit or gameplay fact checked"}


def inspect_target(workspace: str, key: str, targets_file: str | None = None, route: str | None = None) -> dict:
    """One target's entry plus its location table summary, when a table exists. The key may
    carry its route (``<key>@<route>``) or name it with ``route``. A key two routes provide and
    no route given returns both entries and refuses to choose: picking a provider is the
    composition's decision."""
    key, id_route = parse_id(key)
    if id_route is not None and route is not None and id_route != route:
        raise Failure(INVALID_ARGUMENTS, f"--route {route!r} disagrees with the key's route {id_route!r}")
    wanted = route or id_route
    if wanted is not None and not ROUTE.match(wanted):
        raise Failure(INVALID_ARGUMENTS, f"Route {wanted!r} is a provider id")
    parts = parse_key(key)
    listing = list_targets(workspace, targets_file)
    root = Path(listing["workspace"])
    matches = [r for r in listing["targets"] if r["target"] == key and (wanted is None or r["route"] == wanted)]
    available = sorted({r["route"] for r in listing["targets"] if r["target"] == key})
    result = {"protocol": PROTOCOL, "workspace": str(root), "target": key, **parts, "route": wanted,
              "routes": available, "entry": None, "entries": matches, "listed": bool(matches),
              "location_table": None, "diagnostics": []}
    if wanted is None and len(available) > 1:
        result["outcome"] = "route_choice"
        result["detail"] = (f"{key} is provided by {len(available)} routes ({', '.join(available)}); "
                            "name one with --route. Two providers are a pair to choose from, never a merge.")
        return result
    entry = matches[0] if matches else None
    result["entry"] = entry
    result["outcome"] = "one"
    relative = (entry or {}).get("location_table") or table_relpath(key, wanted)
    path = root / relative
    if path.is_file():
        table = load_table(path)
        doc = table["doc"] if isinstance(table["doc"], dict) else {}
        result["location_table"] = {"path": relative, "sha256": table["sha256"],
                                    "route": doc.get("route", STOCK_ROUTE),
                                    "validation": "valid" if not table["errors"] else "invalid",
                                    "summary": summarize_table(table["doc"]), "diagnostics": table["errors"][:32]}
        if doc.get("target") != key:
            result["diagnostics"].append({"where": relative, "message": f"table target {doc.get('target')!r} differs from its path {key!r}"})
    if entry is None and result["location_table"] is None:
        raise Failure(INPUT_MISSING, f"Target {target_id(key, wanted)} is neither listed nor has a location table in {root}",
                      "Run: pat target list <workspace> --json for the keys this workspace knows", **{k: v for k, v in result.items() if k != "protocol"})
    return result


def validate_workspace(workspace: str, targets_file: str | None = None) -> dict:
    """Every location table under ``registry/locations`` and the target file: the table rules,
    the entry rules, each table at the path its target and route name, each listed table
    present, its listed row count right, and no two entries for one ``(target, route)``. Tables
    with no entry are reported, not refused: the proof table came before the target file."""
    root = _workspace(workspace)
    listing = list_targets(workspace, targets_file)
    tables_root = root / TABLES_DIR
    tables = []
    errors: list[dict] = list(listing["diagnostics"])
    ids = {r["id"] for r in listing["targets"]}
    counted: dict[str, int] = {}
    if tables_root.is_dir():
        files = sorted(p for p in tables_root.rglob("*.json") if not p.is_symlink())
        if len(files) > MAX_TARGETS:
            raise Failure(INPUT_LIMIT, f"{TABLES_DIR} holds more than {MAX_TARGETS} tables")
        for file in files:
            rel = file.relative_to(root).as_posix()
            try:
                table = load_table(file)
            except Failure as exc:
                errors.append({"where": rel, "message": exc.message})
                tables.append({"path": rel, "ok": False, "target": None, "route": None, "placements": 0})
                continue
            doc = table["doc"]
            key, suffix = parse_table_relpath(file.relative_to(tables_root).as_posix())
            route = doc.get("route", STOCK_ROUTE) if isinstance(doc, dict) else None
            table_errors = list(table["errors"])
            if isinstance(doc, dict):
                if doc.get("target") != key:
                    table_errors.append({"where": rel, "message": f"table target {doc.get('target')!r} must equal its path {key!r}"})
                expected = table_relpath(key, route if isinstance(route, str) else None)
                if f"{TABLES_DIR}/{file.relative_to(tables_root).as_posix()}" != expected:
                    table_errors.append({"where": rel, "message": f"a table on route {route!r} is named {expected!r}, "
                                                                 "so two providers of one target never share a file"})
            for e in table_errors:
                e["where"] = e["where"].replace(file.name, rel, 1) if e["where"].startswith(file.name) else e["where"]
            errors += table_errors
            summary = summarize_table(doc)
            entry_id = target_id(key, route if isinstance(route, str) else None)
            counted[f"{TABLES_DIR}/{file.relative_to(tables_root).as_posix()}"] = summary["placements"]
            tables.append({"path": rel, "sha256": table["sha256"], "ok": not table_errors, "target": summary["target"],
                           "route": route, "placements": summary["placements"], "by_kind": summary["by_kind"],
                           "listed": entry_id in ids})
    # A target file entry whose location_table is absent, or whose listed row count is stale.
    for row in listing["targets"]:
        declared = row.get("declared_table")
        if declared and not (root / declared).is_file():
            errors.append({"where": f"targets#{row['id']}", "message": f"location_table {declared!r} does not exist"})
        relative = table_relpath(row["target"], row.get("route"))
        listed = row.get("listed_placements")
        if listed is not None and relative in counted and counted[relative] != listed:
            errors.append({"where": f"targets#{row['id']}",
                           "message": f"placements says {listed} but {relative} holds {counted[relative]} rows"})
    return {"protocol": PROTOCOL, "workspace": str(root), "targets_file": listing["targets_file"],
            "ok": not errors, "targets": listing["counts"]["targets"], "entries": listing["counts"]["entries"],
            "tables": tables, "route_choices": listing["route_choices"],
            "unlisted_tables": [t["path"] for t in tables if t.get("listed") is False],
            "diagnostics": errors[:256], "diagnostics_total": len(errors),
            "verification": "shape, keys, citations and facts checked offline; no coordinate is checked against a map and nothing about T6 is claimed"}


def table_for(root: Path, entry_id: str) -> dict:
    """The location table a target id names, resolved on disk. ``<key>@<route>`` names its
    table directly; a bare key takes the one table present. A key two routes provide and no
    route named is refused here, at plan time, exactly as two ``replaceFunc`` owners of one
    function are: the pair is reported, never merged."""
    key, route = parse_id(entry_id)
    if route is not None:
        relative = table_relpath(key, route)
        return {"target": key, "route": route, "path": relative if (root / relative).is_file() else None}
    found = []
    directory = (root / TABLES_DIR / key).parent
    name = key.rsplit("/", 1)[-1]
    if directory.is_dir():
        for candidate in sorted(directory.glob(f"{name}.json")) + sorted(directory.glob(f"{name}.*.json")):
            if candidate.is_symlink():
                continue
            _, suffix = parse_table_relpath(candidate.name)
            found.append((suffix, candidate))
    if len(found) > 1:
        routes = sorted(r or STOCK_ROUTE for r, _ in found)
        raise Failure(INVALID_ARGUMENTS, f"{key} is provided by {len(found)} routes ({', '.join(routes)}); name one as {key}@<route>",
                      "Two providers of one target are a pair to choose from, never a merge. "
                      f"Run: pat target inspect <workspace> {key} --json", routes=routes)
    if not found:
        return {"target": key, "route": None, "path": None}
    suffix, candidate = found[0]
    return {"target": key, "route": suffix or STOCK_ROUTE, "path": table_relpath(key, suffix)}


# ----- placements: what a module needs, resolved against a table --------------------------

def validate_placements(value, mid: str) -> list[dict] | None:
    """The ``placements`` field of ``module.json``: what a module needs, never where. Each row
    is ``{"needs": <row kind>, "occupant"?: <identity>, "count": 1 | int | "any", "fallback": <policy>}``.
    Absent is not an error and adds nothing."""
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > 64:
        raise Failure(INPUT_INVALID, f"{mid}: placements is a list of at most 64 needs", field="/placements")
    rows = []
    for index, row in enumerate(value):
        field = f"/placements/{index}"
        if not isinstance(row, dict):
            raise Failure(INPUT_INVALID, f"{mid}: placements[{index}] is an object", field=field)
        unknown = sorted(set(row) - {"needs", "occupant", "count", "fallback", "note"})
        if unknown:
            raise Failure(INPUT_INVALID, f"{mid}: placements[{index}] has unknown fields {unknown}", field=field + "/" + unknown[0])
        needs = row.get("needs")
        if needs not in KINDS:
            raise Failure(INPUT_INVALID, f"{mid}: placements[{index}].needs is one of {list(KINDS)}", field=field + "/needs")
        occupant = row.get("occupant")
        if occupant is not None and (not isinstance(occupant, str) or not occupant.strip() or len(occupant) > 120):
            raise Failure(INPUT_INVALID, f"{mid}: placements[{index}].occupant is the identity the module provides (at most 120 characters) or absent", field=field + "/occupant")
        count = row.get("count", 1)
        if not (count == "any" or (isinstance(count, int) and not isinstance(count, bool) and 1 <= count <= 256)):
            raise Failure(INPUT_INVALID, f"{mid}: placements[{index}].count is 1, an integer up to 256, or \"any\"", field=field + "/count")
        fallback = row.get("fallback", "refuse")
        if fallback not in FALLBACKS:
            raise Failure(INPUT_INVALID, f"{mid}: placements[{index}].fallback is one of {list(FALLBACKS)}", field=field + "/fallback")
        note = row.get("note")
        if note is not None and (not isinstance(note, str) or len(note) > 400):
            raise Failure(INPUT_INVALID, f"{mid}: placements[{index}].note is at most 400 characters", field=field + "/note")
        rows.append({"needs": needs, "occupant": occupant, "count": count, "fallback": fallback, **({"note": note} if note else {})})
    return rows


def resolve_placements(modules: list[dict], table: dict | None, target: str) -> dict:
    """Plan-time check for one target: which declared needs the table can satisfy and which it
    cannot. Rows are handed out in table order, an occupant match first, then any free row of
    the kind; a row is consumed once. No provider is generated; nothing is written."""
    rows = [r for r in (table or {}).get("placements", []) if isinstance(r, dict)] if table else []
    free = {i: r for i, r in enumerate(rows)}
    needs_out, refused, fallbacks = [], 0, 0
    kinds_present = Counter(r.get("kind") for r in rows)
    for module in modules:
        for index, need in enumerate(module.get("placements") or []):
            wanted = need["count"]
            picked = []
            candidates = [i for i, r in free.items() if r.get("kind") == need["needs"]]
            preferred = [i for i in candidates if need["occupant"] is not None and rows[i].get("occupant") == need["occupant"]]
            for i in preferred + [i for i in candidates if i not in preferred]:
                if wanted != "any" and len(picked) >= wanted:
                    break
                picked.append(i)
            for i in picked:
                free.pop(i, None)
            satisfied = (wanted == "any" and bool(picked)) or (wanted != "any" and len(picked) == wanted)
            row = {"module": module["id"], "need": index, "needs": need["needs"], "occupant": need["occupant"], "count": wanted,
                   "rows": [rows[i].get("id") for i in picked], "occupant_matched": bool(preferred and picked and picked[0] in preferred),
                   "fallback": need["fallback"]}
            if table is None:
                row["outcome"] = "no_table"
            elif satisfied:
                row["outcome"] = "satisfied"
            elif need["fallback"] == "refuse":
                row["outcome"] = "refused"
                refused += 1
            else:
                row["outcome"] = "fallback"
                fallbacks += 1
                if need["fallback"] in ("rotation-slot", "wunderfizz"):
                    row["fallback_rows_in_table"] = kinds_present.get(need["fallback"], 0)
            needs_out.append(row)
    if not needs_out:
        outcome, detail = "not_counted", "no member declares placements"
    elif table is None:
        outcome, detail = "not_counted", f"no location table for {target}; needs listed, nothing resolved"
    elif refused:
        outcome, detail = "failed", f"{refused} need(s) with fallback refuse have no row in the table for {target}"
    else:
        outcome, detail = "passed", f"every need has a row or a declared fallback in the table for {target}" + (f" ({fallbacks} on fallback)" if fallbacks else "")
    return {"target": target, "table": None if table is None else table.get("target"), "needs": needs_out,
            "free_rows": len(free), "outcome": outcome, "detail": detail}


def foundation_for_base(root: Path, base: str) -> str | None:
    matches = sorted(fid for fid, info in foundations(root).items() if info["base"] == base)
    return matches[0] if len(matches) == 1 else None
