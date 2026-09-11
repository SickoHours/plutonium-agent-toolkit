# Plutonium Agent Toolkit

**Agent-native tools, knowledge and playbooks for building, controlling and testing Plutonium
T6 Zombies mods.** You describe the result. Your coding agent researches the donor, extracts or
recovers the assets, adapts the tools, builds and verifies the package, installs it and launches
the game. You playtest and give the verdict. If your setup is unusual, the agent adapts the toolkit.

This is how the authoring workspace built its own library: over one hundred player-accepted
modules across wonder weapons, firearms, melee, perks, GobbleGums, bosses and power-ups, including
a weapon recovered live from a running Black Ops III match. The counts, the workflow and the exact
scope of each verdict are in [docs/TRACK-RECORD.md](docs/TRACK-RECORD.md). That page is the wide
view of what an agent can do with this environment. [docs/SUPPORT.md](docs/SUPPORT.md) is the
narrow one: it grades the packaged `pat` routes one at a time and is deliberately strict.

**This is meant to be modified.** It is open source and malleable by design. The person using it
already has a coding agent; the agent reads the docs, configures the toolkit to that machine, and
edits or extends it when the defaults do not fit. Every doc here is written for that agent to read.
See [AGENTS.md](AGENTS.md) and [docs/FOR-AGENTS.md](docs/FOR-AGENTS.md).

