# Plutonium Agent Toolkit

**Agent-native tools for building, controlling and testing Plutonium T6 Zombies mods.**
You describe the result. Your coding agent installs the tools, builds the mod, loads the game and
shows you the evidence. If your setup is unusual, the agent adapts the toolkit to it.

**This is meant to be modified.** It is open source and malleable by design. The person using it
already has a coding agent; the agent reads the docs, configures the toolkit to that machine, and
edits or extends it when the defaults do not fit. Every doc here is written for that agent to read.
See [AGENTS.md](AGENTS.md) and [docs/FOR-AGENTS.md](docs/FOR-AGENTS.md).

> **Status: public beta. The development (file) tools run on Windows and Linux; game control is
> Windows-only.** The build toolchain is `available` with native receipts from Windows 11 and from
> Arch Linux (Omarchy): `dev setup`, `gsc compile`, `ff inspect|extract`,
> `project plan|build|verify`, and discovery/`configure`/`doctor`. You can build and package a T6
> Zombies mod with the real tools on either OS. Backends are pinned per platform (gsc-tool,
> OpenAssetTools, FFmpeg and Blender on both; CoDLuaDecompiler and the extraction GUIs on Windows
> only); where a platform has no pinned download, supply the tool yourself and point the toolkit at
> it with `PAT_BACKEND_<NAME>`. macOS is untested, has no pinned backends and is not claimed. Game
> control uses the Win32 console, so it needs a native Windows host; it is `implemented` and not yet
> qualified ([issue #8](https://github.com/SickoHours/plutonium-agent-toolkit/issues/8)), so no
> `game` route has earned level `game`. Screen recording and the autonomous test runner are
> deferred. Read [docs/SUPPORT.md](docs/SUPPORT.md) before trusting any capability claim, and
> [CHANGELOG.md](CHANGELOG.md) for what each version actually ships.

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
| Development (Windows, Linux) | `dev`, `gsc`, `ff`, `project`, `model`, `audio`, `image`, `lua`, `weapon` | Scripts, fastfiles, models, media and saved-asset recipes through pinned upstream backends. Verified on Windows 11 and Arch Linux (Omarchy); macOS untested |
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
add a script, port a feature, four preflights, diagnose a crash, package and install.

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
| `src/plutonium_agent_toolkit/testing/` | Capture and test routes |
| `examples/hello-zm/` | The bundled first-run mod used by the qualification loop |
| `docs/` | User guide, support matrix, contributor docs, engineering history |
| `CONTEXT.md` | The vocabulary every doc, receipt and skill uses, one definition each |
| `docs/knowledge/` | Facts an agent reads once per task: client layout, fastfiles, scripts, contracts, foundations, crashes, limits |
| `docs/playbooks/` | Finite recipes with the receipt field that proves each step, including four preflight gate lists |
| `skills/` | Installable agent skills: the `plutonium-agent-toolkit` umbrella skill; `pat-help` routes; `pat-grill`, `pat-build`, `pat-port`, `pat-diagnose`, `pat-review` do the work |
| `vendor/matt-pocock/` | Unmodified upstream skills (MIT) that three of ours adapt; pinned by commit and hash |
| `tools/` | Qualification runner, backends-page generator, private-material scanner and release check used by CI |

## License

Apache-2.0 for the authored code and documentation in this repository. Call of Duty, Plutonium
and every backend program remain the property of their respective owners.
