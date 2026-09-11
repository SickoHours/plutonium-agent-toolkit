"""Argument parsing and dispatch for ``pat agent``. Every action returns one result dict."""
from __future__ import annotations

from pathlib import Path

from ..core.envelope import success
from ..core.errors import INVALID_ARGUMENTS, Failure
from . import t3

ACTIONS = ("probe", "hosts", "models", "dispatch", "status", "send", "interrupt")


def add_parser(sub) -> None:
    p = sub.add_parser("agent", help="Hand work to a running T3 Code server as a thread (orchestration protocol 1)")
    actions = p.add_subparsers(dest="action", required=True)

    def origin(q):
        q.add_argument("--origin", help="Server origin, for example http://127.0.0.1:3773; default: the origin in T3CODE_HOME/userdata/server-runtime.json")
        q.add_argument("--json", action="store_true")

    q = actions.add_parser("probe", help="Public descriptor and orchestration protocol; needs no token")
    origin(q)
    q = actions.add_parser("hosts", help="Projects and threads the server knows")
    origin(q)
    q = actions.add_parser("models", help="Provider instances, models and reasoning options from this machine's T3 Code settings")
    q.add_argument("--home", help="T3 Code data directory; default: T3CODE_HOME or ~/.t3")
    q.add_argument("--json", action="store_true")
    q = actions.add_parser("dispatch", help="Create a thread and start its first turn")
    origin(q)
    q.add_argument("--project", required=True, help="Project id from pat agent hosts")
    q.add_argument("--title", required=True, help="Thread title")
    q.add_argument("--prompt", required=True, help="Prompt text, or @path to read it from a file")
    q.add_argument("--instance", required=True, help="Provider instance id from pat agent models")
    q.add_argument("--model", required=True, help="Model slug from pat agent models")
    q.add_argument("--option", action="append", default=[], metavar="ID=VALUE",
                   help="Provider option such as effort=high or reasoningEffort=high; repeatable; ids from pat agent models")
    q.add_argument("--runtime-mode", default="full-access", choices=t3.RUNTIME_MODES)
    q.add_argument("--interaction-mode", default="default", choices=t3.INTERACTION_MODES)
    q.add_argument("--worktree", help="Absolute path of an existing worktree the thread should work in")
    q.add_argument("--branch", help="Branch name to record on the thread")
    q = actions.add_parser("status", help="One thread's turn and session state with recent messages")
    origin(q)
    q.add_argument("thread_id")
    q.add_argument("--messages", type=int, default=4, help="Recent messages to include (0-20)")
    q = actions.add_parser("send", help="Send a follow-up turn to a thread")
    origin(q)
    q.add_argument("thread_id")
    q.add_argument("--prompt", required=True, help="Prompt text, or @path to read it from a file")
    q.add_argument("--queue", action="store_true", help="Allow sending while a turn is running; the server adopts it afterwards")
    q = actions.add_parser("interrupt", help="Interrupt the running turn once")
    origin(q)
    q.add_argument("thread_id")


def run(args, command: str) -> dict:
    if args.action == "models":
        home = Path(args.home).expanduser() if args.home else None
        if home is not None and not home.is_absolute():
            raise Failure(INVALID_ARGUMENTS, "--home must be an absolute path")
        return success(command, t3.models(home))
    origin, state = t3.origin_for(args.origin)
    if args.action == "probe":
        result = t3.probe(origin)
        if state:
            result["runtime_state"] = state
        return success(command, result)
    t3.require_token_safe_origin(origin, state)
    bearer = t3.token()
    if args.action == "hosts":
        return success(command, t3.hosts(origin, bearer))
    if args.action == "status":
        if not 0 <= args.messages <= 20:
            raise Failure(INVALID_ARGUMENTS, "--messages must be 0-20")
        return success(command, t3.status(origin, bearer, args.thread_id, message_limit=args.messages))
    if args.action == "dispatch":
        selection = t3.model_selection(args.instance, args.model, args.option)
        prompt = t3.read_prompt(args.prompt)
        return success(command, t3.dispatch(origin, bearer, project_id=args.project, title=args.title, prompt=prompt,
                                            selection=selection, runtime_mode=args.runtime_mode,
                                            interaction_mode=args.interaction_mode, worktree_path=args.worktree,
                                            branch=args.branch))
    if args.action == "send":
        return success(command, t3.send(origin, bearer, t3.validate_id(args.thread_id, "thread id"),
                                        t3.read_prompt(args.prompt), queue=args.queue))
    if args.action == "interrupt":
        return success(command, t3.interrupt(origin, bearer, t3.validate_id(args.thread_id, "thread id")))
    raise Failure(INVALID_ARGUMENTS, f"Unknown agent action {args.action!r}")
