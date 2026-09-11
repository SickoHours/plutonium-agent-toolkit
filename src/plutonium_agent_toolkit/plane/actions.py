"""The typed actions of the control plane.

Every button on the page is one row of ``ACTIONS``: one registered ``pat`` route, a fixed argv
template and typed parameters the server validates before it starts the child process. Paths
come only from the library roots the user named on the command line or from the jobs directory;
the client never sends argv, a shell string, an absolute path or an output directory. Agent
actions carry the instance, model and reasoning choice the person picked on the page; nothing
here has a default model.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from ..core.discovery import find
from ..core.errors import INPUT_INVALID, INPUT_MISSING, Failure

ID = re.compile(r"^[a-z0-9_]{1,64}\Z")
FOLDER = re.compile(r"^[A-Za-z0-9_.-]{1,100}\Z")
HOST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
OPTION = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}=[^\x00-\x1f\x7f]{1,512}\Z")  # the value range pat agent accepts
REFERENCE = re.compile(r"^(?:[a-z0-9][a-z0-9-]{0,38}/[a-z0-9_]{1,64}|https://github\.com/[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100})@[0-9a-f]{40}\Z")
ENTRY = re.compile(r"^[a-z0-9][a-z0-9-]{0,38}/[a-z0-9_]{1,64}\Z")
BASE = re.compile(r"^[a-z0-9]{1,16}\Z")
MAP = re.compile(r"^[a-z0-9_]{1,64}\Z")
TAG = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}\Z")
CATEGORY = re.compile(r"^[a-z][a-z0-9-]{0,31}\Z")
MAP_KEY = re.compile(r"^[a-z0-9-]{1,64}\Z")
LOAD_ID = re.compile(r"^[a-f0-9]{32}\Z")
SOURCE = re.compile(r"^https://[^\s\x00-\x1f]{1,2048}\Z")
PRINTABLE = re.compile(r"^[^\x00-\x08\x0b\x0c\x0e-\x1f]*\Z")
MAX_PROMPT = 200_000
MAX_TEXT = 512
MAX_LIST = 16
RUNTIME_MODES = ("approval-required", "auto-accept-edits", "auto", "full-access")
INTERACTION_MODES = ("default", "plan")


@dataclass(frozen=True)
class Param:
    name: str
    kind: str                 # path, id, folder, text, prompt, flag, int, enum, reference, entry, options, host_id, ...
    help: str
    required: bool = False
    flag: str | None = None   # argv flag; positional when None
    file: str | None = None   # path parameters: the exact file name the path must end in
    roots: tuple = ("library",)  # path parameters: library roots, the jobs directory, or both
    choices: tuple = ()
    pattern: re.Pattern | None = None
    limit: int = MAX_TEXT
    minimum: int = 0
    maximum: int = 0
    directory: bool = False   # path parameters: a directory (holding `file`) rather than the file itself


@dataclass(frozen=True)
class Action:
    id: str
    route: str
    label: str
    screen: str
    params: tuple = ()
    job: bool = False          # a job route: the server adds --output under the jobs directory
    confirm: bool = False      # the page asks the person to confirm before starting it
    timeout: int = 300         # seconds the server gives the child process
    note: str = ""


COMPOSITION = Param("composition", "path", "A composition.json under a library root, or inside a snapshot that module fetch placed under the jobs directory",
                    required=True, file="composition.json", roots=("library", "jobs"))
PROMPT = Param("prompt", "prompt", "The prompt text; the page offers playbook templates, the person edits and sends", required=True)
THREAD = Param("thread_id", "host_id", "A thread id from agent hosts or a dispatch result", required=True, pattern=HOST_ID)

ACTIONS: tuple[Action, ...] = (
    # ----- reads --------------------------------------------------------------------------
    Action("manifest", "manifest", "Toolkit manifest", "home"),
    Action("doctor", "doctor", "Doctor: configuration and backends", "home"),
    Action("game-mods", "game mods", "Installed mod folders (disk inventory)", "install"),
    Action("game-status", "game status", "Game windows (no engine input)", "install"),
    Action("game-info", "game info", "Fresh map, mod and server state from the engine", "install", confirm=True),
    Action("registry-list", "registry list", "Registries recorded on this machine", "registry"),
    Action("registry-search", "registry search", "Search the recorded registries", "registry", params=(
        Param("words", "words", "Words that must all appear in name, title, category, kind or tags", pattern=PRINTABLE, limit=200),
        Param("category", "token", "Category filter", flag="--category", pattern=CATEGORY),
        Param("kind", "token", "Kind filter", flag="--kind", pattern=CATEGORY),
        Param("tag", "token", "Tag filter", flag="--tag", pattern=TAG),
        Param("base", "token", "Base filter", flag="--base", pattern=BASE),
        Param("map", "token", "Map filter", flag="--map", pattern=MAP),
        Param("entry_kind", "enum", "module or composition", flag="--entry-kind", choices=("module", "composition")))),
    Action("registry-show", "registry show", "Every listing of one entry", "registry", params=(
        Param("name", "entry", "<owner>/<id>", required=True, pattern=ENTRY),)),
    Action("agent-probe", "agent probe", "Probe the local T3 Code server (no token)", "agent"),
    Action("agent-hosts", "agent hosts", "Projects and threads the T3 Code server knows", "agent"),
    Action("agent-models", "agent models", "Provider instances, models and reasoning choices on this machine", "agent"),
    Action("agent-status", "agent status", "One thread's turn state and recent messages", "agent", params=(
        THREAD, Param("messages", "int", "Recent messages to include", flag="--messages", minimum=0, maximum=20))),
    # ----- jobs ----------------------------------------------------------------------------
    Action("module-plan", "module plan", "Plan a composition: order, fit, budget, collisions as decisions", "pack",
           params=(COMPOSITION,), job=True, timeout=600),
    Action("module-build", "module build", "Build a composition into one mod.ff and read it back", "pack",
           params=(COMPOSITION,), job=True, timeout=1800),
    Action("module-declare", "module declare", "Declare a prebuilt mod.ff as a seed (manifest and draft declaration)", "library", params=(
        Param("package", "path", "A mod.ff under a library root", required=True, file="mod.ff"),
        Param("id", "id", "Module id for the draft", flag="--id", pattern=ID),
        Param("title", "text", "Title for the draft", flag="--title", limit=120),
        Param("category", "token", "Category for the draft", flag="--category", pattern=CATEGORY),
        Param("base", "token", "Base token it was tested on", flag="--base", pattern=BASE),
        Param("map", "token", "Map id it was tested on", flag="--map", pattern=MAP)), job=True, timeout=900),
    Action("module-fetch", "module fetch", "Fetch a published module or pack at its exact commit", "registry", params=(
        Param("reference", "reference", "<owner>/<id>@<commit> or https://github.com/<owner>/<repo>@<commit>", required=True, pattern=REFERENCE),
        Param("path", "relpath", "Directory inside the repository holding the declaration", flag="--path")), job=True, timeout=600),
    Action("project-verify", "project verify", "Re-hash a build receipt's outputs (and inputs)", "pack", params=(
        Param("receipt", "path", "A receipt.json under the jobs directory", required=True, file="receipt.json", roots=("jobs",)),
        Param("inputs", "flag", "Also re-hash the recorded inputs", flag="--inputs")), job=True),
    Action("registry-add", "registry add", "Record a registry file (path under a library root, or an https URL)", "registry", params=(
        Param("source", "registry_source", "registry.json under a library root, or an https URL", required=True),)),
    Action("game-install-mod", "game install-mod", "Copy a built mod.ff into storage/t6/mods/<folder>", "install", params=(
        Param("package", "path", "The mod.ff of a build under the jobs directory, or a seed under a library root", required=True,
              file="mod.ff", roots=("jobs", "library")),
        Param("folder", "folder", "Destination folder id (a composition's name)", required=True, pattern=FOLDER),
        Param("replace", "flag", "Move an existing folder aside first", flag="--replace")), confirm=True),
    # ----- live game (Windows; each needs the person's go) ----------------------------------
    Action("game-launch", "game launch", "Start the game through the plutonium:// handler", "install", confirm=True, timeout=600),
    Action("game-select-mod", "game select-mod", "Select an installed mod folder (or base) in the running game", "install", params=(
        Param("folder", "folder", "Folder id from the inventory, or base", required=True, pattern=FOLDER),), confirm=True, timeout=600),
    Action("game-load-map", "game load-map", "Load a catalogued map once in the running game", "install", params=(
        Param("map", "token", "Map key from the catalog (tranzit, town, der-riese, ...)", required=True, pattern=MAP_KEY),), confirm=True, timeout=600),
    Action("game-check-load", "game check-load", "Check a load id against the running process", "install", params=(
        Param("load_id", "token", "The load_id a load returned", required=True, pattern=LOAD_ID),), confirm=True, timeout=120),
    # ----- agent -----------------------------------------------------------------------------
    Action("agent-dispatch", "agent dispatch", "Hand a prompt to a new T3 Code thread with the chosen model", "agent", params=(
        Param("project", "host_id", "Project id from agent hosts", required=True, flag="--project", pattern=HOST_ID),
        Param("title", "text", "Thread title", required=True, flag="--title", limit=200),
        PROMPT,
        Param("instance", "host_id", "Provider instance id from agent models", required=True, flag="--instance", pattern=HOST_ID),
        Param("model", "text", "Model slug from agent models (any printable slug pat agent accepts)", required=True, flag="--model", limit=MAX_TEXT),
        Param("options", "options", "Reasoning choices as id=value rows from agent models", flag="--option"),
        Param("runtime_mode", "enum", "Runtime mode", flag="--runtime-mode", choices=RUNTIME_MODES),
        Param("interaction_mode", "enum", "Interaction mode", flag="--interaction-mode", choices=INTERACTION_MODES),
        Param("branch", "text", "Branch name to record on the thread", flag="--branch", limit=200)), confirm=True, timeout=120),
    Action("agent-send", "agent send", "Send a follow-up turn to a thread", "agent", params=(
        THREAD, PROMPT, Param("queue", "flag", "Allow sending while a turn runs", flag="--queue")), confirm=True, timeout=120),
    Action("agent-interrupt", "agent interrupt", "Interrupt the running turn once", "agent", params=(THREAD,), confirm=True, timeout=120),
)

BY_ID = {a.id: a for a in ACTIONS}


def table(platform_info: dict) -> list[dict]:
    """Every action with its route's effect, status and availability on this host."""
    rows = []
    for action in ACTIONS:
        group, _, name = action.route.partition(" ")
        route = find(group, name) if name else None
        effect = route.effect if route else "inert"
        status = route.status if route else "available"
        requires_windows = bool(route and route.requires_windows)
        available = status in ("available", "implemented") and not (
            requires_windows and not platform_info.get("game_control_supported"))
        rows.append({"id": action.id, "route": action.route, "label": action.label, "screen": action.screen,
                     "effect": effect, "status": status, "requires_windows": requires_windows, "available_here": available,
                     "job": action.job, "confirm": action.confirm, "timeout_seconds": action.timeout,
                     "requires_config": list(route.requires_config) if route else [],
                     "params": [{"name": p.name, "kind": p.kind, "help": p.help, "required": p.required,
                                 "choices": list(p.choices), "file": p.file, "roots": list(p.roots) if p.kind == "path" else []}
                                for p in action.params], "note": action.note})
    return rows


