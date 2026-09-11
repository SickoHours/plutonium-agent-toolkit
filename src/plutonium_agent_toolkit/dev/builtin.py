"""``dev builtin``: the modules and packs that ship with the toolkit, fetched onto this machine.

The toolkit's own registry (``dev/builtin.json``) lists its built-in modules and packs at the exact
commit the release pins. ``dev builtin`` downloads each listed repository snapshot once per
repository and commit, keeps the entry directories (and, for a pack, the member directories and
loads its recipe names inside the same snapshot), and lays them out under
``<toolkit home>/modules/builtin/<owner>/<repository>/<commit>/<path>`` so the relative paths a
composition uses keep resolving. A receipt per entry records the commit, the archive hash and every
file's hash; a rerun re-hashes the tree and reports ``verified``, refuses a tree with a changed,
missing or added file with ``artifact_changed`` and never overwrites it. ``--plan`` reports the state and touches no network.

Built-in, fetched and installed are three different places: this shelf under the toolkit home,
the ``module fetch`` job directories a person chose, and the profiles under Plutonium's ``mods``.
A built-in is planned and built like any other module (``pat module plan <its composition.json>``);
nothing here installs anything into the game.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path

from .. import __version__
from ..core import config
from ..core.envelope import now
from ..core.errors import ARTIFACT_CHANGED, BUSY, INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING, OUTPUT_EXISTS, Failure
from ..core.receipts import inventory, sha256_file
from . import backends, registry

MAX_ENTRY_FILES = 4096
MAX_NESTING = 4


def shelf_dir() -> Path:
    return config.home() / "modules" / "builtin"


def _receipts_dir() -> Path:
    return shelf_dir() / "receipts"


def _repo_name(repository: str) -> str:
    return registry.OWNER_REPO.match(repository).group(2)


def snapshot_dir(entry: dict) -> Path:
    """Where one repository snapshot lives: every entry at that commit shares it."""
    owner = entry["name"].split("/", 1)[0]
    return shelf_dir() / owner / _repo_name(entry["repository"]) / entry["listed"]["commit"]


def entry_dir(entry: dict) -> Path:
    path = entry["path"]
    return snapshot_dir(entry) if path == "." else snapshot_dir(entry) / path


def receipt_path(entry: dict) -> Path:
    """One receipt per entry and pinned commit. A release that moves a pin writes a new receipt
    beside the old one, so the previous snapshot stays accounted for and the new pin starts absent."""
    owner, mid = entry["name"].split("/", 1)
    return _receipts_dir() / f"{owner}--{mid}--{entry['listed']['commit'][:12]}.json"


def entries(only: list[str] | None = None) -> list[dict]:
    rows = registry.builtin_registry()["entries"]
    if only:
        known = {e["name"] for e in rows}
        unknown = sorted(set(only) - known)
        if unknown:
            raise Failure(INPUT_INVALID, f"Not built-in entries: {unknown}", f"Built-in entries: {sorted(known)}")
        rows = [e for e in rows if e["name"] in only]
    return rows


# ----- what a pack needs from its snapshot ---------------------------------------------------------

def _inside(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def needed_paths(snapshot: Path, path: str, depth: int = 0) -> list[str]:
    """The entry directory plus, for a composition, every member directory and load file its recipe
    names inside the same snapshot (nested packs followed to a bound). Relative to the snapshot."""
    base = snapshot if path == "." else snapshot / path
    if not base.is_dir():
        raise Failure(INPUT_MISSING, f"The snapshot has no directory {path!r}")
    if not _inside(base, snapshot):
        raise Failure(INPUT_INVALID, f"Built-in entry path escapes its snapshot: {path}")
    found = [base.relative_to(snapshot).as_posix() if base != snapshot else "."]
    recipe = base / "composition.json"
    if not recipe.is_file():
        return found
    if depth >= MAX_NESTING:
        raise Failure(INPUT_INVALID, f"Built-in pack nests deeper than {MAX_NESTING}: {path}")
    try:
        data = json.loads(recipe.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise Failure(INPUT_INVALID, f"Built-in pack recipe is not readable JSON: {path}/composition.json") from exc
    members = data.get("modules", []) if isinstance(data, dict) else []
    loads = data.get("loads", []) if isinstance(data, dict) else []
    if not isinstance(members, list) or not isinstance(loads, list):
        raise Failure(INPUT_INVALID, f"Built-in pack {path}: modules and loads must be lists")
    for member in members:
        rel = member.get("path") if isinstance(member, dict) else member
        if not isinstance(rel, str) or not rel or "\\" in rel or Path(rel).is_absolute():
            raise Failure(INPUT_INVALID, f"Built-in pack {path} names a member that is not a relative path: {rel!r}")
        target = (base / rel)
        if not _inside(target, snapshot) or not target.is_dir():
            raise Failure(INPUT_MISSING, f"Built-in pack {path} names a member outside its snapshot or missing: {rel}")
        rel_snapshot = target.resolve().relative_to(snapshot.resolve()).as_posix()
        for item in needed_paths(snapshot, rel_snapshot, depth + 1):
            if item not in found:
                found.append(item)
    for load in loads:
        if not isinstance(load, str) or not load or "\\" in load or Path(load).is_absolute():
            raise Failure(INPUT_INVALID, f"Built-in pack {path} names a load that is not a relative path: {load!r}")
        target = base / load
        if not _inside(target, snapshot) or not target.is_file():
            raise Failure(INPUT_MISSING, f"Built-in pack {path} names a load outside its snapshot or missing: {load}")
        rel_snapshot = target.resolve().relative_to(snapshot.resolve()).as_posix()
        if rel_snapshot not in found:
            found.append(rel_snapshot)
    return found


# ----- receipts and verification ------------------------------------------------------------------

def _read_receipt(entry: dict) -> dict | None:
    path = receipt_path(entry)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise Failure(INPUT_INVALID, f"Built-in receipt is not valid JSON: {path}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict) or not isinstance(data.get("paths"), list):
        raise Failure(INPUT_INVALID, f"Built-in receipt is malformed: {path}")
    if data.get("commit") != entry["listed"]["commit"] or data.get("name") != entry["name"]:
        # A receipt for another pin or another entry is not this entry's; this pin starts absent.
        return None
    return data


def verify(entry: dict) -> dict:
    """Re-hash what the receipt recorded. ``state``: verified, changed, absent, unrecorded."""
    receipt = _read_receipt(entry)
    directory = entry_dir(entry)
    if receipt is None:
        return {"state": "unrecorded" if directory.exists() else "absent", "changed": [], "missing": []}
    snapshot = snapshot_dir(entry)
    changed, missing, added = [], [], []
    for rel, digest in receipt["files"].items():
        p = snapshot / rel
        if p.is_symlink() or not p.is_file():
            missing.append(rel)
        elif sha256_file(p) != digest:
            changed.append(rel)
    # The recorded directories must hold exactly the recorded files: a file added under a fetched
    # built-in is a changed tree too, not something a rerun quietly keeps.
    for rel in receipt.get("paths", []):
        p = snapshot if rel == "." else snapshot / rel
        if p.is_symlink():
            # A recorded path replaced by a link would make planning read outside the shelf.
            added.append(f"{rel}: is a link")
            continue
        if not p.is_dir():
            continue
        # So would a link anywhere below it: the recorded files would still hash through it.
        links = _links_under(p)
        if links:
            added.extend(f"{rel}/{sub}: is a link" if rel != "." else f"{sub}: is a link" for sub in links)
            continue
        try:
            present = inventory(p)
        except Failure as exc:
            added.append(f"{rel}: {exc.message}")
            continue
        for sub in present:
            key = sub if rel == "." else (Path(rel) / sub).as_posix()
            if key not in receipt["files"]:
                added.append(key)
    state = "verified" if not changed and not missing and not added else "changed"
    return {"state": state, "changed": changed, "missing": missing, "added": added, "receipt": receipt}


def _links_under(root: Path) -> list[str]:
    """Every link (file or directory) below root, relative to it; the walk never follows one."""
    found = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs) + sorted(files):
            p = Path(directory) / name
            if p.is_symlink():
                found.append(p.relative_to(root).as_posix())
    return found


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


# ----- install ------------------------------------------------------------------------------------

def _download(entry: dict, scratch: Path) -> tuple[Path, str, int]:
    url = registry.snapshot_url(entry["repository"], entry["listed"]["commit"])
    raw = registry.fetch_bytes(url, registry.MAX_SNAPSHOT)
    archive = scratch / f"{entry['listed']['commit']}.tar.gz"
    archive.write_bytes(raw)
    extracted = scratch / "snapshot"
    backends.safe_extract(archive, extracted, strip_root=True)
    count = sum(1 for p in extracted.rglob("*") if p.is_file())
    if count > registry.MAX_SNAPSHOT_FILES:
        raise Failure(INPUT_LIMIT, f"The snapshot holds more than {registry.MAX_SNAPSHOT_FILES} files")
    return extracted, hashlib.sha256(raw).hexdigest(), len(raw)


def _place(entry: dict, extracted: Path, archive_sha: str, archive_bytes: int) -> dict:
    snapshot = snapshot_dir(entry)
    rels = needed_paths(extracted, entry["path"])
    files: dict[str, str] = {}
    placed = []
    for rel in rels:
        src = extracted if rel == "." else extracted / rel
        dst = snapshot if rel == "." else snapshot / rel
        if src.is_dir():
            expected = inventory(src)
            if len(files) + len(expected) > MAX_ENTRY_FILES:
                raise Failure(INPUT_LIMIT, f"Built-in {entry['name']} exceeds {MAX_ENTRY_FILES} files")
            if dst.exists():
                # Shared with an entry placed earlier from the same snapshot: it must still equal the
                # snapshot byte for byte, otherwise it is somebody's changed tree and is preserved.
                if inventory(dst) != expected:
                    raise Failure(ARTIFACT_CHANGED, f"{rel} is already on the shelf and differs from the snapshot; preserving it",
                                  "Move it aside if you want the pinned copy; built-ins are never overwritten.", path=str(dst))
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(src, dst, symlinks=False)
                placed.append(rel)
                if inventory(dst) != expected:
                    raise Failure(ARTIFACT_CHANGED, f"{rel} does not match the snapshot after the copy; inspect the storage volume")
            for sub, digest in expected.items():
                files[(Path(rel) / sub).as_posix() if rel != "." else sub] = digest
        else:
            digest = sha256_file(src)
            if dst.exists():
                if dst.is_symlink() or not dst.is_file() or sha256_file(dst) != digest:
                    raise Failure(ARTIFACT_CHANGED, f"{rel} is already on the shelf and differs from the snapshot; preserving it", path=str(dst))
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
                placed.append(rel)
            files[rel] = digest
    receipt = {"schema_version": 1, "name": entry["name"], "kind": entry["kind"], "repository": entry["repository"],
               "commit": entry["listed"]["commit"], "path": entry["path"], "module_dir": str(entry_dir(entry)),
               "snapshot_dir": str(snapshot), "archive_sha256": archive_sha, "archive_bytes": archive_bytes,
               "paths": rels, "placed": placed, "files": files, "toolkit_version": __version__, "installed_at": now()}
    _receipts_dir().mkdir(parents=True, exist_ok=True)
    _write_json(receipt_path(entry), receipt)
    return receipt


def install(plan: bool = False, only: list[str] | None = None) -> dict:
    rows = entries(only)
    shelf = shelf_dir()
    if plan:
        results = []
        for e in rows:
            check = verify(e)
            results.append({"name": e["name"], "kind": e["kind"], "commit": e["listed"]["commit"], "module_dir": str(entry_dir(e)),
                            "state": check["state"], "changed": check["changed"], "missing": check["missing"], "added": check.get("added", []),
                            "action": {"verified": "verify", "absent": "install", "changed": "refuse", "unrecorded": "refuse"}[check["state"]]})
        return {"plan": True, "destination": str(shelf), "registry": registry.BUILTIN_NAME, "results": results,
                "downloads": sorted({(e["repository"], e["listed"]["commit"]) for e in rows if verify(e)["state"] == "absent"}),
                "network_touched": False, "game_touched": False}
    shelf.mkdir(parents=True, exist_ok=True)
    lock = shelf / "builtin.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise Failure(BUSY, "Another dev builtin is running or an interrupted one left builtin.lock; inspect before removing it") from exc
    scratch = shelf / f".download-{uuid.uuid4().hex}"
    results, downloads, snapshots = [], [], {}
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        for e in rows:
            check = verify(e)
            if check["state"] == "verified":
                results.append({"name": e["name"], "kind": e["kind"], "commit": e["listed"]["commit"], "module_dir": str(entry_dir(e)),
                                "action": "verified", "files": len(check["receipt"]["files"])})
                continue
            if check["state"] == "changed":
                raise Failure(ARTIFACT_CHANGED, f"Built-in {e['name']} differs from its receipt; preserving it",
                              "Move the changed or added files aside if you want the pinned copy back; built-ins are never overwritten.",
                              changed=check["changed"], missing=check["missing"], added=check.get("added", []), module_dir=str(entry_dir(e)))
            if check["state"] == "unrecorded":
                raise Failure(OUTPUT_EXISTS, f"{entry_dir(e)} exists without a built-in receipt; preserving it",
                              "Move it aside if you want dev builtin to fetch the pinned copy there.")
            key = (e["repository"], e["listed"]["commit"])
            if key not in snapshots:
                where = scratch / hashlib.sha256("@".join(key).encode()).hexdigest()[:12]
                where.mkdir(parents=True)
                extracted, sha, size = _download(e, where)
                snapshots[key] = (extracted, sha, size)
                downloads.append({"repository": key[0], "commit": key[1], "archive_sha256": sha, "archive_bytes": size})
            extracted, sha, size = snapshots[key]
            receipt = _place(e, extracted, sha, size)
            results.append({"name": e["name"], "kind": e["kind"], "commit": e["listed"]["commit"], "module_dir": receipt["module_dir"],
                            "action": "installed", "files": len(receipt["files"]), "placed": receipt["placed"]})
            # A pack lays out its members; a member that is itself a built-in entry from the same
            # snapshot gets its own receipt now, so a later run verifies it instead of finding a stranger.
            covered = set(receipt["paths"])
            for other in registry.builtin_registry()["entries"]:
                if other["name"] == e["name"] or (other["repository"], other["listed"]["commit"]) != key or other["path"] not in covered:
                    continue
                if _read_receipt(other) is not None or any(r["name"] == other["name"] for r in results):
                    continue
                adopted = _place(other, extracted, sha, size)
                results.append({"name": other["name"], "kind": other["kind"], "commit": other["listed"]["commit"], "module_dir": adopted["module_dir"],
                                "action": "recorded", "files": len(adopted["files"]), "placed": adopted["placed"],
                                "note": f"laid out by {e['name']}; its own receipt written from the same snapshot"})
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        lock.unlink(missing_ok=True)
    return {"destination": str(shelf), "registry": registry.BUILTIN_NAME, "results": results, "downloads": downloads,
            "receipts": str(_receipts_dir()), "game_touched": False,
            "next": ["pat module plan <module_dir>/composition.json --output <new dir> --json   (a built-in pack)",
                     "pat registry search --origin builtin --json   (what is built in, with builtin_dir when fetched)"],
            "verification": "exact-commit snapshots over HTTPS, hashed, extracted with the archive safety checks, every kept file "
                            "hashed into a receipt; nothing built, nothing installed into the game"}


def status() -> dict:
    """For doctor and registry search: receipt-backed presence per built-in, without re-hashing."""
    try:
        rows = entries()
    except Failure as exc:
        return {"destination": str(shelf_dir()), "note": exc.message, "entries": []}
    out = []
    for e in rows:
        receipt = None
        try:
            receipt = _read_receipt(e)
        except Failure:
            pass
        present = receipt is not None and entry_dir(e).is_dir()
        out.append({"name": e["name"], "kind": e["kind"], "present": present, "module_dir": str(entry_dir(e)) if present else None})
    return {"destination": str(shelf_dir()), "entries": out, "present": sum(1 for r in out if r["present"]), "total": len(out),
            "fetch": None if all(r["present"] for r in out) else "pat dev builtin --json"}


def module_dir_if_present(entry: dict) -> str | None:
    try:
        receipt = _read_receipt(entry)
    except Failure:
        return None
    return str(entry_dir(entry)) if receipt is not None and entry_dir(entry).is_dir() else None
