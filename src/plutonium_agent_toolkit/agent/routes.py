"""Registered agent-host routes: dispatch work to a running T3 Code server.

T3 Code is the only agent host with a route today. Its nightly (orchestration protocol 1)
exposes an authenticated HTTP dispatch endpoint; the orchestrator V2 branch replaces it with a
WebSocket call, so ``agent probe`` reports the protocol the host speaks and every other route
refuses a host it cannot drive rather than guessing.
"""
from ..core.discovery import Route, register

OWNER = "thread-3-agent-hosts"

ROUTES = [
    Route("agent", "probe", "Read a T3 Code server's public descriptor: version, environment id and orchestration protocol; no token", "inert",
          status="available", owner=OWNER,
          notes="Argument: the server origin, or none to read T3CODE_HOME/userdata/server-runtime.json. Protocol 1 is the nightly's HTTP dispatch; 2 (Orchestrator V2) is not driven yet."),
    Route("agent", "hosts", "List the projects and threads a T3 Code server knows, with each thread's turn state; disk-free, engine-free", "inert",
          status="available", owner=OWNER, requires_config=["t3_bearer_token"],
          notes="Reads GET /api/orchestration/shell. Needs a bearer with orchestration:read."),
    Route("agent", "models", "List the provider instances, models and reasoning options a T3 Code host offers, so nothing is assumed", "inert",
          status="available", owner=OWNER,
          notes="Reads T3CODE_HOME/userdata/settings.json and model-manifest.json on this machine; a remote host's list is not readable over HTTP on protocol 1."),
    Route("agent", "dispatch", "Create a T3 Code thread in a project and start its first turn with the prompt, model and reasoning the user chose", "writes-output",
          status="available", owner=OWNER, requires_config=["t3_bearer_token"],
          notes="Arguments: --project <id> --title <text> --prompt <text|@file> --instance <id> --model <slug> [--option id=value]... [--runtime-mode ...] [--worktree <path>] [--branch <name>]. Two POSTs to /api/orchestration/dispatch: thread.create, then thread.turn.start. Never picks a model or reasoning level itself."),
    Route("agent", "status", "Read one thread's turn state, session state and last messages from a T3 Code server", "inert",
          status="available", owner=OWNER, requires_config=["t3_bearer_token"],
          notes="Argument: <thread-id>. latestTurn.state is running|interrupted|completed|error; a completed turn is not a completed task."),
    Route("agent", "send", "Send a follow-up turn to an existing T3 Code thread", "writes-output",
          status="available", owner=OWNER, requires_config=["t3_bearer_token"],
          notes="Arguments: <thread-id> --prompt <text|@file>. Refuses while the thread's latest turn is running unless --queue; the server then adopts it after the current turn."),
    Route("agent", "interrupt", "Interrupt the running turn on a T3 Code thread once", "writes-output",
          status="available", owner=OWNER, requires_config=["t3_bearer_token"],
          notes="Argument: <thread-id>. Sends thread.turn.interrupt; the thread stays open."),
]

for route in ROUTES:
    register(route)
