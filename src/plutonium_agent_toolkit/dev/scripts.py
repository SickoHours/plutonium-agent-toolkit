"""``gsc compile``, ``gsc check`` and ``gsc decompile`` through gsc-tool.

The input script is copied into the job directory before the compiler runs so
the source tree is never written to. Compiler errors are detected from the log
as well as the exit status because gsc-tool can exit zero after printing errors.

``check`` is the compile with gsc-tool's dry run (``-y``): the parser and
compiler run for the title, nothing is written. It is the syntax gate for a
title whose client executes source (IW5), where gsc-tool's bytecode is never
what the game runs; ``project build`` uses it for such titles.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..core.errors import BACKEND_FAILED, INPUT_INVALID, Failure
from ..core.jobs import Job
from . import titles
from .backends import executable

SYSTEMS = ("pc",)
INSTANCES = ("server", "client")
MODES = {"compile": ("comp", "compiled"), "check": ("comp", None), "decompile": ("decomp", "decompiled")}
ERROR = re.compile(r"(?im)^\s*(?:error\b|\[error\]|fatal\b)")


def add_parser(sub, common):
    p = sub.add_parser("gsc", help="Compile or decompile scripts with gsc-tool")
    actions = p.add_subparsers(dest="action", required=True)
    helps = {"compile": "Compile a script to the title's bytecode (what T6 runs)",
             "check": "Parse and compile a script with gsc-tool's dry run; writes nothing (the syntax gate for IW5 source)",
             "decompile": "Decompile a compiled script"}
    for action in MODES:
        q = actions.add_parser(action, help=helps[action])
        q.add_argument("input", help="Script file (.gsc/.csc) or compiled script")
        q.add_argument("--game", choices=titles.names(), default=titles.DEFAULT_TITLE,
                       help="Title the script targets; selects the gsc-tool game (default t6)")
        q.add_argument("--instance", choices=INSTANCES, default=None, help="server for .gsc, client for .csc; inferred from the suffix")
        q.add_argument("--includes", help="Directory searched for #include files; hashed into the receipt")
        common(q)


def execute(args, job: Job) -> dict:
    src = job.input(args.input)
    instance = args.instance or ("client" if src.suffix.lower() == ".csc" else "server")
    if args.action in ("compile", "check") and src.suffix.lower() not in (".gsc", ".csc"):
        raise Failure(INPUT_INVALID, f"{args.action.capitalize()} expects a .gsc or .csc source file")
    if instance not in titles.instances(args.game):
        raise Failure(INPUT_INVALID, f"Title {args.game} has no {instance} script instance (IW5 has one server VM and no .csc)")
    staged_dir = job.root / "input"
    staged_dir.mkdir()
    staged = staged_dir / src.name
    shutil.copyfile(src, staged)
    mode, out_dir = MODES[args.action]
    argv = [*executable("gsc"), "-m", mode, "-g", titles.gsc_game(args.game), "-s", "pc", "-i", instance]
    if args.action == "check":
        argv.append("-y")
    if args.includes:
        include = job.input_tree(Path(args.includes).expanduser())
        argv += ["-w", str(include)]
    log = job.run([*argv, str(staged)], timeout=args.timeout)
    text = log.read_bytes()[:4 * 1024 * 1024].decode("utf-8", errors="replace")
    if ERROR.search(text):
        raise Failure(BACKEND_FAILED, "gsc-tool reported errors", log=log.name,
                      first_error=next((line.strip() for line in text.splitlines() if ERROR.match(line)), "")[:300])
    if args.action == "check":
        return {"files": [], "instance": instance, "game": args.game, "checked": src.name,
                "verification": "gsc-tool parsed and compiled the source in dry-run mode; nothing written; behaviour in game untested"}
    produced = sorted(p for p in (job.root / out_dir).rglob("*") if p.is_file())
    if not produced:
        raise Failure(BACKEND_FAILED, "gsc-tool produced no output", log=log.name)
    if any(p.stat().st_size == 0 for p in produced):
        raise Failure(BACKEND_FAILED, "gsc-tool produced an empty file", log=log.name)
    return {"files": [p.relative_to(job.root).as_posix() for p in produced], "instance": instance,
            "game": args.game,
            "verification": "compiler exit and log checked; script behavior in game untested"}
