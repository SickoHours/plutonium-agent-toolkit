"""``pat`` command line. Every invocation prints exactly one JSON document.

    pat version
    pat manifest
    pat describe <group> <action>
    pat doctor
    pat configure --plutonium-storage-t6 <abs path> [--plutonium-launcher <abs path>] ...
    pat dev backends
    pat dev setup [--plan] [--only ID ...]
    pat dev install-skills [--plan] [--only HARNESS ...] [--home DIR] [--source CHECKOUT]
    pat workspace init <directory> [--name ID]   a modding workspace outside the checkout
    pat dev builtin [--plan] [--only owner/id ...]     the built-in modules and packs, fetched onto this machine
    pat gsc compile|decompile <script> --output <new dir>
    pat ff inspect|extract <file.ff> --output <new dir>
    pat ff link <project dir> --zone <name> --output <new dir>
    pat project init|plan|build|verify ... --output <new dir>
    pat module plan|build <composition.json> --output <new dir>
    pat module declare <mod.ff> --output <new dir>
    pat module fetch <owner/id@commit | https://github.com/o/r@commit> --output <new dir>
    pat registry add <file|url> | list | search [words] [--category ...] | show <owner/id>
    pat registry baseline <directory> [--repository <url>] [--commit <40 hex>] --output <new dir>
    pat knowledge builtin <name> [--vm server|client] | signature --log <file> | limits [--map <zm_map>]   shipped T6 facts
    pat agent probe|hosts|models|dispatch|status|send|interrupt ...   T3 Code (protocol 1) as an agent host
    pat plane actions | serve --library <dir> --jobs <dir>   a local control plane over these routes
    pat mcp tools | serve --library <dir> --jobs <dir>       the same typed actions as MCP tools on stdin and stdout
    pat <group> <action> ...          planned routes answer not_implemented

Exit statuses: 0 ok, 1 failure, 2 usage, 130 cancelled. See core/errors.py.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .core import config, platform
from .core.discovery import find, manifest, routes
from .core.envelope import emit, failure, success
from .core.errors import INVALID_ARGUMENTS, NOT_IMPLEMENTED, OPERATION_FAILED, Failure

# Importing the route modules registers their contracts.
from .agent import routes as _agent_routes  # noqa: F401
from .dev import routes as _dev_routes  # noqa: F401
from .game import routes as _game_routes  # noqa: F401
from .mcp import routes as _mcp_routes  # noqa: F401
from .plane import routes as _plane_routes  # noqa: F401
from .testing import routes as _testing_routes  # noqa: F401


class Parser(argparse.ArgumentParser):
    def error(self, message):  # noqa: D401 - argparse hook
        raise Failure(INVALID_ARGUMENTS, message, "Run: pat manifest --json")


def build_parser() -> Parser:
    p = Parser(prog="pat", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="group", required=True)

    for name in ("version", "manifest", "doctor"):
        q = sub.add_parser(name)
        q.add_argument("--json", action="store_true", help="Output is always JSON; flag accepted for agents")

    q = sub.add_parser("describe")
    q.add_argument("route_group")
    q.add_argument("route_action")
    q.add_argument("--json", action="store_true")

    q = sub.add_parser("configure", help="Save absolute paths under the toolkit home")
    for key, help_text in config.KNOWN_KEYS.items():
        q.add_argument("--" + key.replace("_", "-"), dest=key, help=help_text)
    q.add_argument("--json", action="store_true")

    q = sub.add_parser("dev")
    dev = q.add_subparsers(dest="action", required=True)
    b = dev.add_parser("backends")
    b.add_argument("--json", action="store_true")
    s = dev.add_parser("setup")
    s.add_argument("--plan", action="store_true", help="List pinned downloads without downloading")
    s.add_argument("--only", nargs="+", metavar="ID", help="Install only these backend IDs")
    s.add_argument("--json", action="store_true")
    k = dev.add_parser("install-skills", help="Copy skills/ into the harnesses' skills directories under your home, with a receipt")
    k.add_argument("--plan", action="store_true", help="Report what would be written, updated, left or refused; write nothing")
    k.add_argument("--only", nargs="+", metavar="HARNESS", help="Only these harness ids (claude, codex, gemini, opencode, cursor, hermes, agents)")
    k.add_argument("--home", help="Home directory to detect harnesses under (default: the current user's)")
    k.add_argument("--source", help="Toolkit checkout holding skills/ (default: the checkout this installation runs from)")
    k.add_argument("--json", action="store_true")
    ws = sub.add_parser("workspace", help="A modding workspace for the person and their agent, outside the toolkit checkout")
    wsa = ws.add_subparsers(dest="action", required=True)
    q = wsa.add_parser("init", help="Create the workspace directory with AGENTS.md, layout, ignore file and record")
    q.add_argument("directory", help="New or empty directory to create the workspace in")
    q.add_argument("--name", help="Workspace name (default: the directory name)")
    q.add_argument("--json", action="store_true")
    b = dev.add_parser("builtin", help="Fetch the built-in modules and packs the shipped registry lists into the toolkit home; rerun verifies")
    b.add_argument("--plan", action="store_true", help="Report each built-in's state without touching the network")
    b.add_argument("--only", nargs="+", metavar="OWNER/ID", help="Only these built-in entries")
    b.add_argument("--json", action="store_true")

    # Implemented job groups get real parsers; every job takes --output and --timeout.
    def common(q):
        q.add_argument("--output", required=True, help="New directory for artifacts and receipt.json; never overwritten")
        q.add_argument("--timeout", type=_timeout, default=300, help="Per-backend deadline in seconds (1-1800)")
        q.add_argument("--json", action="store_true")

    from .dev import compositions, fastfiles, media, models, projects, scripts, weapons

    scripts.add_parser(sub, common)
    fastfiles.add_parser(sub, common)
    projects.add_parser(sub, common)
    compositions.add_parser(sub, common)
    media.add_parsers(sub, common)
    models.add_parser(sub, common)
    weapons.add_parser(sub, common)

    r = sub.add_parser("registry", help="Registries of published modules and packs (files anyone can host)")
    ra = r.add_subparsers(dest="action", required=True)
    q = ra.add_parser("add"); q.add_argument("source", help="Path or https URL to a registry.json"); q.add_argument("--json", action="store_true")
    q = ra.add_parser("list"); q.add_argument("--json", action="store_true")
    q = ra.add_parser("search"); q.add_argument("words", nargs="*"); q.add_argument("--category"); q.add_argument("--kind"); q.add_argument("--tag")
    q.add_argument("--base"); q.add_argument("--map"); q.add_argument("--entry-kind", choices=["module", "composition"])
    q.add_argument("--origin", choices=["builtin", "added"], help="Only the registry that ships with the toolkit, or only registries you added")
    q.add_argument("--json", action="store_true")
    q = ra.add_parser("show"); q.add_argument("name", help="<owner>/<id>"); q.add_argument("--json", action="store_true")
    from .dev import baseline

    baseline.add_parser(ra, common)  # registry baseline is a job: --output and --timeout like every other job

    k = sub.add_parser("knowledge", help="Generated T6 facts shipped with the toolkit: builtins per script VM, engine limits with per-map occupancy, crash signatures")
    ka = k.add_subparsers(dest="action", required=True)
    q = ka.add_parser("builtin", help="Does this call exist on a script VM, with which argument counts")
    q.add_argument("name"); q.add_argument("--vm", choices=["server", "client"], help="Only this script VM"); q.add_argument("--json", action="store_true")
    q.add_argument("--output", help="Optional new directory: also write the answer and a receipt there (provenance for a benchmark)")
    q = ka.add_parser("signature", help="Match a console log slice against the crash signatures")
    q.add_argument("--log", help="Console log file or slice to read"); q.add_argument("--text", help="One log line or a short slice")
    q.add_argument("--json", action="store_true")
    q.add_argument("--output", help="Optional new directory: also write the answer and a receipt there (provenance for a benchmark)")
    q = ka.add_parser("limits", help="Observed engine limits, or one map's loaded zones counted against them")
    q.add_argument("--map", help="Zombies map id, for example zm_transit"); q.add_argument("--json", action="store_true")
    q.add_argument("--output", help="Optional new directory: also write the answer and a receipt there (provenance for a benchmark)")
    from .agent import cli as _agent_cli

    _agent_cli.add_parser(sub)
    from .plane import cli as _plane_cli

    _plane_cli.add_parser(sub)
    from .mcp import cli as _mcp_cli

    _mcp_cli.add_parser(sub)

    g = sub.add_parser("game", help="Plutonium T6 Zombies control through the external console")
    g.add_argument("action", choices=sorted(r.action for r in routes() if r.group == "game"))
    g.add_argument("argument", nargs="?", help="Mod folder ID, map ID, load ID or (install-mod) mod.ff path")
    g.add_argument("argument2", nargs="?", help="install-mod only: destination folder ID")
    g.add_argument("--replace", action="store_true", help="install-mod only: move an existing folder aside first")
    g.add_argument("--json", action="store_true")

    # Planned/deferred groups accept any action so they can answer with a structured refusal.
    for group in sorted({r.group for r in routes()} - {"dev", "gsc", "ff", "project", "module", "registry", "workspace", "knowledge", "game", "agent", "plane", "mcp", "audio", "image", "lua", "model", "weapon"}):
        g = sub.add_parser(group)
        g.add_argument("action")
        g.add_argument("rest", nargs=argparse.REMAINDER)
    return p


def _timeout(value):
    n = int(value)
    if not 1 <= n <= 1800:
        raise argparse.ArgumentTypeError("timeout must be 1-1800 seconds")
    return n


JOB_GROUPS = {"gsc": "scripts", "ff": "fastfiles", "project": "projects", "module": "compositions", "audio": "media",
              "image": "media", "lua": "media", "model": "models", "weapon": "weapons"}
# Single actions that are jobs inside a group whose other actions are not (registry add|list|search|show
# take no --output; registry baseline writes a report and a receipt into a new directory).
JOB_ACTIONS = {("registry", "baseline"): "baseline"}


def is_job(group: str, action: str) -> bool:
    return group in JOB_GROUPS or (group, action) in JOB_ACTIONS


def run_job(args, argv: list[str]) -> dict:
    """Gate, create the job directory, dispatch to the owning module, write the receipt."""
    from importlib import import_module

    from .core.jobs import Job

    route = find(args.group, args.action)
    if route.requires_windows and not os.environ.get("PAT_DEV_UNGATED"):
        platform.require_windows(f"{args.group} {args.action}")
    owner = JOB_ACTIONS.get((args.group, args.action), JOB_GROUPS.get(args.group))
    module = import_module(f".dev.{owner}", __package__)
    job = Job(Path(args.output), f"{args.group} {args.action}", argv, timeout=max(args.timeout, 60) * 4)
    try:
        result = module.execute(args, job)
        return success(f"{args.group} {args.action}", job.finish(result))
    except Failure as exc:
        job.fail(exc)
        row = failure(f"{args.group} {args.action}", exc)
        row["receipt"] = str(job.receipt_path)
        return row
    except KeyboardInterrupt:
        exc = Failure("cancelled", "Job cancelled; owned backend processes stopped")
        job.fail(exc)
        row = failure(f"{args.group} {args.action}", exc)
        row["receipt"] = str(job.receipt_path)
        return row
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as unexpected:
        # Never let a traceback replace the JSON contract; the receipt must not stay "running".
        exc = Failure(OPERATION_FAILED, f"{type(unexpected).__name__}: {str(unexpected)[:400]}",
                      "This is a toolkit defect. Keep the receipt and report it with the command you ran.")
        job.fail(exc)
        row = failure(f"{args.group} {args.action}", exc)
        row["receipt"] = str(job.receipt_path)
        return row


def run(argv: list[str]) -> dict:
    args = build_parser().parse_args(argv)
    argv = ["pat", *argv]
    group = args.group
    command = group if group in ("version", "manifest", "doctor", "describe", "configure") else f"{group} {args.action}"

    if group == "version":
        return success(command, {"version": __version__, "platform": platform.describe()})

    if group == "manifest":
        return success(command, manifest(platform.describe()))

    if group == "describe":
        route = find(args.route_group, args.route_action)
        return success(command, route.to_dict())

    if group == "doctor":
        from .dev import backends

        info = platform.describe()
        cfg_state = {}
        try:
            cfg = config.load()
            shown = {k: ("<set>" if k in config.SECRET_KEYS else v) for k, v in cfg.items()}
            cfg_state = {"home": str(config.home()), "config": shown, "ok": True}
        except Failure as exc:
            cfg_state = {"home": str(config.home()), "ok": False, "error": exc.to_dict()}
        result = {"platform": info, "configuration": cfg_state}
        try:
            result["backends"] = backends.doctor()
        except Failure as exc:
            result["backends"] = {"ok": False, "error": exc.to_dict()}
        result["ok"] = cfg_state.get("ok", False) and result["backends"].get("ok", False)
        from .dev import skills

        result["skills"] = skills.status()
        from .dev import builtin

        result["builtin"] = builtin.status()
        result["game_control"] = {
            "supported_here": bool(info["game_control_supported"]),
            "note": "Game control and capture use the Win32 console and need a native Windows host. "
                    "Development file tools run on this platform.",
        }
        result["verification"] = "Presence and configuration only. Execution, game control and capture are separate facts."
        return success(command, result)

    if group == "configure":
        values = {key: getattr(args, key) for key in config.KNOWN_KEYS if getattr(args, key)}
        if not values:
            raise Failure(INVALID_ARGUMENTS, "Provide at least one configuration option", "Run: pat configure --help")
        path = config.save(values)
        return success(command, {"path": str(path), "saved": sorted(values)})

    if group == "dev" and args.action == "backends":
        from .dev import backends

        return success(command, backends.doctor() | {"pins": backends.pins()["programs"]})

    if group == "dev" and args.action == "setup":
        from .dev import backends

        return success(command, backends.setup(only=args.only, plan=args.plan))

    if group == "dev" and args.action == "install-skills":
        from .dev import skills

        return success(command, skills.install(plan=args.plan, only=args.only, home=args.home, source=args.source))
    if group == "dev" and args.action == "builtin":
        from .dev import builtin

        return success(command, builtin.install(plan=args.plan, only=args.only))
    if group == "workspace" and args.action == "init":
        from .dev import workspace

        return success(command, workspace.init(args.directory, args.name))

    if is_job(group, getattr(args, "action", "")):
        return run_job(args, argv)

    if group == "game":
        return run_game(args)

    if group == "registry":
        from .dev import registry

        if args.action == "add":
            return success(command, registry.add(args.source))
        if args.action == "list":
            return success(command, registry.listing())
        if args.action == "search":
            return success(command, registry.search(" ".join(args.words), category=args.category, kind=args.kind, tag=args.tag,
                                                        base=args.base, map_id=args.map, entry_kind=args.entry_kind, origin=args.origin))
        return success(command, registry.show(args.name))
    if group == "knowledge":
        from .dev import knowledge

        if getattr(args, "output", None):
            if args.action == "signature":
                # The log is snapshotted into the job before it is read, so the receipt names the classified bytes.
                return success(command, knowledge.record(Path(args.output), command, argv, None,
                                                        Path(args.log) if args.log else None, args.text))
            answer = knowledge.builtin(args.name, args.vm) if args.action == "builtin" else knowledge.limits(args.map)
            return success(command, knowledge.record(Path(args.output), command, argv, answer))
        if args.action == "builtin":
            return success(command, knowledge.builtin(args.name, args.vm))
        if args.action == "signature":
            return success(command, knowledge.signature(Path(args.log) if args.log else None, args.text))
        return success(command, knowledge.limits(args.map))
    if group == "agent":
        from .agent import cli as agent_cli

        return agent_cli.run(args, command)
    if group == "plane":
        from .plane import cli as plane_cli

        return plane_cli.run(args, command)

    if group == "mcp":
        from .mcp import cli as mcp_cli

        return mcp_cli.run(args, command)

    route = find(group, args.action)
    hint = ("Deferred by product decision; not part of this release. See docs/SUPPORT.md." if route.status == "deferred"
            else f"Owner: {route.owner}. See docs/SUPPORT.md for the qualification status of every route.")
    raise Failure(NOT_IMPLEMENTED, f"Route {route.id} is {route.status} in {__version__}; nothing was executed.",
                  hint, route=route.to_dict())


def run_game(args) -> dict:
    from .game import control

    command = f"game {args.action}"
    route = find("game", args.action)
    if args.action != "install-mod":
        if args.argument2 is not None:
            raise Failure(INVALID_ARGUMENTS, f"game {args.action} takes at most one argument; got extra {args.argument2!r}. Nothing was sent")
        if args.replace:
            raise Failure(INVALID_ARGUMENTS, "--replace applies only to game install-mod. Nothing was sent")
    if args.action == "mods":
        if args.argument:
            raise Failure(INVALID_ARGUMENTS, "game mods takes no argument")
        root = control.storage()
        return success(command, {"storage": str(root), "mods": control.inventory(root), "game_queried": False})
    if args.action == "install-mod":
        from .game import install

        if not args.argument or not args.argument2:
            raise Failure(INVALID_ARGUMENTS, "Usage: pat game install-mod <path to mod.ff> <folder-id> [--replace]")
        return success(command, install.install_mod(Path(args.argument), args.argument2, replace=args.replace))
    if route.requires_windows and not os.environ.get("PAT_GAME_UNGATED"):
        platform.require_windows(command)
    control.validate_argument(args.action, args.argument)
    for key in route.requires_config:
        config.require(key)
    result = control.dispatch(args.action, args.argument)
    if not result.get("ok", True):
        row = failure(command, Failure(result.get("error_code", "operation_failed"), result.get("message", ""),
                                       result.get("hint", ""), **{k: v for k, v in result.items()
                                                                 if k not in ("ok", "error_code", "message", "hint")}))
        return row
    result.pop("ok", None)
    return success(command, result)


def entry(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    label = " ".join(argv[:2]) if argv else "pat"
    try:
        row = run(argv)
    except Failure as exc:
        row = failure(label, exc)
    except KeyboardInterrupt:
        row = failure(label, Failure("cancelled", "Interrupted"))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as unexpected:
        row = failure(label, Failure(OPERATION_FAILED, f"{type(unexpected).__name__}: {str(unexpected)[:400]}",
                                     "This is a toolkit defect. Report it with the command you ran."))
    return emit(row)


if __name__ == "__main__":
    raise SystemExit(entry())
