# Getting started (Windows 11 x64)

This guide is written for your agent to follow. You can read along.

This toolkit is meant to be adapted to your machine. Where a default here does not match your
setup, your agent should configure or edit the toolkit to fit, not stop. It reads the state of
your machine and makes it work. See [FOR-AGENTS.md](FOR-AGENTS.md).

## Requirements

- Windows 11 x64 with Plutonium installed and Black Ops II Zombies launched at least once.
- Python 3.11 or newer from python.org, installed for your user.
- A coding agent with local terminal and file access on the same PC and user session.
- Internet access for the first setup (backend downloads, several hundred MB if Blender is chosen).
- A GPU with a hardware video encoder (NVENC, AMF or Quick Sync) for recording. Not needed for
  building mods.

## Install

```powershell
git clone https://github.com/SickoHours/plutonium-agent-toolkit
cd plutonium-agent-toolkit
python -m pip install --user -e .
pat version --json
```

If `pat` is not found, use `python -m plutonium_agent_toolkit` or add your user Scripts directory
to PATH. The agent can locate it with `python -m site --user-base`.

## Configure

```powershell
pat configure --plutonium-storage-t6 "%LOCALAPPDATA%\Plutonium\storage\t6" --plutonium-launcher "C:\path\to\plutonium.exe"
pat doctor --json
```

Configuration lives in `%LOCALAPPDATA%\PlutoniumAgentToolkit\config.json`. Set `PAT_HOME` to
relocate everything, including backends and evidence.

## Install backends

```powershell
pat dev setup --plan --json     # shows URLs, sizes and hashes; downloads nothing
pat dev setup --json            # required backends: OpenAssetTools and gsc-tool
pat dev setup --only blender cast ffmpeg --json   # optional model and media tools
```

Setup downloads over HTTPS, verifies SHA-256, extracts into the backends directory and writes a
receipt per program. Rerunning verifies existing installs and refuses to overwrite a changed tree.
No vendor installer runs, PATH and registry are untouched, and the game is never started.

## What next

Read [SUPPORT.md](SUPPORT.md) for what each route has earned. Development and game routes are
implemented and tested offline; none has a native Windows receipt yet, which is exactly what
[WINDOWS-QUALIFICATION.md](WINDOWS-QUALIFICATION.md) produces. The first thing to ask your agent
for is the `examples/hello-zm` build:

```powershell
pat project build examples\hello-zm\project.json --output ..\jobs\hello-001 --json
pat game install-mod ..\jobs\hello-001\packages\mod.ff hello_zm --json
```

Game operations (`launch`, `select-mod`, `load-map`, restarts, `quit`) always need your explicit
go-ahead for the specific test. Screen recording and the autonomous test runner are deferred to a
later release.

## Troubleshooting

| Result | What to do |
| --- | --- |
| `unsupported_platform` | Use a native Windows terminal, not WSL, Wine or a remote Linux shell |
| `config_missing` | Run the `pat configure` command the hint names |
| `hash_mismatch` on setup | The download did not match the pin. The failed file is kept. Do not edit the pin; open an issue with the URL and the hash you received |
| `busy` on setup | Another setup is running, or an interrupted one left `setup.lock` in the backends directory. Inspect before removing |
| `backend_failed: installed files differ` | Someone changed an installed program. The toolkit preserves it. Move it aside and rerun setup if you want the pinned version |
| `not_implemented` | The route is a contract in this version. `docs/SUPPORT.md` names the owner and status |

Report problems with `pat version --json`, the full JSON output, the exit status and your Windows
version. Redact your username if you prefer.
