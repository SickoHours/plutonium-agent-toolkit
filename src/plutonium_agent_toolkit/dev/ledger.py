"""The evidence ledger: typed, scoped rows in ``evidence.json`` beside ``module.json``.

Provenance is a ledger, not a flag. A module's history is a list of rows, each of one type
(``lineage``, ``authored``, ``accepted-in-pack``, ``extracted-from-release``, ``built-alone``,
``agent-reviewed``, ``game-tested``, ``player-accepted``, ``known-issue``), each scoped to a base or foundation
and a map set, each pointing at the record that supports it and carrying a hash where one
exists. Rows coexist; nothing collapses them. The six facts (offline verified, installed,
launched, loaded and playable, captured, player accepted) are derived for display only, per
scope, and a fact with no row of the matching type stays unknown (``null``). Rows about a
composition the module was part of (``accepted-in-pack``) never feed the facts: nothing is
inferred from a pack that used a module. The format is specified in ``docs/evidence-ledger.md``.

``validate`` checks a ledger and collects one diagnostic per bad row; ``facts`` derives the
per-scope facts from valid rows; ``add_rows`` appends rows through that same validator, and
``propose`` drafts a ledger for one workspace module from the workspace registry and the
module's docs without writing anything.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import stat
import subprocess
from datetime import datetime
from pathlib import Path, PureWindowsPath

try:                                    # POSIX: the advisory lock two appends serialise on
    import fcntl
except ImportError:                     # pragma: no cover - Windows has no fcntl
    fcntl = None
try:                                    # Windows: the same lock through the C runtime
    import msvcrt
except ImportError:                     # pragma: no cover - POSIX has no msvcrt
    msvcrt = None

from ..core.errors import (BUSY, INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING, INVALID_ARGUMENTS,
                           OPERATION_FAILED, ROW_DUPLICATE, Failure)
from .compositions import BASE, MAP, _fields, _pointer

PROTOCOL = "pat.module-ledger/1"
PROPOSAL_PROTOCOL = "pat.module-ledger-proposal/1"
ADD_PROTOCOL = "pat.module-ledger-add/1"
FILENAME = "evidence.json"
TYPES = ("lineage", "authored", "accepted-in-pack", "extracted-from-release", "built-alone",
         "agent-reviewed", "game-tested", "player-accepted", "known-issue")
FACTS = ("offline_verified", "installed", "launched", "loaded_and_playable", "captured", "player_accepted")
OBSERVED = ("installed", "launched", "loaded_and_playable", "captured")
MAX_BYTES = 1024 * 1024
MAX_ROWS = 1024
MAX_DIAGNOSTICS = 32
MAX_TEXT = 2000
MAX_LIST = 64
MAX_ROW_FILES = 64
MAX_ROW_BYTES = 256 * 1024
# Windows only: msvcrt.locking blocks for about ten seconds per attempt, so this is a minute of
# waiting for whichever process holds the ledger before the append reports busy. flock waits.
LOCK_ATTEMPTS = 6
# Each of the two read-only git questions a known-issue row's fix is placed by.
GIT_TIMEOUT = 10
SHA256 = re.compile(r"^[0-9a-f]{64}\Z")
COMMIT = re.compile(r"^[0-9a-f]{7,40}\Z")
# The commit a known-issue row is closed by is a whole one: an abbreviation is a prefix that
# means one commit in the repository it was written in and may mean another, or none, here.
CLOSES_WITH = re.compile(r"^[0-9a-f]{40}\Z")
FOUNDATION = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}\Z")
# A survival location: a fenced area of a stock map with its own route (Reimagined's or QoL's
# Crazy Place, Diner, Cell Block). A row scoped to one never collapses into the parent map.
LOCATION = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}\Z")
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})?)?\Z")
SOURCE_MAP = re.compile(r"^zm_[a-z0-9_]{1,60}\Z")
COMMON = {"type", "scope", "at", "note", "record", "package_sha256"}
# Fields beyond COMMON per row type: (allowed, required). Lineage keeps the shape of the
# module.json field it came from and is scoped by its own game and map.
SHAPES = {
    "lineage": ({"type", "game", "map", "source", "note"}, {"game", "map", "source"}),
    "authored": ({"by", "parent", "changes"}, {"scope"}),
    "accepted-in-pack": ({"pack", "verdict", "reporter", "not_covered"}, {"pack", "scope", "record"}),
    "extracted-from-release": ({"release", "use", "commit"}, {"release", "use", "scope"}),
    "built-alone": ({"receipt", "offline_verified", "parent"}, {"receipt", "scope", "offline_verified"}),
    "agent-reviewed": ({"by", "outcome"}, {"outcome", "scope"}),
    "game-tested": ({"run", "result", "capture", *OBSERVED}, {"run", "result", "scope"}),
    "player-accepted": ({"outcome", "reporter", "quote", "not_covered", "supersedes"}, {"outcome", "record", "scope"}),
    # ``at`` is required here, where it is optional everywhere else: an issue is a thing that was
    # seen on a day, and a bug with no date cannot be read against the fix that closed it.
    "known-issue": ({"issue", "seen_by", "closes_with", "capture"}, {"issue", "seen_by", "scope", "at"}),
}
OUTCOMES = {"agent-reviewed": ("passed", "failed", "noted"), "player-accepted": ("accepted", "rejected")}
RESULTS = ("passed", "failed", "inconclusive")


# ----- validation ------------------------------------------------------------------------

def _text(value, what: str, limit: int = MAX_TEXT, field: str = "/") -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise Failure(INPUT_INVALID, f"{what} is a non-empty string of at most {limit} characters", field=field)
    return value


def _hash(value, what: str, field: str) -> str:
    if not isinstance(value, str) or not SHA256.match(value):
        raise Failure(INPUT_INVALID, f"{what} is a 64-character lowercase hex SHA-256", field=field)
    return value


def _bool(value, what: str, field: str) -> bool:
    if type(value) is not bool:
        raise Failure(INPUT_INVALID, f"{what} is true or false; leave it out when unknown", field=field)
    return value


def _date(value, field: str) -> str:
    """The shape, then the calendar. ``2026-99-99`` matches the digit shape and is not a day that
    happened; a row dated one is a row nothing can place in a history."""
    if not isinstance(value, str) or not DATE.match(value):
        raise Failure(INPUT_INVALID, "at is an ISO date (YYYY-MM-DD) or date-time", field=field)
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise Failure(INPUT_INVALID, f"at is a date that exists on the calendar: {value!r}", field=field) from exc
    return value


def _relative(text: str, what: str, field: str) -> str:
    """A pointer stays inside the workspace: forward-slash, relative, no parent steps."""
    if not isinstance(text, str) or not text or len(text) > 4096 or "\\" in text or text != text.strip():
        raise Failure(INPUT_INVALID, f"{what} path is a forward-slash relative path of at most 4096 characters", field=field)
    p = Path(text)
    if p.is_absolute() or PureWindowsPath(text).anchor or text.startswith("/") or ".." in p.parts or not p.parts:
        raise Failure(INPUT_INVALID, f"{what} path is relative to the workspace root and never climbs out of it: {text}", field=field)
    return text


def _record(value, what: str, field: str) -> dict:
    _fields(value, {"path", "sha256", "commit"}, {"path"}, what, field)
    result = {"path": _relative(value["path"], what, field + "/path")}
    if "sha256" in value:
        result["sha256"] = _hash(value["sha256"], f"{what} sha256", field + "/sha256")
    if "commit" in value:
        if not isinstance(value["commit"], str) or not COMMIT.match(value["commit"]):
            raise Failure(INPUT_INVALID, f"{what} commit is 7 to 40 lowercase hex characters", field=field + "/commit")
        result["commit"] = value["commit"]
    return result


def _scope(value, field: str) -> dict:
    """Where a row applies: a base token and/or a foundation id, a map set (``*`` for any), and
    optionally one survival ``location`` inside a single map.

    ``map`` (one id) is accepted and normalized to ``maps``. A ``location`` requires exactly one
    map and is part of the match: a row about the Diner is not a row about Green Run, and a
    query for Green Run alone does not see it. Descriptive keys (``mode``, ``players``,
    ``profile``) narrow the statement without affecting matching.
    """
    _fields(value, {"base", "foundation", "map", "maps", "location", "mode", "players", "profile"}, set(), "scope", field)
    result = {}
    if "base" in value:
        if not isinstance(value["base"], str) or not BASE.match(value["base"]):
            raise Failure(INPUT_INVALID, "scope base is a base token (lowercase letters and digits)", field=field + "/base")
        result["base"] = value["base"]
    if "foundation" in value:
        if not isinstance(value["foundation"], str) or not FOUNDATION.match(value["foundation"]):
            raise Failure(INPUT_INVALID, "scope foundation is a lowercase foundation id (letters, digits, dash)", field=field + "/foundation")
        result["foundation"] = value["foundation"]
    if "base" not in result and "foundation" not in result:
        raise Failure(INPUT_INVALID, "scope names a base token, a foundation id, or both", field=field)
    if ("map" in value) == ("maps" in value):
        raise Failure(INPUT_INVALID, "scope names exactly one of map (one id) or maps (a list of ids, or [\"*\"])", field=field)
    maps = [value["map"]] if "map" in value else value["maps"]
    if not isinstance(maps, list) or not maps or len(maps) > MAX_LIST or len(set(map(str, maps))) != len(maps) \
            or not all(isinstance(m, str) and (m == "*" or MAP.match(m)) for m in maps):
        raise Failure(INPUT_INVALID, f"scope maps is a non-empty list of at most {MAX_LIST} distinct map ids, or [\"*\"]", field=field + ("/map" if "map" in value else "/maps"))
    result["maps"] = list(maps)
    if "location" in value:
        if not isinstance(value["location"], str) or not LOCATION.match(value["location"]):
            raise Failure(INPUT_INVALID, "scope location is a lowercase survival-location id (letters, digits, underscore)", field=field + "/location")
        if len(maps) != 1 or maps[0] == "*":
            raise Failure(INPUT_INVALID, "scope location names one fenced area inside exactly one map", field=field + "/location")
        result["location"] = value["location"]
    if "mode" in value:
        if value["mode"] not in ("solo", "coop"):
            raise Failure(INPUT_INVALID, "scope mode is solo or coop", field=field + "/mode")
        result["mode"] = value["mode"]
    if "players" in value:
        if type(value["players"]) is not int or not 1 <= value["players"] <= 8:
            raise Failure(INPUT_INVALID, "scope players is an integer from 1 to 8", field=field + "/players")
        result["players"] = value["players"]
    if "profile" in value:
        result["profile"] = _text(value["profile"], "scope profile", 128, field + "/profile")
    return result


def _strings(value, what: str, field: str, limit: int = 400) -> list:
    if not isinstance(value, list) or len(value) > MAX_LIST or not all(isinstance(s, str) and s.strip() and len(s) <= limit for s in value):
        raise Failure(INPUT_INVALID, f"{what} is a list of at most {MAX_LIST} non-empty strings of at most {limit} characters", field=field)
    return list(value)


def _parent(value, field: str) -> dict:
    _fields(value, {"id", "declaration_sha256", "package_sha256", "record"}, {"id"}, "parent", field)
    if not isinstance(value["id"], str) or not re.fullmatch(r"[a-z0-9_-]{1,64}", value["id"]):
        raise Failure(INPUT_INVALID, "parent id is a module id or directory name", field=field + "/id")
    result = {"id": value["id"]}
    for key in ("declaration_sha256", "package_sha256"):
        if key in value:
            result[key] = _hash(value[key], f"parent {key}", field + "/" + key)
    if "record" in value:
        result["record"] = _record(value["record"], "parent record", field + "/record")
    return result


def _encodable(value, field: str) -> None:
    """Every string in the row survives a UTF-8 encode, keys included.

    ``"\\ud800"`` in a row file parses as JSON, is a perfectly ordinary Python string, and passes
    every shape check here -- and then the encoder refuses it when the ledger is written. A row
    that validates but cannot be written is a crash instead of a diagnostic, so the encode is
    part of validation and the refusal carries the pointer of the field that holds it.
    """
    stack = [(value, field)]
    while stack:
        item, where = stack.pop()
        if isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise Failure(INPUT_INVALID,
                              "text holds a character that is not valid UTF-8 (a lone surrogate)",
                              field=where) from exc
        elif isinstance(item, dict):
            for key, sub in item.items():
                stack.append((key, where))
                stack.append((sub, f"{where}/{key}" if isinstance(key, str) else where))
        elif isinstance(item, list):
            for index, sub in enumerate(item):
                stack.append((sub, f"{where}/{index}"))


def validate_row(row, field: str) -> dict:
    """One row, normalized. Raises the first defect with its JSON Pointer."""
    _encodable(row, field)
    if not isinstance(row, dict):
        raise Failure(INPUT_INVALID, "a ledger row is an object", field=field)
    kind = row.get("type")
    if kind not in TYPES:
        raise Failure(INPUT_INVALID, f"row type is one of {list(TYPES)}", field=field + "/type")
    allowed, required = SHAPES[kind]
    if kind == "lineage":
        _fields(row, allowed, required, "lineage row", field)
        if row["game"] not in ("t4", "t5") or not isinstance(row["map"], str) or not SOURCE_MAP.match(row["map"]):
            raise Failure(INPUT_INVALID, "lineage requires a T4/T5 game and a zm_ map ID", field=field)
        note = row.get("note", "")
        if not isinstance(note, str) or len(note) > 400:
            raise Failure(INPUT_INVALID, "lineage note is at most 400 characters", field=field + "/note")
        return {"type": kind, "game": row["game"], "map": row["map"],
                "source": _text(row["source"], "lineage source", 2048, field + "/source"), "note": note}
    _fields(row, allowed | COMMON, required | {"type"}, f"{kind} row", field)
    if row["scope"] is None:
        raise Failure(INPUT_INVALID, "scope is missing: name the base or foundation and the map set this row applies to", field=field + "/scope")
    out = {"type": kind, "scope": _scope(row["scope"], field + "/scope")}
    if "at" in row:
        out["at"] = _date(row["at"], field + "/at")
    if "note" in row:
        out["note"] = _text(row["note"], "note", MAX_TEXT, field + "/note")
    if "record" in row:
        out["record"] = _record(row["record"], "record", field + "/record")
    if "package_sha256" in row:
        out["package_sha256"] = _hash(row["package_sha256"], "package_sha256", field + "/package_sha256")
    for key in ("by", "pack", "release", "use", "verdict", "reporter", "quote"):
        if key in row:
            out[key] = _text(row[key], key, MAX_TEXT if key in ("verdict", "quote", "use") else 200, field + "/" + key)
    for key in ("not_covered", "changes"):
        if key in row:
            out[key] = _strings(row[key], key, field + "/" + key)
    if "parent" in row:
        out["parent"] = _parent(row["parent"], field + "/parent")
    if "commit" in row:
        if not isinstance(row["commit"], str) or not COMMIT.match(row["commit"]):
            raise Failure(INPUT_INVALID, "commit is 7 to 40 lowercase hex characters", field=field + "/commit")
        out["commit"] = row["commit"]
    if "supersedes" in row:
        out["supersedes"] = _hash(row["supersedes"], "supersedes", field + "/supersedes")
    if kind == "built-alone":
        out["receipt"] = _record(row["receipt"], "receipt", field + "/receipt")
        out["offline_verified"] = _bool(row["offline_verified"], "offline_verified", field + "/offline_verified")
        if "foundation" not in out["scope"]:
            raise Failure(INPUT_INVALID, "a built-alone row names the foundation it was built on in its scope", field=field + "/scope/foundation")
    if kind in OUTCOMES:
        if row["outcome"] not in OUTCOMES[kind]:
            raise Failure(INPUT_INVALID, f"{kind} outcome is one of {list(OUTCOMES[kind])}", field=field + "/outcome")
        out["outcome"] = row["outcome"]
    if kind == "game-tested":
        if not isinstance(row["run"], str) or not RUN_ID.match(row["run"]):
            raise Failure(INPUT_INVALID, "run is the run id (letters, digits, dot, underscore, colon, dash)", field=field + "/run")
        out["run"] = row["run"]
        if row["result"] not in RESULTS:
            raise Failure(INPUT_INVALID, f"result is one of {list(RESULTS)}", field=field + "/result")
        out["result"] = row["result"]
        if "capture" in row:
            out["capture"] = _record(row["capture"], "capture", field + "/capture")
        for key in OBSERVED:
            if key in row:
                out[key] = _bool(row[key], key, field + "/" + key)
    if kind == "known-issue":
        out["issue"] = _text(row["issue"], "issue", MAX_TEXT, field + "/issue")
        if "\n" in out["issue"] or "\r" in out["issue"]:
            raise Failure(INPUT_INVALID, "issue is one line", field=field + "/issue")
        out["seen_by"] = _text(row["seen_by"], "seen_by", 200, field + "/seen_by")
        if "closes_with" in row:
            if not isinstance(row["closes_with"], str) or not CLOSES_WITH.match(row["closes_with"]):
                raise Failure(INPUT_INVALID, "closes_with is the 40-hex commit that closes the issue", field=field + "/closes_with")
            out["closes_with"] = row["closes_with"]
        if "capture" in row:
            out["capture"] = _record(row["capture"], "capture", field + "/capture")
    return out


def validate(data) -> tuple[dict | None, list[dict]]:
    """The whole ledger. Returns (normalized ledger or None, diagnostics).

    A malformed header yields no ledger. A bad row is one diagnostic and is dropped from the
    normalized rows, so a display can still show the rows that are well-formed; the
    diagnostics say which rows were not counted. Nothing is inferred from a dropped row.
    """
    diagnostics = []
    try:
        _fields(data, {"schema", "subject", "rows"}, {"schema", "subject", "rows"}, "evidence.json")
        if data["schema"] != 1:
            raise Failure(INPUT_INVALID, "evidence.json: expected schema 1", field="/schema")
        _fields(data["subject"], {"id"}, {"id"}, "subject", "/subject")
        if not isinstance(data["subject"]["id"], str) or not re.fullmatch(r"[a-z0-9_]{1,64}", data["subject"]["id"]):
            raise Failure(INPUT_INVALID, "subject id is the module id from module.json", field="/subject/id")
        rows = data["rows"]
        if not isinstance(rows, list) or len(rows) > MAX_ROWS:
            raise Failure(INPUT_INVALID, f"rows is a list of at most {MAX_ROWS} rows", field="/rows")
    except Failure as exc:
        return None, [{"field": exc.details.get("field", "/"), "error_code": exc.code, "message": exc.message}]
    kept = []
    for index, row in enumerate(rows):
        try:
            kept.append(validate_row(row, f"/rows/{index}"))
        except Failure as exc:
            if len(diagnostics) < MAX_DIAGNOSTICS:
                diagnostics.append({"field": exc.details.get("field", f"/rows/{index}"), "error_code": exc.code, "message": exc.message})
    return {"schema": 1, "subject": {"id": data["subject"]["id"]}, "rows": kept}, diagnostics


# ----- reading -----------------------------------------------------------------------------

def read(path: Path) -> tuple[bytes, dict]:
    """One bounded read of a regular file; symlinks at the final component are refused."""
    if path.is_symlink() or not path.is_file():
        raise Failure(INPUT_MISSING, f"Ledger is missing or is a link: {path}")
    if path.stat().st_size > MAX_BYTES:
        raise Failure(INPUT_LIMIT, f"Ledger exceeds {MAX_BYTES} bytes: {path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise Failure(INPUT_MISSING, f"Cannot read ledger: {path} ({exc})") from exc
    if len(raw) > MAX_BYTES:
        raise Failure(INPUT_LIMIT, f"Ledger exceeds {MAX_BYTES} bytes: {path}")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError) as exc:
        raise Failure(INPUT_INVALID, f"Ledger is not valid JSON: {path}", field="/") from exc
    return raw, data


def inspect(path: Path, expected_id: str | None = None) -> dict:
    """The ledger summary `module inspect` attaches beside a declaration. Never raises for a
    malformed ledger: that is a diagnostic, and the declaration's own validity is untouched."""
    result = {"file": str(path), "sha256": None, "validation": "invalid", "rows": None, "types": None, "diagnostics": []}
    try:
        raw, data = read(path)
        result["sha256"] = hashlib.sha256(raw).hexdigest()
        ledger, diagnostics = validate(data)
        if ledger is not None and expected_id is not None and ledger["subject"]["id"] != expected_id:
            diagnostics.insert(0, {"field": "/subject/id", "error_code": INPUT_INVALID,
                                   "message": f"ledger subject {ledger['subject']['id']!r} is not the declaration's id {expected_id!r}"})
        result["diagnostics"] = diagnostics[:MAX_DIAGNOSTICS]
        if ledger is not None:
            result["rows"] = len(ledger["rows"])
            result["types"] = sorted({row["type"] for row in ledger["rows"]})
            if not diagnostics:
                result["validation"] = "valid"
    except Failure as exc:
        result["diagnostics"] = [{"field": exc.details.get("field", "/"), "error_code": exc.code, "message": exc.message}]
    return result


