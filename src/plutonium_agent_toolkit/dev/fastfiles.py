"""``ff inspect``, ``ff link`` and ``ff extract`` through OpenAssetTools.

``link`` takes a read-only OAT project directory containing ``zone_source`` and
``raw``, links every zone named on the command line into the job's ``packages``
directory and immediately reads each result back with Unlinker.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..core.errors import BACKEND_FAILED, INPUT_INVALID, INPUT_MISSING, Failure
from ..core.jobs import Job
from ..core.receipts import sha256_file
from .backends import executable

IDENTIFIER = re.compile(r"^[A-Za-z0-9_]{1,64}\Z")
# Diagnostics only: anchored at line start so an asset *named* "fatal error.gsc" in a
# `--list` inventory line (which starts with the asset type) cannot trip the check.
LOAD_FAILURE = re.compile(r"(?im)^(?:\[?(?:error|fatal)\]?\s*[:\-]|failed to load\b|error loading\b|fatal error\b)")


def add_parser(sub, common):
    p = sub.add_parser("ff", help="Fastfile operations with OpenAssetTools")
    actions = p.add_subparsers(dest="action", required=True)
    q = actions.add_parser("inspect", help="List a fastfile's assets")
    q.add_argument("input", help="Fastfile (.ff)")
    q.add_argument("--load", action="append", default=[], help="Dependency fastfile; repeat as needed")
    common(q)
    q = actions.add_parser("extract", help="Extract assets from a fastfile")
    q.add_argument("input", help="Fastfile (.ff)")
    q.add_argument("--load", action="append", default=[])
    q.add_argument("--types", help="Comma-separated OAT asset types, e.g. rawfile,image")
    q.add_argument("--model-format", choices=["GLTF", "GLB", "OBJ", "XMODEL_EXPORT", "XMODEL_BIN"], default="GLTF")
    q.add_argument("--image-format", choices=["DDS", "IWI"], default="DDS")
    common(q)
    q = actions.add_parser("link", help="Link a zone from an OAT project and read it back")
    q.add_argument("project", help="OAT project directory with zone_source/ and raw/")
    q.add_argument("--zone", required=True, help="Zone name (zone_source/<name>.zone)")
    q.add_argument("--load", action="append", default=[], help="Dependency fastfile; repeat as needed")
    q.add_argument("--assets", action="append", default=[], help="Extra asset search directory; repeat as needed")
    common(q)


def check_readback_log(log: Path) -> str:
    """Unlinker can exit zero after reporting a load failure; the log is authoritative."""
    text = log.read_bytes()[:4 * 1024 * 1024].decode("utf-8", errors="replace")
    if LOAD_FAILURE.search(text):
        hint = ("The zones Plutonium ships for IW5 under storage/iw5/zone are zone version 2000; OpenAssetTools reads version 1 only. "
                "Load the game's own zone/english/*.ff instead." if "Could not create factory" in text else "")
        raise Failure(BACKEND_FAILED, "OpenAssetTools reported a loading failure", hint, log=log.name)
    return text


def check_link_log(log: Path) -> str:
    """Linker can print an ERROR line and still exit zero; the log is authoritative here too."""
    text = log.read_bytes()[:4 * 1024 * 1024].decode("utf-8", errors="replace")
    if LOAD_FAILURE.search(text):
        raise Failure(BACKEND_FAILED, "OpenAssetTools Linker reported an error", log=log.name)
    return text


def _link(args, job: Job) -> dict:
    base = Path(args.project).expanduser().resolve()
    if not base.is_dir():
        raise Failure(INPUT_MISSING, f"Project directory is missing: {base}")
    if not IDENTIFIER.match(args.zone):
        raise Failure(INPUT_INVALID, "Zone names use letters, digits and underscore only")
    if not (base / "zone_source" / f"{args.zone}.zone").is_file():
        raise Failure(INPUT_MISSING, f"zone_source/{args.zone}.zone is missing")
    for name in ("zone_source", "raw"):
        if (base / name).is_dir():
            job.input_tree(base / name)
    out = job.root / "packages"
    argv = [*executable("linker"), "--no-color", "--base-folder", str(base), "--output-folder", str(out)]
    for directory in args.assets:
        p = Path(directory).expanduser().resolve()
        if not p.is_dir() or ";" in str(p):
            raise Failure(INPUT_INVALID, "Asset search paths must be existing directories without semicolons")
        job.input_tree(p)
        argv += ["--add-asset-search-path", str(p)]
    for zone in args.load:
        argv += ["-l", str(job.input(zone))]
    check_link_log(job.run([*argv, args.zone], cwd=base, timeout=args.timeout))
    packages = sorted(out.rglob("*.ff"))
    if not packages:
        raise Failure(BACKEND_FAILED, "Linker produced no fastfile")
    verified = []
    for p in packages:
        log = job.run([*executable("unlinker"), "--no-color", "--skip-obj", "--list", str(p)], timeout=args.timeout)
        check_readback_log(log)
        verified.append({"path": p.relative_to(job.root).as_posix(), "sha256": sha256_file(p), "inventory_log": log.name})
    return {"packages": verified, "verification": "linked and read back by OpenAssetTools; gameplay untested"}


def execute(args, job: Job) -> dict:
    if args.action == "link":
        return _link(args, job)
    src = job.input(args.input)
    if src.suffix.lower() != ".ff":
        raise Failure(INPUT_INVALID, "Expected a .ff fastfile")
    argv = [*executable("unlinker"), "--no-color"]
    if args.action == "inspect":
        argv += ["--skip-obj", "--list"]
    else:
        argv += ["--output-folder", str(job.root / "assets"), "--model-format", args.model_format,
                 "--image-format", args.image_format]
        if args.types:
            if not re.fullmatch(r"[a-z0-9_,]{1,512}", args.types):
                raise Failure(INPUT_INVALID, "Asset types are comma-separated lowercase identifiers")
            argv += ["--include-assets", args.types]
    for zone in args.load:
        argv += ["-l", str(job.input(zone))]
    try:
        log = job.run([*argv, str(src)], timeout=args.timeout)
    except Failure as exc:
        log_name = exc.details.get("log")
        if exc.code == BACKEND_FAILED and log_name and "Could not create factory" in (job.root / log_name).read_bytes()[:65536].decode("utf-8", errors="replace"):
            raise Failure(BACKEND_FAILED, "OpenAssetTools could not open this fastfile (no zone loader for its header)",
                          "The zones Plutonium ships for IW5 under storage/iw5/zone are zone version 2000; OpenAssetTools reads version 1 "
                          "only. Load the game's own zone/english/*.ff instead (docs/knowledge/iw5.md).", log=log_name) from exc
        raise
    text = check_readback_log(log)
    if args.action == "extract" and not any(p.is_file() for p in (job.root / "assets").rglob("*")):
        raise Failure(BACKEND_FAILED, "No assets were extracted", log=log.name)
    zone = re.search(r"(?m)^Zone '[^']+' \((\w+)\)", text) or re.search(r'(?m)^Loaded zone "[^"]+" \((\w+)\)', text)
    return {"input": str(src), "inventory_log": log.name, "listing": text[:65536], "listing_truncated": len(text) > 65536,
            "game": zone.group(1) if zone else None,
            "verification": "OpenAssetTools readback; not gameplay acceptance"}
