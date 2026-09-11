"""T3 Code (orchestration protocol 1) as an agent host.

The nightly T3 Code server serves an authenticated HTTP API beside its WebSocket. This module
drives the three endpoints the toolkit needs and nothing else:

    GET  /.well-known/t3/environment          public descriptor (no token)
    GET  /api/orchestration/shell             projects and thread shells      scope orchestration:read
    GET  /api/orchestration/threads/<id>      one thread with messages        scope orchestration:read
    POST /api/orchestration/dispatch          one client command              scope orchestration:operate

Commands are the server's own ``ClientOrchestrationCommand`` union (``thread.create``,
``thread.turn.start``, ``thread.turn.interrupt``); ids are client-allocated UUIDs and the server
stamps ``createdAt`` with its own clock, so the value sent only has to be a string. The
bearer token comes from the user's own T3 Code CLI (``t3 auth session issue``); the toolkit
never mints, reads or stores a login, only the token the user configured.

Orchestrator V2 (protocol 2) removes the HTTP dispatch endpoint and gates the WebSocket on
``?orchestrationProtocol=2``. ``probe`` reports which protocol a host speaks; every other route
refuses a protocol-2 host instead of guessing, so the V2 client can be added as one more module
without changing these contracts.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from ..core import config
from ..core.envelope import now
from ..core.errors import (BACKEND_FAILED, BACKEND_TIMEOUT, BUSY, CONFIG_INVALID, CONFIG_MISSING, DELIVERY_UNCERTAIN,
                           INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING, NOT_IMPLEMENTED, UNSUPPORTED_PLATFORM, Failure)

PROTOCOL = 1
MAX_BODY = 8 * 1024 * 1024
MAX_PROMPT = 200_000
MAX_TEXT = 512
MAX_OPTIONS = 16
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
OPTION_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
RUNTIME_MODES = ("approval-required", "auto-accept-edits", "auto", "full-access")
INTERACTION_MODES = ("default", "plan")
TURN_STATES = ("running", "interrupted", "completed", "error")
DESCRIPTOR_PATH = "/.well-known/t3/environment"
TIMEOUT = 20


# ----- host discovery -----------------------------------------------------------------

def t3_home() -> Path:
    override = os.environ.get("T3CODE_HOME")
    return Path(override) if override else Path.home() / ".t3"


def runtime_state(home: Path | None = None) -> dict:
    """The server's own record of where it listens, written when it starts."""
    path = (home or t3_home()) / "userdata" / "server-runtime.json"
    if path.is_symlink() or not path.is_file():
        raise Failure(CONFIG_MISSING, f"No running T3 Code server is recorded at {path}",
                      "Start T3 Code, or pass the server origin explicitly (for example http://127.0.0.1:3773).")
    raw = path.read_bytes()
    if len(raw) > 65536:
        raise Failure(INPUT_LIMIT, f"{path} is larger than expected")
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise Failure(INPUT_INVALID, f"{path} is not JSON") from exc
    if not isinstance(value, dict) or not isinstance(value.get("origin"), str) or not isinstance(value.get("pid"), int):
        raise Failure(INPUT_INVALID, f"{path} lacks origin and pid")
    return {"path": str(path), "origin": value["origin"], "pid": value["pid"], "port": value.get("port"),
            "started_at": value.get("startedAt")}


def origin_for(argument: str | None) -> tuple[str, dict | None]:
    if argument:
        return normalize_origin(argument), None
    state = runtime_state()
    return normalize_origin(state["origin"]), state


def normalize_origin(text: str) -> str:
    parsed = urllib.parse.urlsplit(text if "://" in text else "http://" + text)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.path not in ("", "/") or parsed.query:
        raise Failure(INPUT_INVALID, f"Server origin must be http(s)://host[:port] without a path: {text!r}")
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}"


# ----- HTTP -----------------------------------------------------------------------------

