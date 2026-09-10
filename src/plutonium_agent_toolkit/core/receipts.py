"""Receipts: the durable record of one job.

A receipt records exactly what ran (argv), what it read (input hashes), what it
produced (output hashes), how it ended (status, exit code) and where its logs
are. Failed and cancelled jobs keep their receipts. Receipts are written once
into a new output directory that the job created; the toolkit never overwrites.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

from .envelope import now
from .errors import INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING, OUTPUT_EXISTS, OUTPUT_LIMIT, Failure

MAX_HASH_BYTES = 8 * 1024**3
MAX_FILES = 20000
CHUNK = 1024 * 1024


def sha256_file(path: Path, limit: int = MAX_HASH_BYTES) -> str:
    p = Path(path)
    if p.is_symlink() or not p.is_file():
        raise Failure(INPUT_MISSING, f"Cannot hash a missing or linked file: {p}")
    h = hashlib.sha256()
    total = 0
    with p.open("rb") as stream:
        while block := stream.read(CHUNK):
            total += len(block)
            if total > limit:
                raise Failure(INPUT_LIMIT, f"File exceeds {limit} bytes: {p}")
            h.update(block)
    return h.hexdigest()


def inventory(root: Path) -> dict[str, str]:
    """Relative POSIX path -> sha256 for every regular file under root."""
    root = Path(root)
    rows: dict[str, str] = {}
    count = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs.sort()
        for name in sorted(files):
            p = Path(directory) / name
            if p.is_symlink():
                raise Failure(INPUT_MISSING, f"Linked files are not inventoried: {p}")
            count += 1
            if count > MAX_FILES:
                raise Failure(OUTPUT_LIMIT, f"More than {MAX_FILES} files under {root}")
            rows[p.relative_to(root).as_posix()] = sha256_file(p)
    return rows


def new_output_dir(path: Path) -> Path:
    """Create the job's output directory. It must not already exist."""
    p = Path(path).absolute()
    if p.exists():
        raise Failure(OUTPUT_EXISTS, f"Output directory already exists: {p}",
                      "Choose a new directory for every job; the toolkit never overwrites results.")
    p.mkdir(parents=True)
    return p


def write(output_dir: Path, *, command: str, argv: list[str], status: str, exit_code: int,
          inputs: dict | None = None, outputs: dict | None = None, logs: list[str] | None = None,
          **extra) -> Path:
    receipt = {
        "schema_version": 1,
        "job_id": uuid.uuid4().hex,
        "command": command,
        "argv": argv,
        "status": status,
        "exit_code": exit_code,
        "started": extra.pop("started", None),
        "finished": now(),
        "inputs": inputs or {},
        "outputs": outputs or {},
        "logs": logs or [],
    }
    receipt.update(extra)
    path = Path(output_dir) / "receipt.json"
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def verify_outputs(receipt_path: Path) -> dict:
    """Re-hash every recorded output and report what changed."""
    try:
        receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise Failure(INPUT_INVALID, f"Receipt is not readable JSON: {receipt_path}") from exc
    if not isinstance(receipt, dict) or not isinstance(receipt.get("outputs"), dict):
        raise Failure(INPUT_INVALID, f"Receipt lacks an outputs map: {receipt_path}")
    base = Path(receipt_path).parent
    changed, missing = [], []
    for rel, digest in receipt.get("outputs", {}).items():
        p = base / rel
        if not p.is_file():
            missing.append(rel)
        elif sha256_file(p) != digest:
            changed.append(rel)
    return {"verified": not changed and not missing, "changed": changed, "missing": missing,
            "count": len(receipt.get("outputs", {}))}
