"""Agent-host routes with protocol 1 HTTP and protocol 2 WebSocket writes.

Existing available status is backed by protocol 1 native receipts. Protocol 2 writes have
fake-transport evidence until a native authenticated qualification is recorded.
"""
from ..core.discovery import Route, register

OWNER = "thread-3-agent-hosts"

ROUTES = [
    Route("agent", "probe", "Read a T3 Code server's public descriptor: version, environment id and orchestration protocol; no token", "inert",
          status="available", owner=OWNER,
          notes="Argument: the server origin, or none to read T3CODE_HOME/userdata/server-runtime.json. Protocols 1 (HTTP writes) and 2 (WebSocket writes) are supported; unknown versions are refused. drivable reports client compatibility, not authenticated qualification."),
    Route("agent", "hosts", "List the projects and threads a T3 Code server knows, with each thread's turn state; disk-free, engine-free", "inert",
          status="available", owner=OWNER, requires_config=["t3_bearer_token"],
          notes="Reads GET /api/orchestration/shell. Needs a bearer with orchestration:read."),
    Route("agent", "models", "List the provider instances, models and reasoning options a T3 Code host offers, so nothing is assumed", "inert",
          status="available", owner=OWNER,
          notes="Reads T3CODE_HOME/userdata/settings.json and model-manifest.json on this machine; a remote host's list is not readable over HTTP on protocol 1."),
    Route("agent", "dispatch", "Create a T3 Code thread in a project and start its first turn with the prompt, model and reasoning the user chose", "writes-output",
          status="available", owner=OWNER, requires_config=["t3_bearer_token"],
          notes="Arguments: --project <id> --title <text> --prompt <text|@file> --instance <id> --model <slug> [--option id=value]... [--runtime-mode ...] [--worktree <path>] [--branch <name>]. Protocol 1: thread.create then thread.turn.start over HTTP. Protocol 2: one orchestration.launchThread WebSocket call. Never picks a model or reasoning level itself."),
    Route("agent", "status", "Read one thread's turn state, session state and last messages from a T3 Code server", "inert",
          status="available", owner=OWNER, requires_config=["t3_bearer_token"],
          notes="Argument: <thread-id>. turn_state is running|interrupted|completed|error; V2 also reports raw run_state and active_run_id; a completed turn is not a completed task."),
    Route("agent", "send", "Send a follow-up turn to an existing T3 Code thread", "writes-output",
          status="available", owner=OWNER, requires_config=["t3_bearer_token"],
          notes="Arguments: <thread-id> --prompt <text|@file>. Refuses while the thread's latest turn is running unless --queue; the server then adopts it after the current turn."),
    Route("agent", "interrupt", "Interrupt the running turn on a T3 Code thread once", "writes-output",
          status="available", owner=OWNER, requires_config=["t3_bearer_token"],
          notes="Argument: <thread-id>. Sends thread.turn.interrupt (V1) or run.interrupt with the active run id (V2); the thread stays open."),
]

for route in ROUTES:
    register(route)