def _request(origin: str, method: str, path: str, *, token: str | None = None, body: dict | None = None,
             timeout: int = TIMEOUT) -> tuple[int, dict | list | None]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, allow_nan=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(origin + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - origin validated above
            payload = response.read(MAX_BODY + 1)
            status = response.status
    except urllib.error.HTTPError as exc:
        with exc:
            payload = exc.read(MAX_BODY + 1)
            status = exc.code
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            raise Failure(BACKEND_TIMEOUT, f"{method} {path} did not answer within {timeout} s",
                          "The server may still have applied the command. Read agent status before repeating anything.") from exc
        raise Failure(BACKEND_FAILED, f"Cannot reach the T3 Code server at {origin}: {reason}",
                      "Is T3 Code running? `pat agent probe` reads server-runtime.json to find it.") from exc
    if len(payload) > MAX_BODY:
        raise Failure(INPUT_LIMIT, f"{method} {path} answered with more than {MAX_BODY} bytes")
    parsed: dict | list | None = None
    if payload.strip():
        try:
            parsed = json.loads(payload)
        except ValueError:
            parsed = None
    return status, parsed


def _fail_http(status: int, parsed, what: str) -> Failure:
    code = parsed.get("code") if isinstance(parsed, dict) else None
    if status == 401:
        return Failure(CONFIG_INVALID, f"{what}: the server rejected the bearer token (401)",
                       "Issue a new one with your T3 Code CLI: t3 auth session issue --token-only, then pat configure --t3-bearer-token <token>.")
    if status == 403:
        scope = parsed.get("requiredScope") if isinstance(parsed, dict) else None
        return Failure(CONFIG_INVALID, f"{what}: the token lacks the scope {scope or 'required'} (403)",
                       "Issue the token with t3 auth session issue (administrative scopes) rather than a pairing token.")
    if status == 400:
        return Failure(INPUT_INVALID, f"{what}: the server rejected the command ({code or 'invalid_request'})",
                       "The command shape is bound to the server version; run pat agent probe and compare serverVersion with docs/AGENT-HOSTS.md.")
    if status == 404:
        return Failure(INPUT_MISSING, f"{what}: not found ({code or 404})")
    if status == 426:
        return Failure(NOT_IMPLEMENTED, f"{what}: the server requires a newer orchestration protocol (426)",
                       "This host runs Orchestrator V2; pat drives protocol 1 only. See docs/AGENT-HOSTS.md.")
    return Failure(BACKEND_FAILED, f"{what}: HTTP {status} ({code or 'no code'})")


def probe(origin: str) -> dict:
    status, parsed = _request(origin, "GET", DESCRIPTOR_PATH)
    if status != 200 or not isinstance(parsed, dict):
        raise _fail_http(status, parsed, "probe")
    version = parsed.get("serverVersion")
    environment = parsed.get("environmentId")
    if not isinstance(version, str) or not isinstance(environment, str):
        raise Failure(INPUT_INVALID, "The descriptor lacks serverVersion or environmentId; this is not a T3 Code server")
    protocol = parsed.get("orchestrationProtocolVersion")
    protocol = protocol if isinstance(protocol, int) else 1
    capabilities = parsed.get("capabilities")
    return {
        "origin": origin, "server_version": version, "environment_id": environment, "label": parsed.get("label"),
        "platform": parsed.get("platform"), "orchestration_protocol": protocol,
        "capabilities": sorted(capabilities) if isinstance(capabilities, dict) else [],
        "drivable": protocol == PROTOCOL,
        "thread_url": origin + "/" + environment + "/<thread-id>",
    }


def require_protocol_1(origin: str) -> dict:
    info = probe(origin)
    if info["orchestration_protocol"] != PROTOCOL:
        raise Failure(NOT_IMPLEMENTED,
                      f"The server at {origin} speaks orchestration protocol {info['orchestration_protocol']}; pat drives protocol 1 (the nightly HTTP dispatch)",
                      "Orchestrator V2 hosts need the WebSocket launchThread client, which this release does not carry. See docs/AGENT-HOSTS.md.",
                      probe=info)
    return info


def token() -> str:
    value = config.load().get("t3_bearer_token")
    if not value:
        raise Failure(CONFIG_MISSING, "Configuration key 't3_bearer_token' is not set",
                      "Issue one with your T3 Code CLI (t3 auth session issue --token-only --ttl 30d) and run: pat configure --t3-bearer-token <token>")
    return value


# ----- reads ----------------------------------------------------------------------------

def _turn(thread: dict) -> dict:
    latest = thread.get("latestTurn") or {}
    session = thread.get("session") or {}
    return {
        "turn_state": latest.get("state"), "turn_id": latest.get("turnId"),
        "turn_requested_at": latest.get("requestedAt"), "turn_started_at": latest.get("startedAt"),
        "turn_completed_at": latest.get("completedAt"),
        "session_status": session.get("status"), "session_error": session.get("lastError"),
        "provider": session.get("providerName"), "settled_at": thread.get("settledAt"),
        "pending_approvals": bool(thread.get("hasPendingApprovals")),
        "pending_user_input": bool(thread.get("hasPendingUserInput")),
    }


def hosts(origin: str, bearer: str) -> dict:
    info = require_protocol_1(origin)
    status, parsed = _request(origin, "GET", "/api/orchestration/shell", token=bearer)
    if status != 200 or not isinstance(parsed, dict):
        raise _fail_http(status, parsed, "hosts")
    projects = [{"id": p.get("id"), "title": p.get("title"), "workspace_root": p.get("workspaceRoot"),
                 "default_model_selection": p.get("defaultModelSelection")}
                for p in parsed.get("projects", []) if isinstance(p, dict)]
    threads = [{"id": t.get("id"), "project_id": t.get("projectId"), "title": t.get("title"),
                "model_selection": t.get("modelSelection"), "runtime_mode": t.get("runtimeMode"),
                "worktree_path": t.get("worktreePath"), "branch": t.get("branch"),
                "archived_at": t.get("archivedAt"), "updated_at": t.get("updatedAt"), **_turn(t)}
               for t in parsed.get("threads", []) if isinstance(t, dict)]
    return {"probe": info, "projects": projects, "threads": threads, "snapshot_sequence": parsed.get("snapshotSequence"),
            "game_touched": False}


def status(origin: str, bearer: str, thread_id: str, message_limit: int = 4) -> dict:
    info = require_protocol_1(origin)
    validate_id(thread_id, "thread id")
    path = "/api/orchestration/threads/" + urllib.parse.quote(thread_id, safe="")
    code, parsed = _request(origin, "GET", path, token=bearer)
    if code != 200 or not isinstance(parsed, dict) or not isinstance(parsed.get("thread"), dict):
        raise _fail_http(code, parsed, "status")
    thread = parsed["thread"]
    messages = [m for m in thread.get("messages", []) if isinstance(m, dict)]
    recent = [{"id": m.get("id"), "role": m.get("role"), "streaming": bool(m.get("streaming")),
               "created_at": m.get("createdAt"), "text": str(m.get("text", ""))[:4000]}
              for m in messages[-message_limit:]]
    return {"probe": info, "thread_id": thread.get("id"), "project_id": thread.get("projectId"), "title": thread.get("title"),
            "model_selection": thread.get("modelSelection"), "runtime_mode": thread.get("runtimeMode"),
            "interaction_mode": thread.get("interactionMode"), "worktree_path": thread.get("worktreePath"),
            "branch": thread.get("branch"), **_turn(thread), "message_count": len(messages), "recent_messages": recent,
            "thread_url": f"{origin}/{info['environment_id']}/{thread.get('id')}",
            "verification": "Server read model only. A completed turn means the provider returned; whether the task is done is in the messages and the receipts the agent wrote."}


# ----- models (this machine's T3 Code settings) ------------------------------------------

def models(home: Path | None = None) -> dict:
    home = home or t3_home()
    settings_path = home / "userdata" / "settings.json"
    manifest_path = home / "userdata" / "model-manifest.json"
    if not settings_path.is_file():
        raise Failure(CONFIG_MISSING, f"No T3 Code settings at {settings_path}",
                      "Set T3CODE_HOME to the T3 Code data directory this server runs from, or pass --home.")
    settings = _small_json(settings_path)
    manifest = _small_json(manifest_path).get("manifest", {}) if manifest_path.is_file() else {}
    instances = []
    for instance_id, row in (settings.get("providerInstances") or {}).items():
        if not isinstance(row, dict):
            continue
        driver = row.get("driver")
        provider = (manifest.get("providers") or {}).get(driver) or {}
        profiles = provider.get("profiles") or {}
        rows = []
        for model in provider.get("models") or []:
            if not isinstance(model, dict) or not model.get("slug"):
                continue
            profile = profiles.get(model.get("profile")) or {}
            descriptors = (profile.get("capabilities") or {}).get("optionDescriptors") or []
            rows.append({"slug": model["slug"], "name": model.get("name"), "status": model.get("status"),
                         "options": [{"id": d.get("id"), "label": d.get("label"), "type": d.get("type"),
                                      "choices": [{"id": c.get("id"), "label": c.get("label"), "default": bool(c.get("isDefault"))}
                                                  for c in d.get("options", []) if isinstance(c, dict)]}
                                     for d in descriptors if isinstance(d, dict)]})
        current = (manifest.get("currentModels") or {}).get(driver) or []
        instances.append({"instance_id": instance_id, "driver": driver, "display_name": row.get("displayName"),
                          "enabled": row.get("enabled", True), "default_chat_model": (provider.get("defaults") or {}).get("chat"),
                          "current_models": current, "models": rows})
    return {"home": str(home), "manifest_updated_at": manifest.get("updatedAt"), "instances": instances,
            "note": "Read from this machine's T3 Code settings and cached model manifest; a driver with no manifest entry lists no models here. "
                    "Pick instance_id, model slug and option choices explicitly; pat never chooses for the user."}


def _small_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise Failure(INPUT_MISSING, f"Missing file: {path}")
    raw = path.read_bytes()
    if len(raw) > MAX_BODY:
        raise Failure(INPUT_LIMIT, f"{path} exceeds {MAX_BODY} bytes")
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise Failure(INPUT_INVALID, f"{path} is not JSON") from exc
    return value if isinstance(value, dict) else {}


# ----- writes ---------------------------------------------------------------------------

def validate_id(value: str, what: str) -> str:
    if not isinstance(value, str) or not ID_RE.match(value):
        raise Failure(INPUT_INVALID, f"Invalid {what}: {value!r}")
    return value


def read_prompt(text: str) -> str:
    if text.startswith("@"):
        path = Path(text[1:]).expanduser()
        if path.is_symlink() or not path.is_file():
            raise Failure(INPUT_MISSING, f"Prompt file is missing: {path}")
        if path.stat().st_size > MAX_PROMPT:
            raise Failure(INPUT_LIMIT, f"Prompt file exceeds {MAX_PROMPT} bytes: {path}")
        text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise Failure(INPUT_INVALID, "The prompt is empty")
    if len(text) > MAX_PROMPT:
        raise Failure(INPUT_LIMIT, f"The prompt exceeds {MAX_PROMPT} characters")
    return text


def model_selection(instance: str, model: str, options: list[str]) -> dict:
    validate_id(instance, "provider instance id")
    if not isinstance(model, str) or not model.strip() or len(model) > MAX_TEXT:
        raise Failure(INPUT_INVALID, "Provide the model slug exactly as pat agent models lists it")
    rows = []
    for item in options or []:
        key, sep, value = item.partition("=")
        if not sep or not OPTION_ID_RE.match(key) or not value or len(value) > MAX_TEXT:
            raise Failure(INPUT_INVALID, f"Options are id=value, for example effort=high: {item!r}")
        rows.append({"id": key, "value": {"true": True, "false": False}.get(value.lower(), value)})
    if len(rows) > MAX_OPTIONS:
        raise Failure(INPUT_LIMIT, f"At most {MAX_OPTIONS} options")
    selection = {"instanceId": instance, "model": model.strip()}
    if rows:
        selection["options"] = rows
    return selection


def _dispatch(origin: str, bearer: str, command: dict, what: str) -> dict:
    code, parsed = _request(origin, "POST", "/api/orchestration/dispatch", token=bearer, body=command, timeout=60)
    if code != 200:
        raise _fail_http(code, parsed, what)
    sequence = parsed.get("sequence") if isinstance(parsed, dict) else None
    if not isinstance(sequence, int):
        raise Failure(DELIVERY_UNCERTAIN, f"{what}: the server answered 200 without a sequence; the command may have applied",
                      "Read agent status before repeating anything.")
    return {"command_id": command["commandId"], "type": command["type"], "sequence": sequence}


def dispatch(origin: str, bearer: str, *, project_id: str, title: str, prompt: str, selection: dict,
             runtime_mode: str = "full-access", interaction_mode: str = "default",
             worktree_path: str | None = None, branch: str | None = None) -> dict:
    info = require_protocol_1(origin)
    validate_id(project_id, "project id")
    if not title.strip() or len(title) > MAX_TEXT:
        raise Failure(INPUT_INVALID, "Provide a non-empty --title up to 512 characters")
    if runtime_mode not in RUNTIME_MODES:
        raise Failure(INPUT_INVALID, f"--runtime-mode must be one of {RUNTIME_MODES}")
    if interaction_mode not in INTERACTION_MODES:
        raise Failure(INPUT_INVALID, f"--interaction-mode must be one of {INTERACTION_MODES}")
    if worktree_path is not None and not Path(worktree_path).is_absolute():
        raise Failure(INPUT_INVALID, "--worktree must be an absolute path the server can see")
    thread_id = str(uuid.uuid4())
    stamp = now()
    create = {"type": "thread.create", "commandId": str(uuid.uuid4()), "threadId": thread_id, "projectId": project_id,
              "title": title.strip(), "modelSelection": selection, "runtimeMode": runtime_mode,
              "interactionMode": interaction_mode, "branch": branch, "worktreePath": worktree_path, "createdAt": stamp}
    created = _dispatch(origin, bearer, create, "dispatch thread.create")
    message_id = str(uuid.uuid4())
    start = {"type": "thread.turn.start", "commandId": str(uuid.uuid4()), "threadId": thread_id,
             "message": {"messageId": message_id, "role": "user", "text": prompt, "attachments": []},
             "modelSelection": selection, "runtimeMode": runtime_mode, "interactionMode": interaction_mode,
             "createdAt": stamp}
    try:
        started = _dispatch(origin, bearer, start, "dispatch thread.turn.start")
    except Failure as exc:
        exc.details.update(thread_id=thread_id, thread_created=created,
                           note="The thread exists but its first turn was not confirmed; send the prompt again with pat agent send after checking status.")
        raise
    return {"probe": {k: info[k] for k in ("origin", "server_version", "environment_id", "orchestration_protocol")},
            "thread_id": thread_id, "message_id": message_id, "project_id": project_id, "title": title.strip(),
            "model_selection": selection, "runtime_mode": runtime_mode, "interaction_mode": interaction_mode,
            "worktree_path": worktree_path, "branch": branch, "commands": [created, started],
            "thread_url": f"{origin}/{info['environment_id']}/{thread_id}", "prompt_chars": len(prompt),
            "game_touched": False,
            "verification": "Both commands were accepted by the server (sequence numbers). Whether the provider started, and what it did, is read with pat agent status."}


def send(origin: str, bearer: str, thread_id: str, prompt: str, queue: bool = False) -> dict:
    current = status(origin, bearer, thread_id, message_limit=1)
    if current["turn_state"] == "running" and not queue:
        raise Failure(BUSY, f"Thread {thread_id} has a running turn; nothing was sent",
                      "Wait for turn_state to leave running, interrupt it, or pass --queue to let the server adopt the message afterwards.",
                      turn_id=current["turn_id"])
    message_id = str(uuid.uuid4())
    command = {"type": "thread.turn.start", "commandId": str(uuid.uuid4()), "threadId": thread_id,
               "message": {"messageId": message_id, "role": "user", "text": prompt, "attachments": []},
               "runtimeMode": current["runtime_mode"] or "full-access",
               "interactionMode": current["interaction_mode"] or "default", "createdAt": now()}
    accepted = _dispatch(origin, bearer, command, "send thread.turn.start")
    return {"thread_id": thread_id, "message_id": message_id, "queued_behind_running_turn": current["turn_state"] == "running",
            "command": accepted, "thread_url": current["thread_url"], "prompt_chars": len(prompt), "game_touched": False}


def interrupt(origin: str, bearer: str, thread_id: str) -> dict:
    current = status(origin, bearer, thread_id, message_limit=0)
    command = {"type": "thread.turn.interrupt", "commandId": str(uuid.uuid4()), "threadId": thread_id, "createdAt": now()}
    if current["turn_id"]:
        command["turnId"] = current["turn_id"]
    accepted = _dispatch(origin, bearer, command, "interrupt thread.turn.interrupt")
    return {"thread_id": thread_id, "turn_id": current["turn_id"], "turn_state_before": current["turn_state"],
            "command": accepted, "game_touched": False,
            "verification": "The interrupt was accepted. Read agent status to see the turn leave running."}
