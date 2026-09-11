# Control plane: a page over the routes

`pat plane serve` puts a small web page on this machine that shows the library of declared
modules and packs, plans and builds compositions, installs a built package, drives the game on
Windows, and hands prompts to a T3 Code thread. It contains no modding logic. Every button is one
typed action bound to one registered `pat` route; the server validates the parameters, adds
`--output` for job routes, runs `pat` as a child process and shows the JSON it printed. The
receipts are the child's own, under the jobs directory, exactly as if the command had been typed.

The agents are the runtime. Where a control needs judgement (resolve the collisions a plan
listed, port a feature from a lead, diagnose a crash, load and check a build on Linux), the
page's Agent screen dispatches a playbook to a T3 Code thread with the model and reasoning the
person picked, and the thread does the work with `pat` itself (`docs/AGENT-HOSTS.md`).

## Start it

```sh
pat plane serve --library /abs/path/to/modules --jobs /abs/path/to/jobs --json
```

- `--library` (repeatable): directories holding module directories (`module.json` beside a
  recipe or a seed) and pack directories (`composition.json`). The page lists what it finds by
  reading those files; nothing is indexed or cached elsewhere.
- `--jobs`: where every job's output directory goes (`<action>-<n>`), plus the plane's own run
  records under `plane-runs/`. A dispatched prompt is written under `plane-prompts/` only while
  its `pat agent` child runs and is removed afterwards (and at shutdown). The jobs directory
  must not lie inside a library root, and no library root inside it.
- `--port` (default 0, a free port) and `--seconds` (default one hour): the server binds
  `127.0.0.1` only and stops on its deadline or Ctrl-C, then prints one JSON summary.

The URL is printed once on stderr with a per-start token in its fragment
(`http://127.0.0.1:<port>/#token=…`). Open that URL. The page sends the token in a header on
every API call; a request without it, or with a non-loopback `Host` or `Origin`, is refused.
The token is not written anywhere and dies with the process.

## Screens

| Screen | Controls | Routes behind them |
| --- | --- | --- |
| Library | The toolkit manifest and doctor; every declaration and composition under the library roots: id, kind, category, bases, maps, tags, payload, whether a seed's package is present; every loose `mod.ff` under a root, declared or not, offered to `module declare` | `manifest`, `doctor`, files; `module declare` |
| Pack | Plan a composition (collisions come back as decisions), build it, verify a build receipt | `module plan`, `module build`, `project verify` |
| Install | Installed mod folders, file-only install of a built package, game status, engine info, launch, select a mod, load a map, check a load | `game mods`, `game install-mod`, `game status`, `game info`, `game launch`, `game select-mod`, `game load-map`, `game check-load` |
| Agent | Probe the local T3 Code server, list its projects and threads, list this machine's provider instances, models and reasoning choices, dispatch a prompt, read a thread, send a follow-up, interrupt | `agent probe`, `agent hosts`, `agent models`, `agent dispatch`, `agent status`, `agent send`, `agent interrupt` |
| Registry | Registries recorded on this machine, search, show an entry, record a registry file (one under a library root, or an https URL typed in), fetch a module or pack at its exact commit; a fetched snapshot's declaration or composition then appears in the Pack selects | `registry list`, `registry search`, `registry show`, `registry add`, `module fetch` |
| Runs | Every action this plane started (argv, exit status, the child's JSON) and every `receipt.json` under the jobs directory | files |

`pat plane actions --json` prints the same table the page uses: each action's route, effect,
status, whether it is available on this host, its typed parameters, and whether it asks for
confirmation first. Actions whose route changes the game, queries the engine, writes to the
agent host or writes the toolkit configuration (`registry add`) always confirm. Windows-only routes are shown but disabled on other hosts; the page
says why.

## What the page cannot do, on purpose

- It never builds argv. A parameter is a typed value: a file under a named root that must end in
  the expected name (`composition.json`, `mod.ff`, `receipt.json`, `registry.json`), an id that
  matches the route's own pattern, an enum, an integer in range, or prompt text. Absolute paths,
  `..`, links and unknown parameters are refused before anything starts.
- It never names an output directory; the server numbers them under `--jobs`.
- It never picks a model or a reasoning level. The Agent screen lists what `agent models` found
  and the person chooses; `dispatch` refuses without an instance and a model.
- It never reads the bearer token. Agent actions are `pat agent` children, which load it from the
  toolkit configuration themselves and send it to the local server only.
- It runs one action at a time; a second request while one runs is answered `busy` at once and
  leaves nothing on disk. The single-run lock is taken before any parameter is checked.
- Its catalog is bounded (rows across roots, directories and loose packages per root) and says
  `truncated` when a bound was reached; a declaration or manifest that is unreadable, not
  strict JSON, not an object, or missing the fields the format requires first (`schema`, a
  valid `id` and `version` with exactly one payload, or a composition `name` with members) is
  shown with its error, never hidden and never a crash; full validation is `module plan`'s.
  A linked declaration file is not offered, because no action would accept it.
- It answers at most 32 connections at a time (a 33rd gets an immediate 503) and drops a
  connection whose request has not arrived within 30 seconds, so nothing can hold every
  worker; the receipt index keeps the newest 512 rows and says `truncated`.
- When it stops (deadline or Ctrl-C) it refuses new runs, interrupts a child still running so the
  child writes its cancelled receipt, kills it after a grace period (the whole tree: a process
  group on Linux, a Job Object on Windows), and reports `child_stopped_at_shutdown` in its
  summary; the run is recorded as `stopped`.
- It is not evidence. A green row is the child's `ok: true`; the six build facts (offline
  verified, installed, launched, loaded, playable, accepted) are stated by the receipts and the
  person, never by the page.

## Reading a run

Each run row carries `argv` (what ran), `exit_code`, `result` (the child's whole JSON document,
parsed in full; both pipes are read as bytes through bounded buffers, and a child that prints more
than 64 MiB is stopped and recorded with `output_overflow: true`, `stdout_head` and `stdout_bytes`)
and, for job routes, `output` (the directory holding `receipt.json` and the artifacts). Every
file the plane reads (declarations, manifests, receipts, request bodies) is strict JSON with a
size bound; anything else is listed as unreadable, and nothing it returns contains `NaN`. A run
that could not start a child (`stderr_head`), or exceeded the action's deadline (`status:
timeout`), is recorded the same way. The plane's own summary at exit counts runs and says
`game_touched: false`, because it touched nothing itself.

## The same actions without a browser

`pat mcp serve` speaks Model Context Protocol on stdin and stdout over this same runtime, so a
harness that loads MCP servers gets every action here as a native tool with a generated JSON
Schema. Same validation, same child processes, same receipts, same confirmation gate.
`docs/MCP.md`.

## Not here

- No live event stream: the page polls a run until it finishes.
- No thread transcript viewer: `agent status` shows the turn state and recent messages, and
  `thread_url` opens the thread in T3 Code.
- No catalog of remote registries beyond what `registry add` recorded; the marketplace view is
  `registry search` over recorded files.
- No authentication beyond the per-start token: the page is for the person at this machine.
