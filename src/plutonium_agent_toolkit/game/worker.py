"""Internal worker entry: ``python -m plutonium_agent_toolkit.game.worker <action> <argument>``.

Spawned only by ``control.dispatch``. Prints one JSON document and exits 0 on
success, 1 on a structured failure. Never invoke it directly.
"""
import json
import os
import sys

from ..core import platform
from ..core.errors import Failure
from .control import WORKER_TOKEN_ENV, execute_worker


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(json.dumps({"ok": False, "error_code": "invalid_arguments", "message": "worker takes action and argument"}))
        return 2
    action, argument = argv[0], argv[1] or None
    try:
        # Only control.dispatch may start this worker: it sets a one-shot token and owns
        # the 110-second deadline. A direct invocation has neither and is refused before
        # any Win32 call. Wine is refused for the same reason the public routes refuse it.
        token = os.environ.pop(WORKER_TOKEN_ENV, "")
        if len(token) != 32 or not all(c in "0123456789abcdef" for c in token):
            raise Failure("invalid_arguments", "The game worker is internal; run `pat game <action>` instead")
        platform.require_windows(f"game {action}")
        result = execute_worker(action, argument)
        print(json.dumps({"ok": True, **result}))
        return 0
    except Failure as error:
        print(json.dumps(error.to_dict()))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
