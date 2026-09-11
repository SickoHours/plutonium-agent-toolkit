# MCP: the routes as tools in any harness

`pat mcp serve` speaks [Model Context Protocol](https://modelcontextprotocol.io) on stdin and
stdout, so a coding agent whose harness loads MCP servers reaches the toolkit's routes as native
tools: no shell string to compose, no output to parse out of a terminal. It is the control
plane's second transport. The page (`docs/CONTROL-PLANE.md`) and the bridge expose the **same
typed actions**, validate them the same way, run them as the same `pat` child processes and leave
the same receipts. Neither adds a capability the command line does not already have.

## Register it with your harness

The bridge is an ordinary stdio MCP server: a command, its arguments, and the protocol on the
pipes. Most harnesses take the same JSON shape in their own configuration file:

```json
{
  "mcpServers": {
    "plutonium": {
      "command": "pat",
      "args": ["mcp", "serve",
               "--library", "/abs/path/to/your/modules",
               "--jobs", "/abs/path/to/your/jobs"]
    }
  }
}
```

Codex reads TOML instead, with the same two fields:

```toml
[mcp_servers.plutonium]
command = "pat"
args = ["mcp", "serve", "--library", "/abs/path/to/your/modules", "--jobs", "/abs/path/to/your/jobs"]
```

Claude Code, Gemini CLI and OpenCode each have an `mcp` subcommand that writes their own
configuration for you (`claude mcp add plutonium -- pat mcp serve --library … --jobs …`, and the
equivalents); their own documentation is the reference for where the file lives. If `pat` is not
on the harness's PATH, use the interpreter that has it: `"command": "python"`, `"args": ["-m",
"plutonium_agent_toolkit", "mcp", "serve", …]`.

`--library` (repeatable) and `--jobs` are the same directories the page takes, with the same
rules: absolute paths, no link as a root, and neither containing the other. `--seconds` (default
one hour, 60 to 86400) is a deadline; the bridge also stops when the harness closes its stdin.

Before wiring anything up, `pat mcp tools --json` prints every tool definition and serves nothing.

## What the tools are

One tool per typed action, named as the action is (`module-plan`, `game-install-mod`,
`agent-dispatch`), plus two local reads:

| Tool | What it answers |
| --- | --- |
| `library` | Every declaration, composition, seed manifest and loose package under the library roots, read from the files. Starts nothing |
| `runs` | Every run this bridge started, newest first, with its action, argv, status, exit code and result |
| every other tool | One registered `pat` route. A job route writes its receipt into a new directory under the jobs directory; the tool returns the route's own JSON document |

Each tool's JSON Schema is generated from the action's parameters, so a harness validates before
it calls. Three things the schemas make explicit:

- **A path on this machine is not a string.** It is `{"root": <index of a library root, or
  "jobs">, "path": "<relative path>"}`. There is no way to name an absolute path, a parent
  directory, a link, or a file outside the roots you gave. (`module-fetch`'s `path` is not one of
  these and its schema says so: it names a directory inside the repository being fetched, which is
  not a place on this machine at all, and stays a plain relative string.)
- **A state-changing tool requires `confirmed: true`** in its arguments, and says so in its
  description. Installing a package, selecting a mod, loading a map, adding a registry, fetching a
  module and dispatching an agent thread are all in that set. The flag is the bridge's record that
  a person saw the call; harnesses show a tool call before running it, and that is the point at
  which they should.
- **A tool this host cannot run says so in its description** (`NOT AVAILABLE on this host`) and is
  refused with the same `unsupported_platform` or `not_implemented` the page gives. The game
  routes need native Windows; the bridge does not hide them, because a hidden route looks like a
  missing feature.

The result of a route call is the child's own JSON document, with the run record beside it
(`{"run": {...}, "result": {...}}`), and `isError` set when the document is not `ok`. Keep it as
you would keep the command's stdout: that pair is the receipt. The two local reads answer with
their own object instead (`{"library": ...}`, `{"runs": ...}`); they start no child, so there is
no run record and no receipt to keep. A result of either kind is capped at 1 MiB: a library too
large for one message is refused with `output_limit`, and the way to read it is narrower roots or
the files themselves, not a receipt it never wrote.

## What the bridge cannot do, on purpose

- **No arbitrary command.** There is no tool that takes argv, a shell string, a script or a
  console string. The action table is the whole surface; adding a capability means adding a
  typed route, with tests and a support row, the same as everywhere else.
- **No second runtime.** Every call becomes `pat <route> … --json` as a child process, one at a
  time, with the route's own timeout, bounded output, and its receipt on disk. A second call sent
  while one runs is read straight away and refused with `busy`, rather than waiting unseen for its
  turn and running when the client has moved on.
- **No credential handling.** `agent dispatch` sends the bearer the user configured, through
  `pat agent`, exactly as the command line does. The bridge never reads, prints or forwards it.
- **No game beyond the routes.** The same rule as everywhere: `game` routes need the user's
  go-ahead for that specific test, which here is the confirmation flag plus whatever the harness
  shows the person.

## The stdio contract

stdout carries the protocol and nothing else: while the bridge runs, anything the process would
otherwise print is sent to stderr. Messages are JSON-RPC 2.0, one per line, UTF-8, bounded at
4 MiB of encoded bytes each (not characters, so a message of astral characters is measured as it
is sent); a longer message is refused and its tail drained so the stream stays in frame, and
text that nests deeply enough to exhaust the parser is a parse error, not the end of the session.
A tool result is bounded at 1 MiB and is encoded in chunks, so a result too large to carry back is
refused with `output_limit` rather than built in full first; its receipt on disk still holds
everything.
Both streams are read and written as UTF-8 with `\n` endings whatever the console's encoding is.
The bridge implements `initialize` (negotiating from `2025-06-18`, `2025-03-26`, `2024-11-05`),
`notifications/initialized`, `ping`, `tools/list` and `tools/call`; a message without
`jsonrpc: "2.0"` is an invalid request, any other method is a JSON-RPC "method not found", and a
request before `initialize` is refused.

Lines are read off the stream by a reader thread, so `--seconds` is reached even while a
connected harness sits idle, and a tool call that is still running when the deadline passes stops
waiting and says so rather than outliving it. A call in progress keeps reading the client: a
`notifications/cancelled` naming that request stops the child and sends no response for it, as the
protocol requires, and the plane accepts the next call normally afterwards. A termination signal
does the same, so shutdown does not wait for the route's own timeout. Anything else that arrives is
answered while the call runs, which is why a second `tools/call` comes back `busy` immediately.

Stdin closing is not a cancellation. `pat mcp serve < requests.jsonl > answers.jsonl` is exactly
that shape -- the requests run out long before the answers are read -- so a call already running
finishes and its answer is written; the session ends after it. To stop a run, withdraw it or send a
signal. The reader holds one message at a time: a harness
that keeps sending while a call runs waits in the pipe rather than filling this process's memory.
Answers are written by a second thread for the same reason in reverse: a harness that stops
reading stdout blocks that thread, not the loop, and after 30 seconds the session ends
(`stopped: undeliverable`) with the running child stopped and this invocation's own document
written to stderr instead of the full pipe (`document_on` says which stream it went to) -- an answer that cannot be delivered
means the next one cannot either, so no message still in hand is run. When the harness closes stdin, the deadline passes,
or a termination signal arrives, the bridge stops a running child, waits for its record, and
writes the invocation's own JSON document (library roots, jobs directory, tool count, messages
handled, how it stopped) as the last thing on stdout, after the protocol stream has ended.

## Not here

No resources, no prompts, no sampling, no subscriptions, no HTTP transport, and no tool that is
not an action on the page. If you want the page instead, or beside it, `pat plane serve` is the
same runtime with a browser in front of it.
