"""Registered capture and test routes. Names and effects are the contract Thread 2 implements."""
from ..core.discovery import Route, register

OWNER = "thread-2-testing"

PLANNED = [
    Route("capture", "start", "Begin recording the T6 window with game-only audio into a new evidence directory", "captures-display",
          status="planned", owner=OWNER, requires_windows=True),
    Route("capture", "status", "Report recorder health, elapsed time, storage reserve and last fresh frame time", "inert",
          status="planned", owner=OWNER, requires_windows=True),
    Route("capture", "screenshot", "Save one fresh frame of the game window without focusing it", "captures-display",
          status="planned", owner=OWNER, requires_windows=True),
    Route("capture", "mark", "Protect recent footage and record a labelled marker with a screenshot attempt", "captures-display",
          status="planned", owner=OWNER, requires_windows=True),
    Route("capture", "save-clip", "Copy the last N seconds into a standalone clip without re-encoding", "writes-output",
          status="planned", owner=OWNER, requires_windows=True),
    Route("capture", "stop", "Stop and finalize the recording; probe the file and decode one frame", "captures-display",
          status="planned", owner=OWNER, requires_windows=True),
    Route("test", "plan", "Validate a test plan offline: package hashes, map recipe, capture profile and limits", "inert",
          status="planned", owner=OWNER),
    Route("test", "start", "Admit one finite plan, arm capture, launch or load and run the recipe", "changes-game",
          status="planned", owner=OWNER, requires_windows=True),
    Route("test", "status", "Read saved run state, artifacts and recent events; not a fresh engine query", "inert",
          status="planned", owner=OWNER),
    Route("test", "cancel", "Stop automated play and hand the game to the human; recording may continue", "changes-game",
          status="planned", owner=OWNER, requires_windows=True),
    Route("test", "report", "Write the run's sanitized JSON report with verdict, evidence and remaining gates", "writes-output",
          status="planned", owner=OWNER),
]

for route in PLANNED:
    register(route)
