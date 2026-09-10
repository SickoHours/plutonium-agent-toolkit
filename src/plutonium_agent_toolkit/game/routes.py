"""Registered game routes. Names and effects are the contract Thread 2 implements."""
from ..core.discovery import Route, register

OWNER = "thread-2-game-control"

PLANNED = [
    Route("game", "status", "Identify the running T6 Zombies process and window without engine input", "inert",
          status="planned", owner=OWNER, requires_windows=True),
    Route("game", "info", "Read fresh map, mod, local-server and cheat state through the external console", "query-engine",
          status="planned", owner=OWNER, requires_windows=True, requires_config=["plutonium_storage_t6"]),
    Route("game", "launch", "Start T6 Zombies through the registered plutonium://play/t6zm handler; report focus events", "changes-game",
          status="planned", owner=OWNER, requires_windows=True, requires_config=["plutonium_launcher"],
          notes="Direct launch and background focus preservation are separate qualification results."),
    Route("game", "load-map", "Load a catalogued map with the selected mod; returns a load ID and check argv", "changes-game",
          status="planned", owner=OWNER, requires_windows=True, requires_config=["plutonium_storage_t6"]),
    Route("game", "select-mod", "Select an installed mod folder from the storage inventory", "changes-game",
          status="planned", owner=OWNER, requires_windows=True, requires_config=["plutonium_storage_t6"]),
    Route("game", "reload-mod", "Leave the match, unload and reload the selected mod", "changes-game",
          status="planned", owner=OWNER, requires_windows=True, requires_config=["plutonium_storage_t6"]),
    Route("game", "check-load", "Check a previous load against original process identity, state and bounded new log lines", "query-engine",
          status="planned", owner=OWNER, requires_windows=True),
    Route("game", "mods", "List installed mod folders from storage; disk inventory only", "inert",
          status="planned", owner=OWNER, requires_windows=False, requires_config=["plutonium_storage_t6"]),
    Route("game", "quit", "Ask the engine to quit once; never force-kills", "changes-game",
          status="planned", owner=OWNER, requires_windows=True),
]

for route in PLANNED:
    register(route)