# ----- validation -----------------------------------------------------------------------------

def _is_absolute(text: str) -> bool:
    """Absolute in either path flavour, so a Windows drive or a POSIX root is refused on every host."""
    return PurePosixPath(text).is_absolute() or PureWindowsPath(text).is_absolute() or bool(PureWindowsPath(text).drive)


def _regular_path(root: Path, relative: str, what: str) -> Path:
    if not isinstance(relative, str) or not relative or len(relative) > 4096 or "\\" in relative or relative != relative.strip():
        raise Failure(INPUT_INVALID, f"{what}: a forward-slash path relative to its root")
    parts = PurePosixPath(relative).parts
    if _is_absolute(relative) or not parts or any(p in ("..", ".") for p in parts):
        raise Failure(INPUT_INVALID, f"{what}: the path stays inside its root")
    current = root
    try:
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise Failure(INPUT_INVALID, f"{what}: linked paths are not accepted")
    except OSError as exc:
        raise Failure(INPUT_INVALID, f"{what}: cannot read {relative}: {exc.strerror or exc}") from exc
    return current


def resolve_path(value, param: Param, library_roots: list[Path], jobs_root: Path) -> Path:
    """``{"root": <index into the library roots> | "jobs", "path": "<relative>"}`` to a regular file
    (or directory) under that root, with the file name the parameter requires."""
    what = f"parameter {param.name}"
    if not isinstance(value, dict) or set(value) != {"root", "path"}:
        raise Failure(INPUT_INVALID, f"{what}: give {{\"root\": <library index or \"jobs\">, \"path\": <relative path>}}")
    root_key = value["root"]
    if root_key == "jobs":
        if "jobs" not in param.roots:
            raise Failure(INPUT_INVALID, f"{what}: must come from a library root")
        root = jobs_root
    elif isinstance(root_key, int) and not isinstance(root_key, bool) and 0 <= root_key < len(library_roots):
        if "library" not in param.roots:
            raise Failure(INPUT_INVALID, f"{what}: must come from the jobs directory")
        root = library_roots[root_key]
    else:
        raise Failure(INPUT_INVALID, f"{what}: unknown root {root_key!r}")
    full = _regular_path(root, value["path"], what)
    try:
        if param.directory:
            if not full.is_dir() or (param.file and not (full / param.file).is_file()):
                raise Failure(INPUT_MISSING, f"{what}: no directory holding {param.file} at {value['path']}")
            return full
        if param.file and full.name != param.file:
            raise Failure(INPUT_INVALID, f"{what}: the path ends in {param.file}")
        if not full.is_file():
            raise Failure(INPUT_MISSING, f"{what}: no file at {value['path']} under its root")
    except OSError as exc:
        raise Failure(INPUT_INVALID, f"{what}: cannot read {value['path']}: {exc.strerror or exc}") from exc
    return full