> **Status: public beta, `0.1.0b1`.** The development (file) tools run natively on Windows 11 and
> Arch Linux with receipts. Game control is implemented for native Windows and not yet qualified
> ([issue #8](https://github.com/SickoHours/plutonium-agent-toolkit/issues/8)). Screen capture
> and the autonomous test runner are a later release. macOS is untested and not claimed. Read
> [docs/SUPPORT.md](docs/SUPPORT.md) before trusting a route claim, and
> [CHANGELOG.md](CHANGELOG.md) for what each version ships.

## What "agent-native" means here

| Principle | How the toolkit delivers it |
| --- | --- |
| Agents discover, humans describe | `pat manifest --json` and `pat describe <group> <action> --json` are inert and complete. No hidden commands. |
| Every result is machine-checkable | One JSON document per invocation, stable `error_code` strings, exit statuses 0/1/2/130. |
| Work leaves receipts | Each job creates a new output directory with `receipt.json`: argv, input hashes, output hashes, logs. Failures keep their receipts. |
| Uncertainty is never replayed | Game commands report admitted, delivered, rejected or uncertain. An uncertain outcome is inspected, not retried. |
| Instructions travel with the code | `AGENTS.md`, `CLAUDE.md`, an installable skill and `SETUP-PROMPT.md` are versioned with the release they describe. |
| Malleable by default | The agent configures paths, overrides backends, edits adapters and adds routes to fit the user's machine. Nothing assumes a fixed install. `docs/FOR-AGENTS.md`. |
| Truth over marketing | Offline verified, installed, launched, playable, captured and player-accepted are separate statements. `docs/SUPPORT.md` says which one each route has earned. |

## Components

| Component | Group(s) | Purpose |
| --- | --- | --- |
| Development (Windows, Linux) | `dev`, `gsc`, `ff`, `project`, `module`, `model`, `audio`, `image`, `lua`, `weapon` | Scripts, fastfiles, models, media, saved-asset recipes and compositions of declared modules through pinned upstream backends. Verified on Windows 11 and Arch Linux (Omarchy); macOS untested |
| Agent hosts (Windows, Linux) | `agent` | Hand a prompt to a running T3 Code server as a new thread with the caller's model and reasoning choice; read the thread back. Orchestration protocol 1 (nightly and stable); V2 hosts are detected and refused. [docs/AGENT-HOSTS.md](docs/AGENT-HOSTS.md) |
| Game control (Windows) | `game` | Launch T6 Zombies, select mods, load maps, verify loads through the external Win32 console. Native Windows only |
| Testing | `capture`, `test` | **Deferred to a later release.** Contracts registered; routes refuse with `not_implemented` |

Backends (OpenAssetTools, gsc-tool, Blender, Cast, FFmpeg and others) are downloaded from their
upstream releases at setup and verified by SHA-256. This repository redistributes none of them.
[docs/BACKENDS.md](docs/BACKENDS.md) lists which program each route runs, with its command line,
version, license and pinned platforms; see [NOTICE](NOTICE) for licenses.

## For users: hand this to your agent

You already have a coding agent, so let it do the work. To build and package mods, Windows or
Linux works; to control a running game you need Windows. macOS is untested and not claimed.

1. Install Python 3.11 or newer.
2. Clone or download this repository.
3. Paste [SETUP-PROMPT.md](SETUP-PROMPT.md) into your agent, working in the repository folder.

The agent installs the toolkit for your user, configures it to your machine, obtains the backends
(downloading the pinned build where one exists for your platform, or using a tool you already have
via `PAT_BACKEND_<NAME>`), and reports what is ready. If anything about your machine is unusual, the
agent is expected to adapt the toolkit to it rather than give up. Nothing launches or touches the
game during setup; live game operations happen only when you ask for a specific test, on Windows.

Any harness works: the toolkit is agent-agnostic. [AGENTS.md](AGENTS.md) is the single file every
harness reads; `CLAUDE.md` is only a thin auto-load shim for Claude Code, and any other harness that
looks for its own entry file can point it at `AGENTS.md` the same way. The toolkit needs a
terminal-capable coding agent on the machine, not a particular vendor.

## For a qualification run

Paste [WINDOWS-QUALIFY-PROMPT.md](WINDOWS-QUALIFY-PROMPT.md) into your agent on the Windows PC.
It follows [docs/WINDOWS-QUALIFICATION.md](docs/WINDOWS-QUALIFICATION.md), fixes what breaks,
and opens a pull request with redacted receipts. On Linux, run the two tiers separately:
`python tools/qualify.py --tier offline --output docs/receipts` then
`python tools/qualify.py --tier backends --output docs/receipts`; they write `linux-*` receipts.
The game tier is Windows-only.

## Pilots

Two acceptance tests gate 1.0: an unfamiliar user's agent installs and loads the example mod
([docs/PILOT-USER.md](docs/PILOT-USER.md)), and an unfamiliar development agent lands a change
([docs/PILOT-CONTRIBUTOR.md](docs/PILOT-CONTRIBUTOR.md)). Both use a different agent harness than
the one that built the toolkit.

## Knowledge and playbooks

[docs/knowledge/](docs/knowledge/README.md) holds the T6 and Plutonium facts an agent needs before
building (client layout, fastfiles, scripts, engine limits, foundations, crashes); the project's
words are defined once in [CONTEXT.md](CONTEXT.md).
[docs/playbooks/](docs/playbooks/README.md) holds finite recipes for the common tasks: first build,
add a script, port a feature, four preflights, diagnose a crash, compose a pack, package and install.
[docs/MODULES.md](docs/MODULES.md) specifies the module declaration and composition recipe that
let an agent compose several mods, from local directories or fetched repositories, into one pack;
[docs/REGISTRY.md](docs/REGISTRY.md) specifies the registry file that lists them by name at exact
commits, with `pat registry` and `pat module fetch`. `examples/registry.json` lists the examples.
[docs/TRACK-RECORD.md](docs/TRACK-RECORD.md) records what that workflow has produced, and the
workflows that went beyond the packaged routes.

## Benchmark

[docs/BENCHMARK.md](docs/BENCHMARK.md): four repeatable offline modding tasks scored only from
receipts, to compare models and harnesses driving the toolkit. It gates nothing.

## For contributors and their agents

Read [CONTRIBUTING.md](CONTRIBUTING.md), then [AGENTS.md](AGENTS.md). Development agents get
architecture, extension recipes and the review checklist in [docs/contributors/](docs/contributors/).
Unit tests run on any platform:

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
python tools/private_scan.py
python tools/release_check.py
```

## Where things live

| Path | Contents |
| --- | --- |
| `src/plutonium_agent_toolkit/core/` | Errors, JSON envelope, config, receipts, platform gate, route registry |
| `src/plutonium_agent_toolkit/dev/` | Backend pins and setup; development routes |
| `src/plutonium_agent_toolkit/game/` | Game control routes |
| `src/plutonium_agent_toolkit/agent/` | Agent-host routes: T3 Code as a thread dispatcher |
| `src/plutonium_agent_toolkit/testing/` | Capture and test routes |
| `examples/hello-zm/` | The bundled first-run mod used by the qualification loop |
| `examples/hello-pack/` | The smallest composition: both example modules on the stock game as one `mod.ff`; formats in `docs/MODULES.md` |
| `examples/registry.json` | A registry listing the examples at an exact commit; format in `docs/REGISTRY.md` |
| `docs/` | User guide, packaged route qualification, contributor docs, engineering history |
| `docs/TRACK-RECORD.md`, `docs/track-record.json` | Generated track record: accepted modules by category, milestones with the scope of each verdict, workflows completed without a packaged route |
| `CONTEXT.md` | The vocabulary every doc, receipt and skill uses, one definition each |
| `docs/knowledge/` | Facts an agent reads once per task: client layout, fastfiles, scripts, contracts, foundations, crashes, limits |
| `docs/playbooks/` | Finite recipes with the receipt field that proves each step, including four preflight gate lists |
| `skills/` | Installable agent skills: the `plutonium-agent-toolkit` umbrella skill; `pat-help` routes; `pat-grill`, `pat-build`, `pat-port`, `pat-diagnose`, `pat-review` do the work |
| `vendor/matt-pocock/` | Unmodified upstream skills (MIT) that three of ours adapt; pinned by commit and hash |
| `tools/` | Qualification runner, backends-page generator, private-material scanner and release check used by CI |

## License

Apache-2.0 for the authored code and documentation in this repository. Call of Duty, Plutonium
and every backend program remain the property of their respective owners.
