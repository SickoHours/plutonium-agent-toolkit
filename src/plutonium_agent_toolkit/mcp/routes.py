"""Registered Model Context Protocol routes.

``pat mcp serve`` speaks MCP on stdin and stdout so any harness that loads MCP servers reaches
the same typed actions the control plane's page exposes: one registered ``pat`` route each, with
validated parameters, run as a child process with its own receipt. It adds no capability: an
action the plane refuses here is refused there, and there is no arbitrary-argv tool.
"""
from ..core.discovery import Route, register

OWNER = "thread-4-control-plane"

ROUTES = [
    Route("mcp", "tools", "List the MCP tools the bridge exposes, with their JSON Schemas; prints one JSON document and serves nothing", "inert",
          status="implemented", owner=OWNER,
          notes="Arguments: [--library <dir>]... [--jobs <dir>]. The same typed actions as `plane actions`, as MCP tool definitions."),
    Route("mcp", "serve", "Speak Model Context Protocol on stdin and stdout, exposing the control plane's typed actions as tools", "serves-stdio",
          status="implemented", owner=OWNER,
          notes="Arguments: [--library <dir>]... [--jobs <dir>] [--seconds N]. stdout carries the protocol; diagnostics go to stderr and the "
                "invocation's own JSON document is written there too, so the channel stays clean. Every tool is one registered route with "
                "validated parameters, run as a `pat` child with its own receipt, one at a time; a state-changing action needs confirmed: true, "
                "and no tool takes argv, a shell string or an absolute path."),
]

for route in ROUTES:
    register(route)