# ----- writing -----------------------------------------------------------------------------

def regular(path: Path) -> bool:
    """Whether a ledger is already on disk here, refusing a path that is not a regular file.

    A module directory holding ``evidence.json -> ~/.bashrc`` must not make this shelf write
    through the link, and a FIFO in that name must not make it block forever on an open that
    never returns. The check is one ``lstat``: nothing opens the path to find out what it is, so
    a FIFO is refused rather than waited on, and the symlink itself is what is inspected. A
    missing file is not a defect; it is the ledger this route is about to create.
    """
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise Failure(INPUT_INVALID, f"Cannot read what the ledger path is: {path} ({exc})",
                      ledger=str(path)) from exc
    if not stat.S_ISREG(mode):
        raise Failure(INPUT_INVALID, f"The ledger path is not a regular file: {path}",
                      "A ledger is a plain file beside module.json. A symlink, a FIFO or a directory "
                      "in its place is refused, never written through.", ledger=str(path))
    return True


def lock_path(path: Path) -> Path:
    """The sibling file the ledger's lock is taken on, never the ledger itself: the lock has to
    outlive the ``os.replace`` that swaps a new ledger in, and a lock held on a replaced file is
    a lock on nothing."""
    return path.parent / f".{path.name}.lock"


def _acquire(fd: int, target: Path) -> bool:
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_EX)
        return True
    if msvcrt is not None:              # pragma: no cover - exercised on Windows only
        for _ in range(LOCK_ATTEMPTS):
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                return True
            except OSError:
                continue
        raise Failure(BUSY, f"Another process is holding the ledger lock: {target}",
                      "Wait for the append that holds it to finish, then run this again.",
                      lock=str(target))
    return False                        # pragma: no cover - a host with neither module


