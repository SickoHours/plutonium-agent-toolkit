"""Pinned backend downloads and the ``doctor`` presence check.

Setup downloads each pinned archive over HTTPS, verifies its SHA-256, extracts
it with path-safety checks into ``<backends_dir>/<id>``, and writes an install
receipt. Rerunning setup verifies existing installs and refuses to overwrite a
tree that changed. No vendor installer is executed, no PATH or registry is
modified and no game is touched.

Backends are cross-platform. A pin may carry per-platform downloads under
``downloads`` keyed by ``windows``/``linux``/``darwin``; a bare top-level
``url``/``sha256`` is treated as the Windows download for backward compatibility.
Where the current platform has no pinned download, setup reports the backend as
``override-required`` (not an error): install it yourself and point the toolkit
at it with ``PAT_BACKEND_<NAME>``. Executable names are resolved per OS (the
``.exe`` suffix is dropped off Windows).
"""
from __future__ import annotations

import hashlib
import json
import os
import platform as _platform
import re
import stat
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from ..core import config
from ..core.errors import BACKEND_FAILED, BACKEND_UNAVAILABLE, HASH_MISMATCH, INPUT_INVALID, INPUT_LIMIT, Failure
from ..core.receipts import inventory

PINS = Path(__file__).with_name("backends.json")
MAX_ARCHIVE = 2 * 1024**3
MAX_UNPACKED = 6 * 1024**3
MAX_ENTRIES = 150000
RESERVED = re.compile(r"(?i)^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$")


def platform_token() -> str:
    """windows / linux / darwin for the host running this process."""
    system = _platform.system()
    return {"Windows": "windows", "Linux": "linux", "Darwin": "darwin"}.get(system, system.lower())


def resolve_download(item: dict, token: str | None = None) -> dict | None:
    """The download pin for the current platform, or None if there is none.

    Prefers ``downloads.<token>``. Falls back to the bare top-level ``url``/
    ``sha256`` only on Windows, where legacy pins are Windows x64 archives.
    """
    token = token or platform_token()
    downloads = item.get("downloads") or {}
    if token in downloads:
        return {"id": item["id"], **downloads[token]}
    # A bare top-level url/sha256 is the Windows x64 archive, unless the program is marked
    # platform_independent (a pure-Python add-on such as Cast), in which case it installs anywhere.
    if item.get("url") and (item.get("platform_independent") or token == "windows"):
        return {"id": item["id"], "url": item["url"], "sha256": item.get("sha256"),
                "bytes": item.get("bytes"), "strip_root": item.get("strip_root", False)}
    return None


def pins() -> dict:
    data = json.loads(PINS.read_text(encoding="utf-8"))
    ids = [p["id"] for p in data["programs"]]
    if len(ids) != len(set(ids)):
        raise Failure(INPUT_INVALID, "Duplicate backend IDs in backends.json")
    return data


def program(pid: str) -> dict:
    for row in pins()["programs"]:
        if row["id"] == pid:
            return row
    raise Failure(INPUT_INVALID, f"Unknown backend ID {pid!r}", "Run: pat dev backends --json")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def safe_extract(archive: Path, dest: Path, strip_root: bool = False) -> None:
    with zipfile.ZipFile(archive) as z:
        rows = z.infolist()
        if len(rows) > MAX_ENTRIES or sum(r.file_size for r in rows) > MAX_UNPACKED:
            raise Failure(INPUT_LIMIT, "Archive exceeds extraction limits")
        seen: set[str] = set()
        planned = []
        root = None
        for row in rows:
            name = row.filename.replace("\\", "/")
            path = PurePosixPath(name)
            parts = list(path.parts)
            if path.is_absolute() or not parts or ".." in parts or ":" in name or "\x00" in name:
                raise Failure(INPUT_INVALID, f"Unsafe archive path: {name}")
            if stat.S_ISLNK(row.external_attr >> 16):
                raise Failure(INPUT_INVALID, "Archive links are refused")
            if strip_root:
                if root is None:
                    root = parts[0]
                if parts[0] != root:
                    raise Failure(INPUT_INVALID, "Expected a single archive root")
                parts = parts[1:]
            if not parts:
                continue
            for part in parts:
                if part.endswith((".", " ")) or RESERVED.match(part):
                    raise Failure(INPUT_INVALID, f"Reserved Windows path component: {part}")
            key = "/".join(parts).casefold()
            if key in seen:
                raise Failure(INPUT_INVALID, f"Case-colliding archive entries: {name}")
            seen.add(key)
            planned.append((row, dest.joinpath(*parts)))
        total = 0
        for row, target in planned:
            if row.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(row) as src, target.open("xb") as out:
                count = 0
                while block := src.read(1024 * 1024):
                    count += len(block)
                    total += len(block)
                    if count > row.file_size or total > MAX_UNPACKED:
                        raise Failure(INPUT_LIMIT, "Archive grew beyond declared size")
                    out.write(block)


