# Getting started

This guide is written for your agent to follow. You can read along.

The development (build) tools run on any OS: Windows, Linux or macOS. Game control and capture are
native-Windows-only, because their transport is the Win32 console.

This toolkit is meant to be adapted to your machine. Where a default here does not match your setup,
your agent should configure or edit the toolkit to fit, not stop. It reads the state of your machine
and makes it work. See [FOR-AGENTS.md](FOR-AGENTS.md).

## Requirements

To build and package mods (any OS):

- Python 3.11 or newer, installed for your user.
- A coding agent with local terminal and file access.
- Each backend you use (OpenAssetTools and gsc-tool at minimum). Where a pinned download exists for
  your OS, `pat dev setup` fetches it; otherwise install the tool and point `PAT_BACKEND_<NAME>` at
  it. Internet access is needed only for pinned downloads.

To control a running game (Windows only):

- Windows 11 x64 with Plutonium installed and Black Ops II Zombies launched at least once.
- A GPU hardware video encoder (NVENC, AMF or Quick Sync) if you later use recording. Not needed for
  building mods.

## Install

```sh
git clone https://github.com/SickoHours/plutonium-agent-toolkit
cd plutonium-agent-toolkit
python -m pip install --user -e .
pat version --json
```

If `pat` is not found, use `python -m plutonium_agent_toolkit` or add your user Scripts/bin directory
to PATH. The agent can locate it with `python -m site --user-base`.

## Configure

The build tools do not need the game configured. Set `PAT_HOME` to choose where backends and
evidence live, and use `PAT_BACKEND_<NAME>` to point at a tool you already have:

```sh
export PAT_BACKEND_GSC=/absolute/path/to/gsc-tool
export PAT_BACKEND_LINKER=/absolute/path/to/Linker
export PAT_BACKEND_UNLINKER=/absolute/path/to/Unlinker
pat doctor --json
```

On Windows, to use game control, also save your storage path and launcher:

```powershell
pat configure --plutonium-storage-t6 "%LOCALAPPDATA%\Plutonium\storage\t6" --plutonium-launcher "C:\path\to\plutonium.exe"
```

`doctor` reports development-tool readiness separately from whether game control is supported on this
host. Configuration lives under `PAT_HOME` (or the per-user config directory); `PAT_HOME` relocates
everything.

## Install backends

```sh
pat dev setup --plan --json     # shows, per backend, the pinned download for your OS or override-required
pat dev setup --json            # downloads the pinned builds that exist for your OS
```

Setup downloads over HTTPS, verifies SHA-256, extracts into the backends directory and writes a
receipt per program. Rerunning verifies existing installs and refuses to overwrite a changed tree.
Where a backend has no pinned build for your OS, setup reports it as `override-required`: supply the
tool and set `PAT_BACKEND_<NAME>`. No vendor installer runs, PATH and registry are untouched, and the
game is never started.

## What next

Read [SUPPORT.md](SUPPORT.md) for what each route has earned. The development routes have native
Windows receipts and also run on Linux and macOS; `examples/hello-zm` has been built and byte-compared
natively on Linux. Game routes are implemented and not yet qualified. The first thing to ask your
agent for is the `examples/hello-zm` build:

```sh
pat project build examples/hello-zm/project.json --output ../jobs/hello-001 --json
pat game install-mod ../jobs/hello-001/packages/mod.ff hello_zm --json   # file copy; any OS
```

Live game operations (`launch`, `select-mod`, `load-map`, restarts, `quit`) run on Windows and always
need your explicit go-ahead for the specific test. Screen recording and the autonomous test runner are
deferred to a later release.

## Troubleshooting

| Result | What to do |
| --- | --- |
| `unsupported_platform` | You ran a game-control or capture route off Windows. The build tools run anywhere; game control needs a native Windows host, not WSL or Wine |
| `backend_unavailable` | The backend is not installed for this OS. Run `pat dev setup --only <id>`, or set `PAT_BACKEND_<NAME>` to an installed binary |
| `config_missing` | Run the `pat configure` command the hint names |
| `hash_mismatch` on setup | The download did not match the pin. The failed file is kept. Do not edit the pin; open an issue with the URL and the hash you received |
| `busy` on setup | Another setup is running, or an interrupted one left `setup.lock` in the backends directory. Inspect before removing |
| `backend_failed: installed files differ` | Someone changed an installed program. The toolkit preserves it. Move it aside and rerun setup if you want the pinned version |
| `not_implemented` | The route is a contract in this version. `docs/SUPPORT.md` names the owner and status |

Report problems with `pat version --json`, the full JSON output, the exit status and your OS and
version. Redact your username if you prefer.
