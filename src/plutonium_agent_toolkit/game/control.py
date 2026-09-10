"""Game control routes: status, info, mods, select-mod, load-map, reload-mod,
check-load, launch, quit.

Every live route runs inside one bounded worker under the toolkit mutex. State
transitions are verified against fresh engine replies and recorded in a load
receipt bound to the game's process identity. Nothing is ever replayed after
an uncertain result; the caller inspects fresh state instead.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

from ..core import config
from ..core.errors import (CONFIG_MISSING, DELIVERY_UNCERTAIN, INPUT_INVALID, INPUT_MISSING, LOAD_UNVERIFIED,
                           NOT_IMPLEMENTED, Failure)
from .engine import SETTINGS, Engine, parse_value

MAPS_PATH = Path(__file__).with_name("maps.json")
# Parent deadline per action, derived from each transition's bounded internal waits
# (state queries of 8/30/40 s, prompt waits of 3 s, registered-verb checks of 8 s)
# plus margin. A parent that kills a worker mid-transaction can only report
# delivery_uncertain, so the deadline must exceed the worst legitimate path.
WORKER_DEADLINES = {
    "status": 20, "info": 30, "check-load": 60, "quit": 45,
    "launch": 90 + 15 + 25,                    # observe + settle + margin
    "fast-restart": 120, "map-restart": 120, "disconnect": 120, "load-map": 150,
    "select-mod": 200, "reload-mod": 200,      # before + disconnect(30) + unload(30) + load(40) + sends + verb checks
}
LOAD_RECEIPT_MAX_AGE = 600
MAX_LOG_TAIL = 131072
MOD_ID = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
LOAD_ID = re.compile(r"[a-f0-9]{32}\Z")
ERROR_LINE = re.compile(r"^(?:\*+\s*)?(?:error\s*:|script (?:runtime |compile )?error\b|server script compile error\b"
                        r"|fatal error\b|unhandled exception\b|a critical exception\b|exception code\s*:"
                        r"|\d+ script error\(s\)|too early to loadmod!\s*$|LUI_ERROR\s*:|Havok Script Panic\b)", re.I)
PLUTONIUM_URI = "plutonium://play/t6zm"
WORKER_TOKEN_ENV = "PAT_GAME_WORKER_TOKEN"


# ----- catalog and inventory ------------------------------------------------------------

def maps() -> dict:
    value = json.loads(MAPS_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not 1 <= len(value) <= 64:
        raise Failure(INPUT_INVALID, "Invalid map catalog")
    for key, row in value.items():
        if not re.fullmatch(r"[a-z0-9-]{1,64}", key) or not isinstance(row, dict):
            raise Failure(INPUT_INVALID, f"Invalid map recipe key {key!r}")
        if not isinstance(row.get("label"), str) or type(row.get("dlc5")) is not bool or any(
                not isinstance(row.get(k), str) or not re.fullmatch(r"[a-z0-9_]{1,100}", row[k])
                for k in ("map", "location", "mode", "group")):
            raise Failure(INPUT_INVALID, f"Invalid map recipe fields for {key!r}")
    return value


def storage() -> Path:
    return config.require("plutonium_storage_t6")


def _regular_child(root: Path, relative: str) -> Path:
    root = root.resolve()
    path = root / relative
    if not path.resolve().is_relative_to(root):
        raise Failure(INPUT_INVALID, "Path escapes the storage directory")
    current = path
    while current != root:
        if current.is_symlink() or (os.name == "nt" and current.exists() and current.lstat().st_file_attributes & 0x400):
            raise Failure(INPUT_INVALID, "Linked mod paths are not supported")
        current = current.parent
    return path


def mod_info(root: Path, folder: str) -> dict:
    if not isinstance(folder, str) or not MOD_ID.match(folder) or folder in (".", ".."):
        raise Failure(INPUT_INVALID, "Invalid mod folder ID; run: pat game mods --json")
    mods = root / "mods"
    path = _regular_child(mods, folder)
    if not path.is_dir():
        raise Failure(INPUT_MISSING, f"Mod folder is not installed: {folder}")
    available = any(_regular_child(mods, f"{folder}/{name}").is_file() for name in ("mod.ff", "mod_load.ff"))
    if folder.lower().startswith("mp_"):
        available = False
    return {"id": folder, "path": f"mods/{folder}", "available": available,
            "reason": "" if available else "No packaged mod.ff, or a multiplayer folder"}


def inventory(root: Path) -> list[dict]:
    mods = root / "mods"
    if not mods.is_dir():
        return []
    rows = []
    with os.scandir(mods) as entries:
        for index, entry in enumerate(entries):
            if index >= 256:
                raise Failure(INPUT_INVALID, "Mod inventory exceeds 256 entries")
            if not entry.is_dir(follow_symlinks=False):
                continue
            try:
                rows.append(mod_info(root, entry.name))
            except Failure:
                continue
    return sorted(rows, key=lambda row: row["id"].lower())


# ----- receipts -------------------------------------------------------------------------

def state_dir() -> Path:
    p = config.home() / "game"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _save(path: Path, value: dict) -> None:
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _log_paths(root: Path) -> dict[str, Path]:
    return {"zombies": root / "main" / "console_zm.log"}


def _log_cursor(path: Path):
    try:
        with path.open("rb") as stream:
            info = os.fstat(stream.fileno())
            stream.seek(max(0, info.st_size - 128))
            anchor = stream.read(128)
        return {"size": info.st_size, "device": info.st_dev, "inode": info.st_ino, "anchor": hashlib.sha256(anchor).hexdigest()}
    except OSError:
        return None


def inspect_logs(root: Path, cursors: dict) -> dict:
    """Counts only. Raw console lines can carry credentials and never leave this function."""
    result = {}
    for name, path in _log_paths(root).items():
        cursor = cursors.get(name)
        try:
            if not isinstance(cursor, dict):
                raise ValueError("log was unavailable when the load started")
            with path.open("rb") as stream:
                info = os.fstat(stream.fileno())
                if (info.st_dev, info.st_ino) != (cursor["device"], cursor["inode"]) or info.st_size < cursor["size"]:
                    raise ValueError("log rotated or truncated")
                stream.seek(max(0, cursor["size"] - 128))
                if hashlib.sha256(stream.read(min(128, cursor["size"]))).hexdigest() != cursor["anchor"]:
                    raise ValueError("log prefix changed")
                # Only output written after the load started counts; the anchor bytes are pre-load.
                stream.seek(cursor["size"])
                raw = stream.read(MAX_LOG_TAIL + 1)
            if len(raw) > MAX_LOG_TAIL:
                raise ValueError("new log output exceeds 128 KiB")
            lines = [re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]|\^[0-9]", "", line).strip() for line in raw.decode(errors="replace").splitlines()]
            result[name] = {"checked": True, "bytes": len(raw), "error_lines": sum(bool(ERROR_LINE.match(line)) for line in lines)}
        except (OSError, ValueError, KeyError, TypeError) as error:
            result[name] = {"checked": False, "reason": str(error)[:200]}
    return result


# ----- transitions ----------------------------------------------------------------------

def _match(actual: dict, expected: dict) -> None:
    if any(actual.get(key) != value for key, value in expected.items()):
        raise Failure(DELIVERY_UNCERTAIN, "Expected engine state did not verify; do not replay. Run game info and inspect the game")


def change(engine: Engine, action: str, argument: str | None, root: Path, process: dict) -> dict:
    """One gameplay transition. Returns a result with a load_id and check argv."""
    before = engine.state()
    if action == "info":
        return {"state": before, "process": process, "engine_queried": True}
    if action == "quit":
        engine.registered("quit")
        engine.console.send("quit")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if engine.console.k.WaitForSingleObject(engine.console.process, 0) == 0:
                return {"process": process, "stopped": True, "method": "engine quit"}
            time.sleep(0.1)
        raise Failure(DELIVERY_UNCERTAIN, "quit was submitted but the original process has not exited; no force kill, no replay")

    mod_action = action in ("select-mod", "reload-mod")
    entry = None
    if mod_action:
        if action == "select-mod":
            if argument is None:
                raise Failure(INPUT_INVALID, "select-mod needs a mod folder ID or 'base'")
            target = "" if argument == "base" else mod_info(root, argument)["path"]
            if argument != "base" and not mod_info(root, argument)["available"]:
                raise Failure(INPUT_INVALID, mod_info(root, argument)["reason"])
        else:
            current = before["fs_game"][5:] if before["fs_game"].startswith("mods/") else ""
            if not current:
                raise Failure(INPUT_INVALID, "No mod is selected; nothing to reload")
            row = mod_info(root, current)
            if not row["available"]:
                raise Failure(INPUT_INVALID, f"Selected mod {current!r} is not reloadable: {row['reason']}")
            target = row["path"]
        if target == before["fs_game"] and action == "select-mod":
            return {"no_op": True, "state": before, "process": process}
        engine.registered("loadmod")
        if before["sv_running"] == "1":
            engine.registered("disconnect")
        expected = {"fs_game": target, "sv_running": "0"}
    else:
        if action == "load-map":
            entry = maps().get(argument or "")
            if entry is None:
                raise Failure(INPUT_INVALID, f"Unknown map recipe {argument!r}; run: pat describe game load-map --json")
            command = "map " + entry["map"]
            if entry["dlc5"]:
                if not re.fullmatch(r"mods/[A-Za-z0-9_.-]{1,100}", before["fs_game"]):
                    raise Failure(INPUT_INVALID, "Select an installed DLC5 mod first; this map's zone is not in the base game")
                row = mod_info(root, before["fs_game"][5:])
                zone = _regular_child(root / "mods", f"{row['id']}/zone/{entry['map']}.ff")
                if not row["available"] or not zone.is_file():
                    raise Failure(INPUT_MISSING, f"Selected mod lacks zone/{entry['map']}.ff")
        else:
            command = {"fast-restart": "fast_restart", "map-restart": "map_restart", "disconnect": "disconnect"}.get(action)
            if not command:
                raise Failure(INPUT_INVALID, f"Unsupported game action {action!r}")
            if command != "disconnect" and before["sv_running"] != "1":
                raise Failure(INPUT_INVALID, "Restart requires a running local match")
        engine.registered(command.split()[0])
        expected = {"fs_game": before["fs_game"], "sv_running": "0" if command == "disconnect" else "1"}
        if command != "disconnect":
            expected["mapname"] = entry["map"] if entry else before["mapname"]
        if entry:
            expected["g_gametype"] = entry["mode"]

    receipt = {"schema_version": 1, "id": uuid.uuid4().hex, "created": time.time(), "action": action, "argument": argument,
               "process": process, "before": before, "expected": expected, "status": "pending",
               "logs": {name: _log_cursor(path) for name, path in _log_paths(root).items()}}
    receipt_path = state_dir() / "last-load.json"
    _save(receipt_path, receipt)
    try:
        if mod_action:
            if before["sv_running"] == "1":
                engine.console.send("disconnect")
                _match(engine.state(30), {"sv_running": "0", "fs_game": before["fs_game"]})
            if before["fs_game"]:
                engine.console.send('loadmod ""')
                _match(engine.state(30), {"sv_running": "0", "fs_game": ""})
            if target:
                engine.console.send("loadmod " + target)
        else:
            if entry:
                settings = dict(zip(SETTINGS, (entry["map"], entry["location"], entry["mode"], entry["mode"], entry["group"])))
                lines = engine.query(tuple(f'set {key} "{value}"' for key, value in settings.items()) + SETTINGS)
                if {key: parse_value(lines, key, pending=key == "g_gametype") for key in settings} != settings:
                    raise Failure(DELIVERY_UNCERTAIN, "Map settings did not verify; the map command was not sent")
            engine.console.send(command)
        after = engine.state(40)
        _match(after, expected)
        receipt.update(status="engine-state-verified", after=after)
        return {"state": after, "process": process, "load_id": receipt["id"], "ready_for_handoff": False,
                "load_check": {"argv": ["pat", "game", "check-load", receipt["id"]]},
                "next": "Run the load check, then inspect an actual game image. A verified state is not a playable spawn."}
    except Failure as error:
        receipt.update(status="unverified", error=error.to_dict())
        raise Failure(error.code if error.code == DELIVERY_UNCERTAIN else LOAD_UNVERIFIED, error.message,
                      "Inspect fresh game info and the actual game; never replay this transition automatically",
                      load_id=receipt["id"], ready_for_handoff=False) from error
    finally:
        _save(receipt_path, receipt)


def check_load(load_id: str, root: Path, console_factory) -> dict:
    if not LOAD_ID.match(load_id or ""):
        raise Failure(INPUT_INVALID, "Use the exact load ID from the original response")
    path = state_dir() / "last-load.json"
    if not path.is_file():
        raise Failure(INPUT_MISSING, "No load receipt is saved")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("id") != load_id or not 0 <= time.time() - receipt.get("created", 0) <= LOAD_RECEIPT_MAX_AGE:
        raise Failure(INPUT_MISSING, "Load receipt missing, superseded or older than ten minutes")
    with console_factory(expected=receipt["process"]) as console:
        state = Engine(console).state()
    logs = inspect_logs(root, receipt.get("logs", {}))
    state_ok = all(state.get(k) == v for k, v in receipt["expected"].items())
    complete = bool(logs) and all(row.get("checked") for row in logs.values())
    errors = any(row.get("error_lines", 0) for row in logs.values())
    result = {"load_id": load_id, "verified": state_ok and complete and not errors and receipt.get("status") == "engine-state-verified",
              "state": state, "state_matches": state_ok, "logs": logs, "original_status": receipt.get("status"),
              "ready_for_handoff": False,
              "visual_checkpoint": "Inspect the actual game image for the expected menu or playable spawn and for delayed errors"}
    _save(state_dir() / "last-load-check.json", result)
    return result


# ----- launch ---------------------------------------------------------------------------

LAUNCH_SETTLE_SECONDS = 15


def launch(native, root: Path, observe_seconds: int = 90, settle_seconds: int = LAUNCH_SETTLE_SECONDS) -> dict:
    """Start T6 Zombies through the registered plutonium:// handler and observe.

    Reports three separate facts: whether the request was issued, whether a game
    window appeared (with its process identity), and every foreground-window
    change during the interval. Focus preservation is a qualification result read
    from that log, never assumed. Nothing is retried on a launcher prompt.
    """
    if native.windows():
        return {"already_running": True, "launched": False, "windows": native.windows()}
    launcher = config.load().get("plutonium_launcher")
    if not launcher or not Path(launcher).is_file() or Path(launcher).name.lower() != "plutonium.exe":
        raise Failure(CONFIG_MISSING, "Configure the official plutonium.exe path first", "Run: pat configure --plutonium-launcher <path>")
    focus_log = []
    last = native.foreground()
    focus_log.append({"t": 0.0, **last, "event": "before-launch"})
    started = time.monotonic()
    # os.startfile on a URI asks the shell to dispatch through the registered handler.
    # No token, no bootstrapper arguments, no saved credentials.
    try:
        os.startfile(PLUTONIUM_URI)  # noqa: S606 - fixed allowlisted URI
    except OSError as error:
        raise Failure(CONFIG_MISSING,
                      f"Windows could not dispatch {PLUTONIUM_URI}; no launch request was issued: {error.strerror or error}",
                      "The plutonium:// protocol handler is not registered for this user. Open the official launcher once, then retry.",
                      uri=PLUTONIUM_URI, launch_requested=False) from error
    game = None
    appeared = None
    detected_at = None
    # Observe until the interval ends, or until the game has been visible for three
    # seconds and a further settle window has passed. Startup focus theft commonly
    # happens after the window appears, so detection alone does not end observation.
    while time.monotonic() - started < observe_seconds:
        now = native.foreground()
        if (now["pid"], now["title"]) != (last["pid"], last["title"]):
            focus_log.append({"t": round(time.monotonic() - started, 2), **now, "event": "foreground-changed"})
            last = now
        if game is None:
            found = native.windows()
            if found:
                if appeared is None:
                    appeared = time.monotonic()
                if time.monotonic() - appeared >= 3:
                    pid, title = next(iter(found.items()))
                    game = {"pid": pid, "title": title}
                    detected_at = time.monotonic()
                    focus_log.append({"t": round(detected_at - started, 2), **now, "event": "game-detected"})
            else:
                appeared = None
        elif time.monotonic() - detected_at >= settle_seconds:
            break
        time.sleep(0.25)
    observed = round(time.monotonic() - started, 2)
    focus_preserved = all(e.get("event") != "foreground-changed" for e in focus_log)
    truncated = len(focus_log) > 200
    result = {"launch_requested": True, "uri": PLUTONIUM_URI, "game_window": game, "game_detected": game is not None,
              "observe_seconds": observe_seconds, "settle_seconds": settle_seconds, "focus_observed_seconds": observed,
              "focus_scope": f"foreground changes during {observed}s from launch request"
                             + (f", including {settle_seconds}s after the game window appeared" if game else ", game window never appeared"),
              "focus_events": focus_log[:200], "focus_events_truncated": truncated,
              "focus_event_count": len(focus_log), "focus_preserved": focus_preserved,
              "ready_for_handoff": False,
              "note": "Window detection is not a playable menu. Run game status/info and inspect the screen. Launcher login or update prompts are reported here, never answered."}
    _save(state_dir() / "last-launch.json", result)
    return result


# ----- worker boundary ------------------------------------------------------------------

LIVE_ACTIONS = {"status", "info", "launch", "select-mod", "load-map", "reload-mod", "check-load", "quit",
                "fast-restart", "map-restart", "disconnect"}
ARGUMENT_ACTIONS = {"select-mod": "mod folder ID or 'base'", "load-map": "map ID", "check-load": "load ID"}


def validate_argument(action: str, argument: str | None) -> None:
    """Required-argument actions need one; every other action must have none."""
    if action in ARGUMENT_ACTIONS:
        if not argument:
            raise Failure(INPUT_INVALID, f"game {action} needs a {ARGUMENT_ACTIONS[action]}")
    elif argument:
        raise Failure(INPUT_INVALID, f"game {action} takes no argument; got {argument!r}. Nothing was sent")


def execute_worker(action: str, argument: str | None) -> dict:
    """Runs inside the bounded child under the toolkit mutex."""
    from . import native

    validate_argument(action, argument)
    # quit and status/launch never touch storage; do not fail them on a missing storage path.
    root = storage() if action not in ("status", "launch", "quit") else None
    with native.lock():
        if action == "status":
            return {"windows": [{"pid": pid, "title": title} for pid, title in native.windows().items()],
                    "foreground": native.foreground(), "engine_queried": False}
        if action == "launch":
            return launch(native, root)
        if action == "check-load":
            return check_load(argument or "", root, native.Console)
        with native.Console() as console:
            return change(Engine(console), action, argument, root, console.identity)


def dispatch(action: str, argument: str | None) -> dict:
    """Parent side: one worker, hard deadline, structured uncertainty."""
    if action not in LIVE_ACTIONS:
        raise Failure(NOT_IMPLEMENTED, f"game {action} is not a live route")
    validate_argument(action, argument)
    request_id = uuid.uuid4().hex
    argv = [sys.executable, "-m", "plutonium_agent_toolkit.game.worker", action, argument or ""]
    env = dict(os.environ, **{WORKER_TOKEN_ENV: request_id})
    deadline = WORKER_DEADLINES[action]
    try:
        completed = subprocess.run(argv, capture_output=True, timeout=deadline, env=env,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if len(completed.stdout) > 65536:
            raise Failure(DELIVERY_UNCERTAIN, "Worker response too large; outcome uncertain, do not replay")
        result = json.loads(completed.stdout.decode("utf-8"))
        if not isinstance(result, dict):
            raise Failure(DELIVERY_UNCERTAIN, "Invalid worker response")
        if completed.returncode and result.get("ok"):
            raise Failure(DELIVERY_UNCERTAIN, "Worker exit status disagrees with its response; outcome uncertain")
    except subprocess.TimeoutExpired as exc:
        raise Failure(DELIVERY_UNCERTAIN, f"{deadline}-second worker deadline for game {action} exceeded; only the CLI worker stopped. Do not replay") from exc
    except (ValueError, OSError) as exc:
        raise Failure(DELIVERY_UNCERTAIN, str(exc)[:500]) from exc
    result["request_id"] = request_id
    try:
        _save(state_dir() / "last-result.json", result)
    except OSError:
        result["receipt_warning"] = "Latest result could not be saved; retain this invocation's JSON"
    return result
