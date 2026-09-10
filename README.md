# Plutonium Agent Toolkit

**Agent-native tools for building, controlling and testing Plutonium T6 Zombies mods on Windows.**
You describe the result. Your coding agent installs the tools, builds the mod, loads the game,
records the test and shows you the evidence.

> **Status: public pre-alpha.** Contracts and the Windows foundation are committed. No route has
> passed native Windows qualification yet. The repository is public so contributors can follow
> along from the first commit; do not mistake visibility for readiness. Read [docs/SUPPORT.md](docs/SUPPORT.md) before trusting
> any capability claim, and [CHANGELOG.md](CHANGELOG.md) for what each version actually ships.

## What "agent-native" means here

| Principle | How the toolkit delivers it |
| --- | --- |
| Agents discover, humans describe | `pat manifest --json` and `pat describe <group> <action> --json` are inert and complete. No hidden commands. |
| Every result is machine-checkable | One JSON document per invocation, stable `error_code` strings, exit statuses 0/1/2/130. |
| Work leaves receipts | Each job creates a new output directory with `receipt.json`: argv, input hashes, output hashes, logs. Failures keep their receipts. |
| Uncertainty is never replayed | Game commands report admitted, delivered, rejected or uncertain. An uncertain outcome is inspected, not retried. |
| Instructions travel with the code | `AGENTS.md`, `CLAUDE.md`, an installable skill and `SETUP-PROMPT.md` are versioned with the release they describe. |
| Truth over marketing | Offline verified, installed, launched, playable, captured and player-accepted are separate statements. `docs/SUPPORT.md` says which one each route has earned. |

## Components

| Component | Group(s) | Purpose |
| --- | --- | --- |
| Development | `dev`, `gsc`, `ff`, `project`, `model`, `audio`, `image`, `lua`, `weapon` | Scripts, fastfiles, models, media and saved-asset recipes through pinned upstream backends |
| Game control | `game` | Launch T6 Zombies, select mods, load maps, verify loads through the external console |
| Testing | `capture`, `test` | Record the game window with game-only audio, screenshots, markers, finite test recipes, sanitized reports |

Backends (OpenAssetTools, gsc-tool, Blender, Cast, FFmpeg and others) are downloaded from their
upstream releases at setup and verified by SHA-256. This repository redistributes none of them.
See [NOTICE](NOTICE) for licenses.

## For users: hand this to your agent

1. Install Python 3.11 or newer on Windows 11 x64 from python.org.
2. Clone or download this repository.
3. Paste [SETUP-PROMPT.md](SETUP-PROMPT.md) into your agent, working in the repository folder.

The agent installs the toolkit for your user, configures your Plutonium storage path, downloads
the required backends and reports what is ready. Nothing launches or touches the game during
setup. Live game operations happen only when you ask for a specific test.

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
| `skills/` | Installable agent skill |
| `tools/` | Private-material scanner and release check used by CI |

## License

Apache-2.0 for the authored code and documentation in this repository. Call of Duty, Plutonium
and every backend program remain the property of their respective owners.