def download(dl: dict, cache: Path) -> Path:
    if not dl.get("sha256"):
        raise Failure(INPUT_INVALID, f"{dl['id']} has no pinned hash for this platform; it cannot be installed by this release")
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"{dl['id']}-{dl['sha256'][:12]}.zip"
    if archive.exists():
        if digest(archive) != dl["sha256"]:
            raise Failure(HASH_MISMATCH, f"Cached archive for {dl['id']} does not match its pin; delete it manually after review")
        return archive
    if not dl["url"].startswith("https://"):
        raise Failure(INPUT_INVALID, "Only HTTPS downloads are permitted")
    tmp = archive.with_suffix(f".download-{uuid.uuid4().hex}")
    started = time.monotonic()
    total = 0
    with urllib.request.urlopen(dl["url"], timeout=60) as src, tmp.open("xb") as out:
        if not src.url.startswith("https://"):
            raise Failure(INPUT_INVALID, "Download redirected away from HTTPS")
        while block := src.read(1024 * 1024):
            total += len(block)
            if total > MAX_ARCHIVE or time.monotonic() - started > 1800:
                raise Failure(INPUT_LIMIT, "Download exceeded size or time limit")
            out.write(block)
    if digest(tmp) != dl["sha256"]:
        raise Failure(HASH_MISMATCH, f"{dl['id']}: downloaded bytes do not match the pinned SHA-256; failed download retained at {tmp}")
    tmp.rename(archive)
    return archive


def install(item: dict, backends_dir: Path, cache: Path) -> dict:
    dest = backends_dir / item["id"]
    receipts = backends_dir / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    receipt = receipts / f"{item['id']}.json"
    dl = resolve_download(item)
    if dest.exists():
        if not receipt.is_file():
            raise Failure(BACKEND_FAILED, f"{dest} exists without an install receipt; preserving it")
        saved = json.loads(receipt.read_text(encoding="utf-8"))
        saved_platform = saved.get("platform")
        if saved_platform and saved_platform != platform_token() and not item.get("platform_independent"):
            # A tree installed for another OS cannot be used here (its binaries will not resolve).
            return {"id": item["id"], "action": "override-required", "platform": platform_token(),
                    "installed_for": saved_platform, "hint": override_hint(item)}
        if (dl and saved["sha256"] != dl["sha256"]) or inventory(dest) != saved["files"]:
            raise Failure(BACKEND_FAILED, f"{item['id']}: installed files differ from the receipt; preserving them")
        return {"id": item["id"], "action": "verified", "files": len(saved["files"])}
    if dl is None:
        return {"id": item["id"], "action": "override-required", "platform": platform_token(),
                "hint": override_hint(item)}
    archive = download(dl, cache)
    stage = backends_dir / f"{item['id']}.staging-{uuid.uuid4().hex}"
    stage.mkdir(parents=True)
    safe_extract(archive, stage, dl.get("strip_root", False))
    files = inventory(stage)
    stage.rename(dest)
    receipt.write_text(json.dumps({"id": item["id"], "url": dl["url"], "sha256": dl["sha256"],
                                   "platform": platform_token(), "license": item.get("license"), "files": files}, indent=2) + "\n",
                       encoding="utf-8")
    return {"id": item["id"], "action": "installed", "files": len(files)}


def setup(only: list[str] | None = None, plan: bool = False) -> dict:
    cfg = config.load()
    backends_dir = Path(cfg["backends_dir"])
    items = pins()["programs"]
    if only:
        unknown = set(only) - {p["id"] for p in items}
        if unknown:
            raise Failure(INPUT_INVALID, f"Unknown backend IDs: {sorted(unknown)}")
        items = [p for p in items if p["id"] in only]
    else:
        items = [p for p in items if not p["optional"]]
    token = platform_token()
    if plan:
        programs = [dict(p, download_available=resolve_download(p) is not None) for p in items]
        return {"plan": True, "platform": token, "destination": str(backends_dir),
                "programs": programs, "executes_installers": False}
    lock = backends_dir / "setup.lock"
    backends_dir.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise Failure("busy", "Another setup is running or an interrupted setup left setup.lock; inspect before removing it") from exc
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        results = [install(item, backends_dir, backends_dir / "download-cache") for item in items]
    finally:
        lock.unlink(missing_ok=True)
    return {"destination": str(backends_dir), "platform": token, "results": results, "game_touched": False}


# ----- executable resolution -----------------------------------------------------------

