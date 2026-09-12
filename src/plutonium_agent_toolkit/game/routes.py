"""Registered game routes. Live routes run in one bounded worker under the toolkit mutex."""
from ..core.discovery import Route, register

OWNER = "thread-2-game-control"
STORAGE = ["plutonium_storage_t6"]

ROUTES = [
    Route("game", "status", "List visible T6 Zombies windows and the foreground window; no engine input", "inert",
          status="implemented", owner=OWNER, requires_windows=True),
    Route("game", "info", "Read fresh map, mod, local-server and cheat state through the external console", "query-engine",
          status="implemented", owner=OWNER, requires_windows=True, requires_config=STORAGE),
    Route("game", "mods", "List installed mod folders from storage; disk inventory only", "inert",
          status="implemented", owner=OWNER, requires_config=STORAGE),
    Route("game", "launch", "Start T6 Zombies through the registered plutonium://play/t6zm handler and log foreground changes", "changes-game",
          status="implemented", owner=OWNER, requires_windows=True, requires_config=["plutonium_launcher"],
          notes="Reports launch_requested, game_detected and focus_preserved separately. Never answers launcher prompts."),
    Route("game", "select-mod", "Select an installed mod folder (or 'base'); leaves the match, unloads, then loads", "changes-game",
          status="implemented", owner=OWNER, requires_windows=True, requires_config=STORAGE,
          notes="Argument: <folder-id> from `game mods`, or base."),
    Route("game", "reload-mod", "Leave the match, unload and reload the currently selected mod", "changes-game",
          status="implemented", owner=OWNER, requires_windows=True, requires_config=STORAGE),
    Route("game", "load-map", "Verify map settings, then load a catalogued map once; keeps the selected mod", "changes-game",
          status="implemented", owner=OWNER, requires_windows=True, requires_config=STORAGE,
          notes="Argument: a map ID from maps.json. DLC5 maps require a selected mod that ships zone/<map>.ff."),
    Route("game", "fast-restart", "Send fast_restart once in a running local match", "changes-game",
          status="implemented", owner=OWNER, requires_windows=True, requires_config=STORAGE),
    Route("game", "map-restart", "Send map_restart once in a running local match", "changes-game",
          status="implemented", owner=OWNER, requires_windows=True, requires_config=STORAGE),
    Route("game", "disconnect", "Leave the current match once", "changes-game",
          status="implemented", owner=OWNER, requires_windows=True, requires_config=STORAGE),
    Route("game", "check-load", "Check a load ID against original process identity, fresh state and bounded new log lines", "query-engine",
          status="implemented", owner=OWNER, requires_windows=True, requires_config=STORAGE,
          notes="Argument: the load_id from the original response; valid for ten minutes."),
    Route("game", "quit", "Ask the engine to quit once and wait up to 20 s; never force-kills", "changes-game",
          status="implemented", owner=OWNER, requires_windows=True),
    Route("game", "install-mod", "Copy a built mod.ff into storage/<game>/mods/<folder>; the fastfile magic picks t6 or iw5; file-only, never overwrites silently", "writes-output",
          status="implemented", owner=OWNER, requires_config=[],
          notes="Arguments: <path to mod.ff> <folder-id> [--replace]. Needs plutonium_storage_t6 or plutonium_storage_iw5 for the title the magic names. "
                "Loading it is a separate step: select-mod on T6; the console fs_game/loadmod on IW5 (no route yet)."),
]

for route in ROUTES:
    register(route)