def _release(fd: int, held: bool) -> None:
    if not held:
        return                          # pragma: no cover - a host with neither module
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_UN)
    elif msvcrt is not None:            # pragma: no cover - exercised on Windows only
        os.lseek(fd, 0, os.SEEK_SET)
        with contextlib.suppress(OSError):
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


@contextlib.contextmanager
def lock(path: Path):
    """An advisory exclusive lock on one ledger, held from the read through the replace.

    Two invocations appending to the same ``evidence.json`` must not both read the same book and
    then each write their own: the second write would drop the first row while both commands
    reported success, and a ledger that loses a row is a provenance record that lies. Holding
    this across the whole read-validate-append-write makes the second invocation wait for the
    first and then read the row it wrote.

    It is advisory and it is this shelf's: it serialises `pat`'s own writers on every host with
    ``fcntl`` or ``msvcrt``, and it does not stop a text editor. On a host with neither the lock
    is a no-op and the write is still all-or-nothing; only the ordering of two racing appends is
    unprotected there.
    """
    target = lock_path(path)
    try:
        fd = os.open(target, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError as exc:
        raise Failure(INPUT_INVALID, f"Cannot open the ledger lock beside it: {target} ({exc})",
                      "The ledger's directory has to be writable to append a row to it.",
                      lock=str(target)) from exc
    held = False
    try:
        held = _acquire(fd, target)
        yield target
    finally:
        _release(fd, held)
        os.close(fd)


def write_ledger(path: Path, text: str) -> str:
    """Write the whole ledger, or leave the one on disk exactly as it was.

    ``write_text`` truncates the file it is about to fill, so a full disk or an interrupt between
    the two leaves the evidence ledger empty or half written -- the rows destroyed are the ones
    nothing can derive a fact from again. Here the text goes to a sibling temporary file in the
    ledger's own directory (so the replace is a rename within one filesystem), is flushed and
    ``fsync``ed, and only a complete file is ``os.replace``d onto the ledger. A reader sees the
    book that was there or the book that was written, never a truncated one. Any failure removes
    the temporary file and leaves the original byte for byte.

    The caller holds ``lock`` around the read this text was computed from and this write.
    """
    path = Path(path)
    # A new file is created the way any other file here is (the umask decides); a ledger that is
    # already there keeps the permissions it already had, because a rename is not a chance to
    # change them.
    mode = stat.S_IMODE(path.lstat().st_mode) if regular(path) else None
    temp = path.parent / f".{path.name}.{os.getpid()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        with os.fdopen(os.open(temp, flags, 0o666), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temp, mode)
        os.replace(temp, path)
    except BaseException as exc:
        with contextlib.suppress(OSError):
            temp.unlink()
        if isinstance(exc, OSError):
            raise Failure(OPERATION_FAILED, f"Could not write the ledger: {path} ({exc})",
                          "The ledger on disk was not changed and the temporary file was removed.",
                          ledger=str(path)) from exc
        raise
    return str(path)


def serialise(data, raw: str | None = None) -> str:
    """JSON the way the file already writes it, so a record is an addition and not a reformat:
    the ledger and the registry differ on ``ensure_ascii`` across this shelf and a diff that
    re-escapes every accent hides the row that was added."""
    if raw is not None and json.dumps(data, indent=2) + "\n" != raw:
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return json.dumps(data, indent=2) + "\n"


def append_row(path: Path, row: dict, subject_id: str) -> tuple[str, int]:
    """The ledger at ``path`` with ``row`` appended, as the exact text to write.

    The header is created when the file is absent, the whole book goes through ``validate``
    before any of it reaches disk, and the file's own ``ensure_ascii`` is kept. Nothing is
    written here: the caller holds ``lock`` and writes the returned text with ``write_ledger``,
    so a route that writes several files together keeps its own all-or-nothing rollback, and a
    route that writes one file refuses with the file untouched. Returns the text and the number
    of rows it holds.

    The read is the bounded ``read``: an ``evidence.json`` past ``MAX_BYTES`` is refused with
    ``input_limit`` rather than parsed into memory. What counts as a ledger already on disk is
    ``regular``: a symlink or a FIFO in that name is refused here, instead of being taken for an
    absent ledger and then written through by the caller.
    """
    path = Path(path)
    if not regular(path):
        raw, book = None, {"schema": 1, "subject": {"id": subject_id}, "rows": []}
    else:
        data, book = read(path)
        raw = data.decode("utf-8")
        if not isinstance(book, dict) or not isinstance(book.get("rows"), list):
            raise Failure(INPUT_INVALID, f"Ledger has no rows list to append to: {path}", field="/rows")
        subject = book.get("subject")
        if isinstance(subject, dict) and subject.get("id") is not None and subject["id"] != subject_id:
            raise Failure(INPUT_INVALID,
                          f"Ledger subject is {subject['id']!r}, not this module's id {subject_id!r}: {path}",
                          "A module's ledger holds rows about that module only.", field="/subject/id")
    book["rows"] = [*book["rows"], row]
    normalized, diagnostics = validate(book)
    if normalized is None or diagnostics:
        raise Failure(INPUT_INVALID, f"The row does not validate against {PROTOCOL}: {diagnostics[:4]}",
                      "A ledger row is written through the same validator module state --ledger reads.",
                      field=(diagnostics[0].get("field") if diagnostics else "/"))
    return serialise(book, raw), len(normalized["rows"])


# ----- derivation ------------------------------------------------------------------------

def row_facts(row: dict) -> dict:
    """What one row states about the six facts. Only rows about the module alone speak; an
    accepted-in-pack row is history of a composition and says nothing here."""
    kind = row["type"]
    if kind == "built-alone":
        return {"offline_verified": row["offline_verified"]}
    if kind == "game-tested":
        return {key: row[key] for key in OBSERVED if key in row}
    if kind == "player-accepted":
        return {"player_accepted": row["outcome"] == "accepted"}
    return {}


def matches(row: dict, base=None, foundation=None, map_id=None, package=None, location=None) -> bool:
    """A scoped row matches a query when every given query key agrees with the row's scope.
    The location is always part of the match: a query without one sees only rows without one,
    and a query with one sees only rows with that one, so a location never collapses into
    its parent map in either direction."""
    if row["type"] == "lineage":
        return False
    scope = row["scope"]
    if base is not None and scope.get("base") != base:
        return False
    if foundation is not None and scope.get("foundation") != foundation:
        return False
    if map_id is not None and "*" not in scope["maps"] and map_id not in scope["maps"]:
        return False
    if scope.get("location") != location:
        return False
    if package is not None and row.get("package_sha256") != package:
        return False
    return True


def _combine(statements: list[tuple[int, bool]]) -> dict:
    """True when any row states true, false when rows state only false, null when no row speaks."""
    if not statements:
        return {"value": None, "rows": []}
    return {"value": any(v for _, v in statements), "rows": [i for i, _ in statements]}


def facts(ledger: dict, base=None, foundation=None, map_id=None, package=None, location=None) -> dict:
    """Per-fact, per-scope derivation. ``facts`` is the queried scope (every row that matches
    the query keys); ``scopes`` lists each (base, foundation, map, location) the rows name with
    its own six facts and the row numbers behind each. A fact no row of the matching type states
    is ``null``. ``history`` counts the rows that never feed a fact."""
    rows = ledger["rows"]
    queried = {fact: [] for fact in FACTS}
    per_scope: dict[tuple, dict] = {}
    history = {kind: 0 for kind in TYPES if kind not in ("built-alone", "game-tested", "player-accepted")}
    for index, row in enumerate(rows):
        stated = row_facts(row)
        if not stated:
            history[row["type"]] += 1
        if row["type"] == "lineage":
            continue
        if matches(row, base, foundation, map_id, package, location):
            for fact, value in stated.items():
                queried[fact].append((index, value))
        if not stated or (package is not None and row.get("package_sha256") != package):
            continue
        scope = row["scope"]
        for m in scope["maps"]:
            bucket = per_scope.setdefault((scope.get("base"), scope.get("foundation"), m, scope.get("location")), {fact: [] for fact in FACTS})
            for fact, value in stated.items():
                bucket[fact].append((index, value))
    scopes = [{"scope": {"base": key[0], "foundation": key[1], "map": key[2], "location": key[3]},
               "facts": {fact: _combine(bucket[fact]) for fact in FACTS}}
              for key, bucket in sorted(per_scope.items(), key=lambda item: tuple(str(k) for k in item[0]))]
    # The app's view: every {base, map, location} the rows name, foundations folded together,
    # a location kept apart from its parent map in its own row.
    by_target: dict[tuple, dict] = {}
    for key, bucket in per_scope.items():
        target = by_target.setdefault((key[0], key[2], key[3]), {fact: [] for fact in FACTS})
        for fact in FACTS:
            target[fact] += bucket[fact]
    targets = [{"base": key[0], "map": key[1], "location": key[2],
                "facts": {fact: _combine(sorted(set(bucket[fact]))) for fact in FACTS}}
               for key, bucket in sorted(by_target.items(), key=lambda item: tuple(str(k) for k in item[0]))]
    return {"query": {"base": base, "foundation": foundation, "map": map_id, "location": location, "package": package},
            "facts": {fact: _combine(queried[fact]) for fact in FACTS},
            "scopes": scopes, "by_target": targets, "history": history}


def query_from_target(key: str) -> dict:
    """A target key ``<foundation>/<map>/<mode>[/<location>]`` (``docs/target-sets.md``) as a
    ledger query: its foundation, map and location. The mode narrows nothing here; rows carry
    ``mode`` as description only."""
    from .targets import parse_key
    parts = parse_key(key)
    return {"foundation": parts["foundation"], "map_id": parts["map"], "location": parts["location"]}


def _git(directory: Path, *args: str):
    """One read-only git question in ``directory``, or ``None`` when git could not be asked.

    A ledger is a file in a directory that may be no repository at all, on a host that may have
    no git. Neither is a defect in the ledger, so neither raises here: the caller reads ``None``
    as "unanswered" and leaves the issue open.
    """
    try:
        return subprocess.run(["git", "-C", str(directory), *args], capture_output=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None


def _landed(directory: Path, commit: str) -> bool | None:
    """Whether ``commit`` is an ancestor of ``directory``'s current git head: whether the fix is
    in the tree this reader is holding. ``None`` when git could not say -- no git, no repository,
    or a commit this checkout does not know. Reads only: no write, no fetch."""
    head = _git(directory, "rev-parse", "HEAD")
    if head is None or head.returncode != 0:
        return None
    answer = _git(directory, "merge-base", "--is-ancestor", commit, "HEAD")
    if answer is None or answer.returncode not in (0, 1):
        return None
    return answer.returncode == 0


def known_issues(ledger: dict, directory: Path) -> dict:
    """The ``known-issue`` rows split into the ones still open here and the ones a fix closed.

    A row is closed when it names ``closes_with`` and that commit is an ancestor of the module
    directory's head: the fix is in the bytes this reader has. Everything else is open -- a row
    with no fix yet, a fix that is not in this checkout, and a fix nothing here can place. So a
    person holding a version from before the fix sees the bug they still have, and never stitches
    a broken version because the fix landed somewhere they are not. A row git could not answer
    for carries ``ancestry: "unknown"``, which is why it is open.
    """
    opened, closed, asked = [], [], {}
    for index, row in enumerate(ledger["rows"]):
        if row["type"] != "known-issue":
            continue
        entry = {"row": index, "issue": row["issue"], "seen_by": row["seen_by"],
                 "at": row.get("at"), "scope": row["scope"], "closes_with": row.get("closes_with")}
        commit = row.get("closes_with")
        if commit is None:
            opened.append(entry)
            continue
        if commit not in asked:
            asked[commit] = _landed(directory, commit)
        if asked[commit] is None:
            entry["ancestry"] = "unknown"
            opened.append(entry)
        elif asked[commit]:
            closed.append(entry)
        else:
            opened.append(entry)
    return {"open": opened, "closed": closed}


def report(path: Path, base=None, foundation=None, map_id=None, package=None, location=None, target=None) -> dict:
    """`module state --ledger`: read, validate, derive. An invalid ledger derives nothing.
    ``target`` is a target key; it supplies foundation, map and location and refuses to
    disagree with any of them given separately."""
    if target is not None:
        parts = query_from_target(target)
        for name, given, from_key in (("foundation", foundation, parts["foundation"]), ("map", map_id, parts["map_id"]), ("location", location, parts["location"])):
            if given is not None and given != from_key:
                raise Failure(INVALID_ARGUMENTS, f"--{name} {given!r} disagrees with --target {target!r} ({from_key!r})")
        foundation, map_id, location = parts["foundation"], parts["map_id"], parts["location"]
    path = Path(path)
    if path.is_dir():
        path = path / FILENAME
    raw, data = read(path)
    ledger, diagnostics = validate(data)
    result = {"protocol": PROTOCOL, "ledger": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
              "validation": "valid" if ledger is not None and not diagnostics else "invalid",
              "subject": ledger["subject"]["id"] if ledger else None, "rows": len(ledger["rows"]) if ledger else 0,
              "diagnostics": diagnostics}
    if ledger is None:
        result.update(facts({"rows": []}, base, foundation, map_id, package, location))
        result["reasons"] = ["ledger header is invalid; no fact was derived"]
    else:
        result.update(facts(ledger, base, foundation, map_id, package, location))
        result["reasons"] = [f"{len(diagnostics)} row(s) were not counted; see diagnostics"] if diagnostics else []
    # Open issues are read against the module directory the ledger sits in, because "is this bug
    # still in what I am holding" is a question about this checkout and no other.
    result["known_issues"] = known_issues(ledger, path.parent) if ledger is not None else {"open": [], "closed": []}
    return result


# ----- appending -----------------------------------------------------------------------------

def _normal_form(row: dict) -> str:
    """One validated row as the bytes two rows are the same row by: keys sorted, no spacing.
    ``validate_row`` has already turned ``map`` into ``maps`` and dropped nothing, so two rows
    written in different shorthands compare equal here."""
    return json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _declared_id(directory: Path) -> str:
    """The ``id`` of the ``module.json`` beside the ledger, which is the ledger's subject.

    Only the id is read: a declaration defect that has nothing to do with provenance must not
    stop a run from being recorded, and ``module inspect`` is the route that judges declarations.
    """
    declaration = directory / "module.json"
    if declaration.is_symlink() or not declaration.is_file():
        raise Failure(INPUT_MISSING, f"No module.json beside the ledger: {declaration}",
                      "A ledger's subject is the id declared beside it; point this route at a module directory.")
    if declaration.stat().st_size > MAX_BYTES:
        raise Failure(INPUT_LIMIT, f"Declaration exceeds {MAX_BYTES} bytes: {declaration}")
    try:
        data = json.loads(declaration.read_bytes().decode("utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        raise Failure(INPUT_INVALID, f"Declaration is not valid JSON: {declaration}", field="/") from exc
    module_id = data.get("id") if isinstance(data, dict) else None
    if not isinstance(module_id, str) or not re.fullmatch(r"[a-z0-9_]{1,64}", module_id):
        raise Failure(INPUT_INVALID, f"Declaration has no module id to be the ledger's subject: {declaration}",
                      "Run pat module inspect on the declaration first.", field="/id")
    return module_id


def _read_row_file(path: Path) -> list:
    """One ``--row`` file: a row object, or a list of row objects, in the order they were given."""
    if path.is_symlink() or not path.is_file():
        raise Failure(INPUT_MISSING, f"Row file is missing or is a link: {path}")
    if path.stat().st_size > MAX_ROW_BYTES:
        raise Failure(INPUT_LIMIT, f"Row file exceeds {MAX_ROW_BYTES} bytes: {path}")
    try:
        data = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        raise Failure(INPUT_INVALID, f"Row file is not valid JSON: {path}", field="/") from exc
    rows = data if isinstance(data, list) else [data]
    if not rows or len(rows) > MAX_ROWS:
        raise Failure(INPUT_INVALID, f"A row file holds one row object or a list of at most {MAX_ROWS}: {path}", field="/")
    return rows


def _row_index(pointer: str, fallback: int) -> int:
    parts = pointer.split("/")
    if len(parts) > 2 and parts[1] == "rows" and parts[2].isdigit():
        return int(parts[2])
    return fallback


def _appended_facts(ledger: dict, index: int, source: str) -> dict:
    """The six facts the ledger now derives for the scope the appended row names, one entry per
    map in that scope. A ``lineage`` row has no scope and feeds no fact, so it names none."""
    row = ledger["rows"][index]
    entry = {"row": index, "type": row["type"], "source": source, "scopes": []}
    if row["type"] == "lineage":
        return entry
    scope = row["scope"]
    for map_id in scope["maps"]:
        # ``*`` is passed through as the query, not dropped: ``matches`` reads it as "the rows
        # that speak for every map", so a row scoped to every map answers from the rows that
        # are themselves scoped to every map. Querying with no map instead would collect the
        # map-specific rows too, and one map's built-alone row would report this row
        # offline-verified everywhere, on maps nothing was ever built for.
        derived = facts(ledger, scope.get("base"), scope.get("foundation"),
                        map_id, None, scope.get("location"))
        entry["scopes"].append({"scope": {"base": scope.get("base"), "foundation": scope.get("foundation"),
                                          "map": map_id, "location": scope.get("location")},
                                "facts": derived["facts"]})
    return entry


def add_rows(path, row_files: list) -> dict:
    """``module ledger-add``: append rows to a module's ``evidence.json`` through the validator.

    Append-only: an existing row is never edited or removed, and a row whose normal form a row
    in the file already has is refused with ``row_duplicate`` rather than written twice, so a
    campaign that reruns its loop records each run once. All-or-nothing: every row is validated
    in the context of the whole ledger (the row count and the file size are the limits after the
    write, not before), and one bad row leaves the file untouched and reports every diagnostic
    with its row index and JSON Pointer. The file's own ``ensure_ascii`` and indent survive, the
    way ``dev/qualify.py`` writes the ``built-alone`` row it earns, so the diff is the rows added.

    An existing ledger that does not validate is refused, not appended to: a row added under a
    malformed one would be a fact recorded in a file nothing can derive from.

    The read, the validation and the write happen under this ledger's own ``lock``, so two
    campaign workers appending at once append both rows instead of one overwriting the other, and
    the write itself is ``write_ledger``: a temporary file, an ``fsync`` and a rename, so a
    failure leaves the rows that were already there.
    """
    path = Path(path)
    directory = path if path.is_dir() else path.parent
    if path.is_dir():
        path = path / FILENAME
    elif path.name != FILENAME:
        raise Failure(INVALID_ARGUMENTS, f"The ledger is a module directory or its {FILENAME}: {path}")
    if not row_files:
        raise Failure(INVALID_ARGUMENTS, "Give at least one --row <row.json>")
    if len(row_files) > MAX_ROW_FILES:
        raise Failure(INPUT_LIMIT, f"At most {MAX_ROW_FILES} --row files in one invocation; {len(row_files)} were given")
    subject = _declared_id(directory)

    with lock(path):
        return _append_locked(path, subject, row_files)


def _append_locked(path: Path, subject: str, row_files: list) -> dict:
    """The read, the validation and the write, with the ledger's lock held around all three.

    Nothing between reading the book and replacing it may be done on a book another invocation
    has since replaced: that is how a row is lost while both commands report success.
    """
    created = not regular(path)
    if created:
        previous, book = None, {"schema": 1, "subject": {"id": subject}, "rows": []}
    else:
        raw, book = read(path)
        previous = raw.decode("utf-8")
    existing, diagnostics = validate(book)
    if existing is None or diagnostics:
        raise Failure(INPUT_INVALID, f"The ledger already on disk does not validate; no row was appended: {path}",
                      "Fix the rows it already holds first; pat module state --ledger lists them.",
                      ledger=str(path), diagnostics=(diagnostics or [])[:MAX_DIAGNOSTICS])
    if existing["subject"]["id"] != subject:
        raise Failure(INPUT_INVALID,
                      f"Ledger subject {existing['subject']['id']!r} is not the declaration's id {subject!r}: {path}",
                      "A ledger belongs to the module.json beside it; this row belongs in that module's ledger.",
                      ledger=str(path), subject=existing["subject"]["id"], declared=subject)

    rows_before = len(book["rows"])
    candidates, sources = [], []
    for name in row_files:
        for row in _read_row_file(Path(name)):
            candidates.append(row)
            sources.append(str(name))
    total = rows_before + len(candidates)
    if total > MAX_ROWS:
        raise Failure(INPUT_LIMIT, f"The ledger would hold {total} rows; a ledger holds at most {MAX_ROWS}",
                      ledger=str(path), rows_before=rows_before, rows_given=len(candidates))

    escapes = previous is None or json.dumps(book, indent=2) + "\n" == previous
    book["rows"] = list(book["rows"]) + candidates
    normalized, diagnostics = validate(book)
    if diagnostics:
        for row in diagnostics:
            index = _row_index(row["field"], rows_before)
            row["row"] = index
            row["source"] = sources[index - rows_before] if rows_before <= index < total else "already in the ledger"
        raise Failure(INPUT_INVALID,
                      f"{len(diagnostics)} of the {len(candidates)} row(s) given do not validate; nothing was written to {path}",
                      "Every row is checked the way pat module inspect checks the ledger; fix each pointer and run it again.",
                      ledger=str(path), rows_before=rows_before, diagnostics=diagnostics[:MAX_DIAGNOSTICS])

    seen = {}
    for index, row in enumerate(normalized["rows"][:rows_before]):
        seen.setdefault(_normal_form(row), index)
    for offset, row in enumerate(normalized["rows"][rows_before:]):
        form = _normal_form(row)
        if form in seen:
            index = rows_before + offset
            raise Failure(ROW_DUPLICATE,
                          f"Row {offset} of {sources[offset]} is already row {seen[form]} of {path}; nothing was written",
                          "A ledger is append-only: a repeated fact is the row already there. Record a new fact as a new row.",
                          ledger=str(path), row=index, source=sources[offset], duplicate_of=seen[form])
        seen[form] = rows_before + offset

    # The rows are written as they were given, not as the validator normalized them: the shorthand
    # the author wrote (a single ``map``) is valid and re-reads identically, and every other record
    # this shelf writes keeps the author's shape too.
    #
    # ``serialise`` picks ``ensure_ascii`` by asking whether the escaped dump is the file's own
    # bytes. An appended row always changes those bytes, so the question is asked of the rows that
    # were already on disk: a file that escapes keeps escaping, one that does not keeps its UTF-8,
    # and the diff is the rows added either way. Indent is two spaces, as every record here is.
    text = serialise(book) if escapes else serialise(book, previous)
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise Failure(INPUT_LIMIT, f"The ledger would exceed {MAX_BYTES} bytes; nothing was written to {path}",
                      ledger=str(path), bytes=len(text.encode("utf-8")))
    write_ledger(path, text)

    appended = list(range(rows_before, total))
    return {"protocol": ADD_PROTOCOL, "ledger": str(path), "created": created, "subject": subject,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "rows_before": rows_before, "rows_after": total, "appended": appended,
            "validation": "valid", "diagnostics": [],
            "rows": [_appended_facts(normalized, index, sources[index - rows_before]) for index in appended]}

# ----- migration proposal ------------------------------------------------------------------

def _load_json(path: Path, limit: int = 16 * 1024 * 1024):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        return None
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return None


def _digest(path: Path) -> str | None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        return None
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _pointer_for(root: Path, text, sources: dict, notes: list, what: str) -> dict | None:
    """A registry path becomes a record pointer. Absolute paths and paths that leave the
    workspace are kept verbatim so the worker sees them, and noted; validation flags them."""
    if not isinstance(text, str) or not text.strip():
        return None
    p = Path(text)
    if p.is_absolute():
        try:
            rel = p.resolve().relative_to(root.resolve())
        except (ValueError, OSError):
            notes.append(f"{what}: absolute path outside the workspace kept verbatim; relativize or replace it before writing: {text}")
            return {"path": text}
        text = rel.as_posix()
    pointer = {"path": text}
    digest = _digest(root / text)
    if digest is None:
        notes.append(f"{what}: {text} is not a readable file in the workspace; the pointer has no hash")
    else:
        pointer["sha256"] = digest
        sources[text] = digest
    return pointer


def _scope_from(row: dict, foundations: dict) -> dict | None:
    foundation = row.get("foundation")
    base = row.get("base")
    if isinstance(foundation, str) and base is None:
        base = foundations.get(foundation)
    map_id = row.get("map")
    scope = {}
    if isinstance(base, str):
        scope["base"] = base
    if isinstance(foundation, str):
        scope["foundation"] = foundation
    if isinstance(map_id, str):
        scope["maps"] = [map_id]
        # A record scoped {base, map, location} (docs/target-sets.md) keeps its location: a
        # verdict on the Diner is not a verdict on Green Run.
        if isinstance(row.get("location"), str):
            scope["location"] = row["location"]
    return scope or None


def _declared_scope(declaration: dict, notes: list, what: str) -> dict | None:
    """A row about the module alone whose source names no base or map takes the declaration's
    own bases and maps, which are the module's statement about itself, never a pack's. The
    worker is told so it can narrow the scope to what the record actually covered."""
    bases = declaration.get("bases")
    maps = declaration.get("maps")
    if not (isinstance(bases, list) and len(bases) == 1 and isinstance(bases[0], str)) or not isinstance(maps, list) or not maps \
            or not all(isinstance(m, str) for m in maps):
        notes.append(f"{what}: names no foundation or map and module.json declares several bases; fill the scope before writing")
        return None
    notes.append(f"{what}: names no foundation or map; scope taken from module.json bases/maps ({bases[0]}: {', '.join(maps)}), narrow it to what the record covered")
    return {"base": bases[0], "maps": list(maps)}


def _acceptance_signal(record: dict) -> bool:
    status = record.get("status")
    return any(record.get(key) is True for key in ("accepted", "player_accepted", "gameplay_accepted")) \
        or (isinstance(status, str) and status.startswith("accepted"))


def propose(workspace: str, module_id: str) -> dict:
    """Draft ``evidence.json`` rows for ``modules/<module_id>`` from the workspace registry's
    ``build_revisions`` and the module's docs. Prints the proposal; writes nothing."""
    if not re.fullmatch(r"[a-z0-9_-]{1,64}", module_id or ""):
        raise Failure(INVALID_ARGUMENTS, "module id is the directory name under modules/ (lowercase letters, digits, underscore, dash)")
    root = Path(workspace).expanduser()
    if not root.is_dir():
        raise Failure(INPUT_MISSING, f"Workspace directory is missing: {root}")
    directory = root / "modules" / module_id
    declaration = _load_json(directory / "module.json", 256 * 1024)
    if not isinstance(declaration, dict):
        raise Failure(INPUT_MISSING, f"Module directory has no readable module.json: modules/{module_id}")
    subject = declaration.get("id") if isinstance(declaration.get("id"), str) else module_id
    notes, sources, rows = [], {}, []
    if (directory / FILENAME).exists():
        notes.append(f"modules/{module_id}/{FILENAME} already exists; this proposal is a fresh draft, not a merge")
    foundations = {}
    foundation_root = root / "foundations"
    if foundation_root.is_dir():
        for file in sorted(foundation_root.glob("*.json")):
            info = _load_json(file, 1024 * 1024)
            if isinstance(info, dict) and isinstance(info.get("id"), str) and isinstance(info.get("profile_prefix"), str):
                foundations[info["id"]] = info["profile_prefix"]
    # 1. The declaration's lineage field, verbatim, is the first row type.
    lineage = declaration.get("lineage")
    for entry in ([lineage] if isinstance(lineage, dict) else lineage if isinstance(lineage, list) else []):
        if isinstance(entry, dict):
            rows.append({"type": "lineage", **{k: entry[k] for k in ("game", "map", "source", "note") if k in entry}})
    # 2. The registry row: by id, or by the modular directory it names.
    registry = _load_json(root / "registry" / "t6-modules.json")
    catalog = registry.get("modules") if isinstance(registry, dict) else None
    catalog = catalog if isinstance(catalog, list) else []
    top_evidence = registry.get("evidence", {}) if isinstance(registry, dict) else {}
    # The registry row is found by the directory it names, else by an id equal to the directory
    # name or the declaration id (dashes and underscores are interchangeable between the two).
    names = {module_id, subject, module_id.replace("_", "-"), subject.replace("_", "-")}
    registered = next((m for m in catalog if isinstance(m, dict) and isinstance(m.get("modular"), dict)
                       and m["modular"].get("directory") == f"modules/{module_id}"), None) \
        or next((m for m in catalog if isinstance(m, dict) and m.get("id") in names), None)
    if registered is None:
        notes.append(f"registry/t6-modules.json has no row for {module_id}; only the module's own files were read")
        registered = {}
    modular = registered.get("modular") if isinstance(registered.get("modular"), dict) else {}
    accepted_doc = _load_json(directory / "docs" / "ACCEPTED.json", 4 * 1024 * 1024)
    accepted_doc = accepted_doc if isinstance(accepted_doc, dict) else None
    verdict_hashes = set()
    if accepted_doc and isinstance(accepted_doc.get("verdicts"), list):
        pointer = _pointer_for(root, f"modules/{module_id}/docs/ACCEPTED.json", sources, notes, "ACCEPTED.json")
        for verdict in accepted_doc["verdicts"]:
            if not isinstance(verdict, dict) or verdict.get("outcome") not in ("accepted", "rejected"):
                continue
            scope_in = verdict.get("scope") if isinstance(verdict.get("scope"), dict) else {}
            build = verdict.get("build") if isinstance(verdict.get("build"), dict) else {}
            row = {"type": "player-accepted", "outcome": verdict["outcome"], "record": pointer,
                   "scope": _scope_from(scope_in, foundations)}
            for key in ("mode", "players", "profile"):
                if key in scope_in and row["scope"] is not None:
                    row["scope"][key] = scope_in[key]
            if isinstance(verdict.get("at"), str):
                row["at"] = verdict["at"]
            if isinstance(verdict.get("reporter"), str):
                row["reporter"] = verdict["reporter"]
            if isinstance(verdict.get("quote"), str):
                row["quote"] = verdict["quote"]
            sha = build.get("mod_ff_sha256")
            if isinstance(sha, str) and SHA256.match(sha):
                row["package_sha256"] = sha
                verdict_hashes.add(sha)
            elif sha:
                notes.append(f"ACCEPTED.json verdict names a short package hash {sha!r}; the row carries no package_sha256")
            if isinstance(verdict.get("not_covered"), list):
                row["not_covered"] = [s for s in verdict["not_covered"] if isinstance(s, str)]
            if isinstance(verdict.get("supersedes"), str) and SHA256.match(verdict["supersedes"]):
                row["supersedes"] = verdict["supersedes"]
            rows.append(row)
    elif accepted_doc:
        notes.append("docs/ACCEPTED.json has no verdicts list; it was left as a pointer for the worker to read")
    # 3. build_revisions: built alone, observed in the game, accepted by the player.
    for revision in registered.get("build_revisions", []) if isinstance(registered.get("build_revisions"), list) else []:
        if not isinstance(revision, dict):
            continue
        rid = revision.get("id", "?")
        members = revision.get("modules")
        if (isinstance(members, list) and len(members) > 1) or revision.get("composition"):
            notes.append(f"build revision {rid!r} is a composition build; nothing is inferred from it for the module alone")
            continue
        scope = _scope_from(revision, foundations)
        sha = revision.get("sha256") if isinstance(revision.get("sha256"), str) and SHA256.match(revision.get("sha256", "")) else None
        receipt = _pointer_for(root, revision.get("receipt"), sources, notes, f"build revision {rid!r} receipt")
        evidence = _pointer_for(root, revision.get("evidence"), sources, notes, f"build revision {rid!r} evidence")
        if receipt is None:
            notes.append(f"build revision {rid!r} names no receipt; the built-alone row points at its evidence file instead and needs the receipt before it is worth much")
            receipt = evidence
        if scope is None:
            scope = _declared_scope(declaration, notes, f"build revision {rid!r}")
        elif "maps" not in scope:
            declared_maps = declaration.get("maps")
            if isinstance(declared_maps, list) and declared_maps and all(isinstance(m, str) for m in declared_maps):
                scope["maps"] = list(declared_maps)
                notes.append(f"build revision {rid!r} names no map; maps taken from module.json ({', '.join(declared_maps)}), narrow them to what the receipt covered")
            else:
                notes.append(f"build revision {rid!r} names no map; fill the scope before writing")
        built = {"type": "built-alone", "receipt": receipt or {"path": ""}, "scope": scope,
                 "offline_verified": revision.get("offline_verified") is True}
        if sha:
            built["package_sha256"] = sha
        for key in ("scope", "variant_scope", "note"):
            if isinstance(revision.get(key), str):
                built["note"] = revision[key]
                break
        rows.append(built)
        observed = {key: revision[key] for key in ("installed", "runtime_verified") if type(revision.get(key)) is bool}
        if observed.get("installed") or observed.get("runtime_verified"):
            tested = {"type": "game-tested", "run": revision.get("run_id") if isinstance(revision.get("run_id"), str) else f"registry:{rid}",
                      "result": "passed" if observed.get("runtime_verified") else "inconclusive", "scope": scope}
            if "installed" in observed:
                tested["installed"] = observed["installed"]
            if "runtime_verified" in observed:
                tested["loaded_and_playable"] = observed["runtime_verified"]
            if sha:
                tested["package_sha256"] = sha
            if evidence:
                tested["record"] = evidence
            if not isinstance(revision.get("run_id"), str):
                notes.append(f"build revision {rid!r} names no run id; the game-tested row carries a registry placeholder, replace it with the run")
            for key in ("runtime_scope", "testing"):
                if isinstance(revision.get(key), str):
                    tested["note"] = revision[key]
                    break
            rows.append(tested)
        if revision.get("player_accepted") is True and sha not in verdict_hashes:
            record = _pointer_for(root, f"modules/{module_id}/docs/ACCEPTED.json", sources, notes, "ACCEPTED.json") \
                if (directory / "docs" / "ACCEPTED.json").is_file() else evidence
            accepted = {"type": "player-accepted", "outcome": "accepted", "scope": scope, "record": record or {"path": ""}}
            if sha:
                accepted["package_sha256"] = sha
            if isinstance(revision.get("player_acceptance_scope"), str):
                accepted["note"] = revision["player_acceptance_scope"]
            if record is None:
                notes.append(f"build revision {rid!r} says player accepted but names no verdict record; the row needs one")
            rows.append(accepted)
    # 4. Pack history: archive records the registry cites for an accepted status.
    status = registered.get("status", "")
    for path in registered.get("evidence", []) if isinstance(registered.get("evidence"), list) else []:
        if not isinstance(path, str) or not path.startswith("archive/"):
            continue
        if not path.endswith(".json"):
            notes.append(f"archive record {path} is prose; read it and add a row by hand if it carries a verdict")
            continue
        record = _load_json(root / path, 16 * 1024 * 1024)
        if not isinstance(record, dict) or not (isinstance(status, str) and status.startswith("accepted")) or not _acceptance_signal(record):
            continue
        pointer = _pointer_for(root, path, sources, notes, path)
        known = top_evidence.get(path, {}) if isinstance(top_evidence, dict) else {}
        if isinstance(known, dict) and isinstance(known.get("sha256"), str) and pointer.get("sha256") not in (None, known["sha256"]):
            notes.append(f"{path}: registry records sha256 {known['sha256']} but the file now hashes {pointer['sha256']}")
        pack = Path(path).parts[2] if len(Path(path).parts) > 2 else Path(path).stem
        row = {"type": "accepted-in-pack", "pack": pack, "record": pointer, "scope": _scope_from(record, foundations)}
        identities = known.get("top_level_build_identities", {}) if isinstance(known, dict) else {}
        sha = record.get("mod_ff_sha256") or (identities.get("mod_ff_sha256") if isinstance(identities, dict) else None)
        if isinstance(sha, str) and SHA256.match(sha):
            row["package_sha256"] = sha
        for key in ("accepted_utc", "accepted_on", "date"):
            if isinstance(record.get(key), str):
                row["at"] = record[key][:10] if not DATE.match(record[key]) else record[key]
                break
        for key in ("user_verdict", "verdict", "owner_verdict_summary", "state"):
            if isinstance(record.get(key), str):
                row["verdict"] = record[key]
                break
        if isinstance(record.get("scope"), str):
            row["note"] = record["scope"]
        if row["scope"] is None:
            notes.append(f"{path} names no map or foundation; fill the accepted-in-pack scope before writing")
        rows.append(row)
    # 5. LINEAGE.json: where the bytes came from, and the parent of an overlay.
    lineage_doc = _load_json(directory / "docs" / "LINEAGE.json", 4 * 1024 * 1024)
    if isinstance(lineage_doc, dict):
        parent = lineage_doc.get("parent") if isinstance(lineage_doc.get("parent"), dict) else {}
        if isinstance(parent.get("source"), str):
            row = {"type": "extracted-from-release", "release": parent["source"],
                   "use": registered.get("scope") if isinstance(registered.get("scope"), str) else "see the release record",
                   "scope": _scope_from({"foundation": parent.get("evidence_base"), "map": parent.get("map")}, foundations)}
            if isinstance(parent.get("source_commit"), str) and COMMIT.match(parent["source_commit"]):
                row["commit"] = parent["source_commit"]
            if isinstance(parent.get("mod_ff_sha256"), str) and SHA256.match(parent["mod_ff_sha256"]):
                row["package_sha256"] = parent["mod_ff_sha256"]
            pointer = _pointer_for(root, parent["source"], sources, notes, "LINEAGE.json parent source")
            if pointer:
                row["record"] = pointer
            if row["scope"] is None:
                notes.append("LINEAGE.json parent names no evidence_base or map; fill the extracted-from-release scope before writing")
            rows.append(row)
        elif isinstance(parent.get("module_id"), str):
            row = {"type": "authored", "scope": _scope_from(lineage_doc, foundations),
                   "parent": {"id": parent["module_id"]}}
            for key in ("declaration_sha256", "mod_ff_sha256"):
                if isinstance(parent.get(key), str) and SHA256.match(parent[key]):
                    row["parent"]["package_sha256" if key == "mod_ff_sha256" else key] = parent[key]
            if isinstance(parent.get("declaration"), str):
                pointer = _pointer_for(root, parent["declaration"], sources, notes, "LINEAGE.json parent declaration")
                if pointer:
                    row["parent"]["record"] = pointer
            if isinstance(lineage_doc.get("changes"), list):
                row["changes"] = [s for s in lineage_doc["changes"] if isinstance(s, str)]
            rows.append(row)
    # 6. The registry's standalone review, when a test record backs it.
    test_record = directory / "docs" / "TEST.md"
    if registered.get("standalone_module_verified") is True and test_record.is_file():
        row = {"type": "agent-reviewed", "outcome": "noted", "scope": _scope_from(modular, foundations),
               "record": _pointer_for(root, f"modules/{module_id}/docs/TEST.md", sources, notes, "TEST.md")}
        if isinstance(registered.get("dependency_audit"), str):
            row["note"] = registered["dependency_audit"]
        if row["scope"] is None:
            row["scope"] = _declared_scope(declaration, notes, "registry standalone review")
        rows.append(row)
    proposal = {"schema": 1, "subject": {"id": subject}, "rows": rows}
    ledger, diagnostics = validate(proposal)
    # Derived from the rows that validate, so the worker sees what the draft would state; a
    # row with a diagnostic is not counted, exactly as `module state --ledger` would treat it.
    derived = facts(ledger) if ledger is not None else None
    return {"protocol": PROPOSAL_PROTOCOL, "workspace": str(root), "module": module_id, "directory": f"modules/{module_id}",
            "target": f"modules/{module_id}/{FILENAME}", "written": False, "registry_row": registered.get("id"),
            "proposal": proposal, "validation": "valid" if ledger is not None and not diagnostics else "invalid",
            "diagnostics": diagnostics, "notes": notes, "sources": sources, "derived": derived}