# name -> (program_id, Windows-relative path). The .exe suffix is dropped off Windows.
EXECUTABLES = {
    "gsc": ("gsc", "gsc-tool.exe"),
    "linker": ("oat", "Linker.exe"),
    "unlinker": ("oat", "Unlinker.exe"),
    "image": ("oat", "ImageConverter.exe"),
    "ffmpeg": ("ffmpeg", "bin/ffmpeg.exe"),
    "ffprobe": ("ffmpeg", "bin/ffprobe.exe"),
    "blender": ("blender", "blender.exe"),
    "lua": ("lua", "CoDLuaDecompiler.exe"),
    "greyhound": ("greyhound", "Greyhound.exe"),
    "husky": ("husky", "Husky.exe"),
    "c2m": ("c2m", "C2M.exe"),
}

# program_id -> [backend names it provides], for override-aware doctor reporting.
PROGRAM_EXECUTABLES: dict[str, list[str]] = {}
for _name, (_pid, _rel) in EXECUTABLES.items():
    PROGRAM_EXECUTABLES.setdefault(_pid, []).append(_name)


def relative(name: str) -> str:
    """Per-OS relative path of a backend binary under ``<backends_dir>/<program_id>``."""
    _pid, win_rel = EXECUTABLES[name]
    if os.name == "nt":
        return win_rel
    return win_rel[:-4] if win_rel.lower().endswith(".exe") else win_rel


def override_for(name: str) -> Path | None:
    value = os.environ.get("PAT_BACKEND_" + name.upper())
    if not value:
        return None
    p = Path(value)
    if not p.is_absolute() or not p.is_file():
        raise Failure(BACKEND_UNAVAILABLE, f"PAT_BACKEND_{name.upper()} must be an absolute path to an existing file")
    return p


def _override_ok(name: str) -> Path | None:
    """override_for without raising; an invalid override reads as absent for doctor."""
    try:
        return override_for(name)
    except Failure:
        return None


def override_hint(item: dict) -> str:
    """How to supply a backend on a platform with no pinned build."""
    names = PROGRAM_EXECUTABLES.get(item["id"], [])
    name = item.get("name", item["id"])
    if names:
        vars_ = ", ".join(f"PAT_BACKEND_{n.upper()}" for n in names)
        return f"No pinned {platform_token()} build. Install {name} and set {vars_} to the binaries."
    # Directory-resolved backend (e.g. the Cast Blender add-on): no PAT_BACKEND override.
    return (f"No pinned {platform_token()} build. Install {name} into the backends directory under "
            f"'{item['id']}/' (it is resolved by directory, not a PAT_BACKEND override).")


def doctor() -> dict:
    cfg = config.load()
    backends_dir = Path(cfg["backends_dir"])
    token = platform_token()
    rows = []
    for item in pins()["programs"]:
        names = PROGRAM_EXECUTABLES.get(item["id"], [])
        overrides = {}
        if names:
            # An executable backend is present when every binary resolves, per binary, by an
            # override or a pinned file. Mixed override/pinned is fine.
            per = {}
            for name in names:
                ov = _override_ok(name)
                if ov is not None:
                    overrides[name] = str(ov)
                    per[name] = "override"
                elif (backends_dir / item["id"] / relative(name)).is_file():
                    per[name] = "pinned"
                else:
                    per[name] = "missing"
            present = all(state != "missing" for state in per.values())
            kinds = set(per.values())
            source = ("missing" if not present else
                      "override" if kinds == {"override"} else
                      "pinned" if kinds == {"pinned"} else "mixed")
        else:
            # Directory-resolved backend (e.g. Cast): check its declared files exist.
            provides = item.get("provides", [])
            present = bool(provides) and all((backends_dir / item["id"] / rel).exists() for rel in provides)
            source = "pinned" if present else "missing"
        rows.append({"id": item["id"], "name": item["name"], "optional": item["optional"],
                     "present": present, "source": source, "overrides": overrides,
                     "path": str(backends_dir / item["id"]),
                     "download_available": resolve_download(item, token) is not None})
    required_ok = all(r["present"] for r in rows if not r["optional"])
    return {"ok": required_ok, "platform": token, "backends_dir": str(backends_dir), "backends": rows,
            "verification": "filesystem presence or override resolution only; execution and gameplay are separate facts"}


def executable(name: str) -> list[str]:
    """Return the argv prefix for a backend executable.

    ``PAT_BACKEND_<NAME>`` overrides the resolved path; a ``.py`` override is run
    through the current interpreter. The override is the supported way to supply a
    backend on a platform with no pinned download. It never changes what is pinned.
    """
    import sys

    if name not in EXECUTABLES:
        raise Failure(INPUT_INVALID, f"Unknown backend executable {name!r}")
    override = override_for(name)
    if override is not None:
        return [sys.executable, str(override)] if override.suffix.lower() == ".py" else [str(override)]
    program_id = EXECUTABLES[name][0]
    path = Path(config.load()["backends_dir"]) / program_id / relative(name)
    if not path.is_file():
        raise Failure(BACKEND_UNAVAILABLE, f"Backend {name} is not installed at {path}",
                      f"Run: pat dev setup --only {program_id} (or set PAT_BACKEND_{name.upper()} to an installed binary)")
    return [str(path)]
