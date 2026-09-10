"""Internal worker entry: ``python -m plutonium_agent_toolkit.game.worker <action> <argument>``.

Spawned only by ``control.dispatch``. Prints one JSON document and exits 0 on
success, 1 on a structured failure. Never invoke it directly.
"""
import json
import sys

from ..core.errors import Failure
from .control import execute_worker


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(json.dumps({"ok": False, "error_code": "invalid_arguments", "message": "worker takes action and argument"}))
        return 2
    action, argument = argv[0], argv[1] or None
    try:
        result = execute_worker(action, argument)
        print(json.dumps({"ok": True, **result}))
        return 0
    except Failure as error:
        print(json.dumps(error.to_dict()))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
