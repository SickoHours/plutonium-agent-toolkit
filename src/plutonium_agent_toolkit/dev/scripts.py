"""``gsc compile`` and ``gsc decompile`` through gsc-tool.

The input script is copied into the job directory before the compiler runs so
the source tree is never written to. Compiler errors are detected from the log
as well as the exit status because gsc-tool can exit zero after printing errors.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..core.errors import BACKEND_FAILED, INPUT_INVALID, Failure
from ..core.jobs import Job
from .backends import executable

GAMES = ("t6",)
SYSTEMS = ("pc",)
INSTANCES = ("server", "client")
MODES = {"compile": ("comp", "compiled"), "decompile": ("decomp", "decompiled")}
ERROR = re.compile(r"(?im)^\s*(?:error\b|\[error\]|fatal\b)")


def add_parser(sub, common):
    p = sub.add_parser("gsc", help="Compile or decompile T6 scripts with gsc-tool")
    actions = p.add_subparsers(dest="action", required=True)
    for action in MODES:
        q = actions.add_parser(action)
        q.add_argument("input", help="Script file (.gsc/.csc) or compiled script")
        q.add_argument("--instance", choices=INSTANCES, default=None, help="server for .gsc, client for .csc; inferred from the suffix")
        q.add_argument("--includes", help="Directory searched for #include files; hashed into the receipt")
        common(q)


def execute(args, job: Job) -> dict:
    src = job.input(args.input)
    instance = args.instance or ("client" if src.suffix.lower() == ".csc" else "server")
    if args.action == "compile" and src.suffix.lower() not in (".gsc", ".csc"):
        raise Failure(INPUT_INVALID, "Compile expects a .gsc or .csc source file")
    staged_dir = job.root / "input"
    staged_dir.mkdir()
    staged = staged_dir / src.name
    shutil.copyfile(src, staged)
    mode, out_dir = MODES[args.action]
    argv = [*executable("gsc"), "-m", mode, "-g", "t6", "-s", "pc", "-i", instance]
    if args.includes:
        include = job.input_tree(Path(args.includes).expanduser())
        argv += ["-w", str(include)]
    log = job.run([*argv, str(staged)], timeout=args.timeout)
    text = log.read_bytes()[:4 * 1024 * 1024].decode("utf-8", errors="replace")
    if ERROR.search(text):
        raise Failure(BACKEND_FAILED, "gsc-tool reported errors", log=log.name,
                      first_error=next((line.strip() for line in text.splitlines() if ERROR.match(line)), "")[:300])
    produced = sorted(p for p in (job.root / out_dir).rglob("*") if p.is_file())
    if not produced:
        raise Failure(BACKEND_FAILED, "gsc-tool produced no output", log=log.name)
    if any(p.stat().st_size == 0 for p in produced):
        raise Failure(BACKEND_FAILED, "gsc-tool produced an empty file", log=log.name)
    return {"files": [p.relative_to(job.root).as_posix() for p in produced], "instance": instance,
            "verification": "compiler exit and log checked; script behavior in game untested"}
