"""Registered control-plane routes.

The control plane is a web page served on this machine's loopback interface by ``pat plane
serve``. It holds no modding logic: every button on it is one of the typed actions in
``actions.py``, each of which is one ``pat`` route run as a child process with validated
arguments, or a dispatch to an agent host through ``pat agent``. It picks no model, reads no
credential and accepts no free-form command.
"""
from ..core.discovery import Route, register

OWNER = "thread-4-control-plane"

ROUTES = [
    Route("plane", "actions", "List the typed actions the control plane exposes, each bound to one route and its parameters", "inert",
          status="implemented", owner=OWNER,
          notes="The table is the whole surface of the page: no action takes argv, a shell string or an arbitrary path."),
    Route("plane", "serve", "Serve the control plane page on 127.0.0.1 with a per-start token and run its actions as pat child processes", "serves-local",
          status="implemented", owner=OWNER,
          notes="Arguments: [--library <dir>]... [--jobs <dir>] [--port N] [--seconds N]. Loopback only; the URL with the token is printed once. "
                "Every job it starts writes its own receipt under the jobs directory; agent actions send the configured bearer only through pat agent."),
]

for route in ROUTES:
    register(route)