def _text(value, param: Param) -> str:
    if not isinstance(value, str) or not PRINTABLE.match(value) or len(value) > param.limit or value != value.strip() or not value:
        raise Failure(INPUT_INVALID, f"parameter {param.name}: text of 1 to {param.limit} printable characters")
    return value


def argv_for(action: Action, args: dict, library_roots: list[Path], jobs_root: Path, prompt_dir: Path) -> list[str]:
    """The child argv for one action. Every parameter is validated by kind; unknown keys refuse."""
    if not isinstance(args, dict):
        raise Failure(INPUT_INVALID, "args is an object of parameter values")
    known = {p.name for p in action.params}
    unknown = sorted(set(args) - known)
    if unknown:
        raise Failure(INPUT_INVALID, f"{action.id}: unknown parameters {unknown}")
    argv = action.route.split(" ")
    prompts: list[tuple[int, str]] = []
    for param in action.params:
        value = args.get(param.name)
        if value is None or value == "" or value == [] or value is False:
            if param.required:
                raise Failure(INPUT_INVALID, f"{action.id}: parameter {param.name} is required")
            continue
        if param.kind == "path":
            text = str(resolve_path(value, param, library_roots, jobs_root))
        elif param.kind == "flag":
            if value is not True:
                raise Failure(INPUT_INVALID, f"parameter {param.name}: true or absent")
            argv.append(param.flag)
            continue
        elif param.kind == "int":
            if not isinstance(value, int) or isinstance(value, bool) or not param.minimum <= value <= param.maximum:
                raise Failure(INPUT_INVALID, f"parameter {param.name}: an integer from {param.minimum} to {param.maximum}")
            text = str(value)
        elif param.kind == "enum":
            if value not in param.choices:
                raise Failure(INPUT_INVALID, f"parameter {param.name}: one of {list(param.choices)}")
            text = value
        elif param.kind == "prompt":
            if not isinstance(value, str) or not value.strip() or len(value) > MAX_PROMPT or len(value.encode("utf-8")) > MAX_PROMPT \
                    or not PRINTABLE.match(value.replace("\n", "").replace("\t", "")):
                raise Failure(INPUT_INVALID, f"parameter {param.name}: prompt text of 1 to {MAX_PROMPT} characters and bytes")
            prompts.append((len(argv) + 1, value))
            argv += ["--prompt", "<prompt file>"]
            continue
        elif param.kind == "options":
            if not isinstance(value, list) or len(value) > MAX_LIST or not all(isinstance(v, str) and OPTION.match(v) for v in value):
                raise Failure(INPUT_INVALID, f"parameter {param.name}: a list of id=value rows")
            for row in value:
                argv += [param.flag, row]
            continue
        elif param.kind == "words":
            if not isinstance(value, str) or not PRINTABLE.match(value) or len(value) > param.limit:
                raise Failure(INPUT_INVALID, f"parameter {param.name}: up to {param.limit} printable characters")
            argv += value.split()
            continue
        elif param.kind == "registry_source":
            if isinstance(value, dict):
                text = str(resolve_path(value, Param("source", "path", "", file="registry.json"), library_roots, jobs_root))
            elif isinstance(value, str) and SOURCE.match(value):
                text = value
            else:
                raise Failure(INPUT_INVALID, "parameter source: a registry.json under a library root, or an https URL")
        elif param.kind == "relpath":
            text = _text(value, param)
            parts = Path(text).parts
            if "\\" in text or Path(text).is_absolute() or any(p == ".." for p in parts):
                raise Failure(INPUT_INVALID, "parameter path: a relative directory inside the repository")
        elif param.kind == "text":
            text = _text(value, param)
        else:  # id, folder, token, host_id, reference, entry: one regex each
            if not isinstance(value, str) or param.pattern is None or not param.pattern.match(value):
                raise Failure(INPUT_INVALID, f"parameter {param.name}: does not match the accepted form")
            text = value
        if param.flag:
            argv += [param.flag, text]
        else:
            argv.append(text)
    # Prompt files are written last, so a refused parameter leaves nothing on disk.
    for index, value in prompts:
        prompt_dir.mkdir(parents=True, exist_ok=True)
        path = prompt_dir / f"prompt-{uuid.uuid4().hex}.txt"
        path.write_text(value, encoding="utf-8")
        argv[index] = "@" + str(path)
    return argv
