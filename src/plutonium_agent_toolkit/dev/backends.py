"""Pinned backend downloads and the ``doctor`` presence check.

Setup downloads each pinned archive over HTTPS, verifies its SHA-256, extracts
it with path-safety checks into ``<backends_dir>/<id>``, and writes an install
receipt. Rerunning setup verifies existing installs and refuses to overwrite a
tree that changed. No vendor installer is executed, no PATH or registry is
modified and no game is touched.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from ..core import config
from ..core.errors import BACKEND_FAILED, HASH_MISMATCH, INPUT_INVALID, INPUT_LIMIT, Failure
from ..core.receipts import inventory

PINS = Path(__file__).with_name("backends.json")
MAX_ARCHIVE = 2 * 1024**3
MAX_UNPACKED = 6 * 1024**3
MAX_ENTRIES = 150000
RESERVED = re.compile(r"(?i)^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$")


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


def download(item: dict, cache: Path) -> Path:
    if not item.get("sha256"):
        raise Failure(INPUT_INVALID, f"{item['id']} has no pinned hash yet; it cannot be installed by this release")
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"{item['id']}-{item['sha256'][:12]}.zip"
    if archive.exists():
        if digest(archive) != item["sha256"]:
            raise Failure(HASH_MISMATCH, f"Cached archive for {item['id']} does not match its pin; delete it manually after review")
        return archive
    if not item["url"].startswith("https://"):
        raise Failure(INPUT_INVALID, "Only HTTPS downloads are permitted")
    tmp = archive.with_suffix(f".download-{uuid.uuid4().hex}")
    started = time.monotonic()
    total = 0
    with urllib.request.urlopen(item["url"], timeout=60) as src, tmp.open("xb") as out:
        if not src.url.startswith("https://"):
            raise Failure(INPUT_INVALID, "Download redirected away from HTTPS")
        while block := src.read(1024 * 1024):
            total += len(block)
            if total > MAX_ARCHIVE or time.monotonic() - started > 1800:
                raise Failure(INPUT_LIMIT, "Download exceeded size or time limit")
            out.write(block)
    if digest(tmp) != item["sha256"]:
        raise Failure(HASH_MISMATCH, f"{item['id']}: downloaded bytes do not match the pinned SHA-256; failed download retained at {tmp}")
    tmp.rename(archive)
    return archive


def install(item: dict, backends_dir: Path, cache: Path) -> dict:
    dest = backends_dir / item["id"]
    receipts = backends_dir / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    receipt = receipts / f"{item['id']}.json"
    if dest.exists():
        if not receipt.is_file():
            raise Failure(BACKEND_FAILED, f"{dest} exists without an install receipt; preserving it")
        saved = json.loads(receipt.read_text(encoding="utf-8"))
        if saved["sha256"] != item["sha256"] or inventory(dest) != saved["files"]:
            raise Failure(BACKEND_FAILED, f"{item['id']}: installed files differ from the receipt; preserving them")
        return {"id": item["id"], "action": "verified", "files": len(saved["files"])}
    archive = download(item, cache)
    stage = backends_dir / f"{item['id']}.staging-{uuid.uuid4().hex}"
    stage.mkdir(parents=True)
    safe_extract(archive, stage, item.get("strip_root", False))
    files = inventory(stage)
    stage.rename(dest)
    receipt.write_text(json.dumps({"id": item["id"], "url": item["url"], "sha256": item["sha256"],
                                   "license": item.get("license"), "files": files}, indent=2) + "\n",
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
    if plan:
        return {"plan": True, "destination": str(backends_dir), "programs": items, "executes_installers": False}
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
    return {"destination": str(backends_dir), "results": results, "game_touched": False}


def doctor() -> dict:
    cfg = config.load()
    backends_dir = Path(cfg["backends_dir"])
    rows = []
    for item in pins()["programs"]:
        present = all((backends_dir / item["id"] / rel).exists() for rel in item.get("provides", []))
        rows.append({"id": item["id"], "name": item["name"], "optional": item["optional"],
                     "present": present, "path": str(backends_dir / item["id"]),
                     "pinned": bool(item.get("sha256"))})
    required_ok = all(r["present"] for r in rows if not r["optional"])
    return {"ok": required_ok, "backends_dir": str(backends_dir), "backends": rows,
            "verification": "filesystem presence only; execution and gameplay are separate facts"}
