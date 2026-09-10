# Windows qualification

This is the procedure that turns a route from `offline` to `native` or `game` in
[SUPPORT.md](SUPPORT.md). It runs on a native Windows 11 x64 machine with Plutonium installed.
An agent follows it; a human authorizes the game tier. The output is a pull request that adds
sanitized receipts under `docs/receipts/<version>/` and any fixes the run exposed.

Tiers 1 and 2 also run on Linux with the same tool (`python tools/qualify.py`), writing
`linux-tier1-offline.json` and `linux-tier2-backends.json`; add `--media` to Tier 2 to install
FFmpeg, Blender and Cast and run the `audio` and `model` routes on synthetic inputs. Tier 3 is
Windows-only. `tools/qualify_windows.py` still works and runs the same code.

Nothing here is optional and nothing here is a formality. The toolkit was written on Linux
against fake backends and a fake console. The first native run *will* find defects. Each one
is fixed in the same pull request with a regression test.

## Before you start

| Check | Command | Expected |
| --- | --- | --- |
| Native Windows Python 3.11+ | `python --version` | `Python 3.11` or newer, not WSL |
| Git and GitHub CLI authenticated | `gh auth status` | logged in as the repository owner |
| Plutonium installed | look for `plutonium.exe` and `%LOCALAPPDATA%\Plutonium\storage\t6` | both exist |
| Game launched once via the launcher | `storage\t6\main\console_zm.log` exists | the log exists |
| Nothing else touching the game | Task Manager | no other automation, no other agent |

Clone the repository, create the branch and install:

```powershell
git clone https://github.com/SickoHours/plutonium-agent-toolkit
cd plutonium-agent-toolkit
git switch -c qualify/windows-$(Get-Date -Format yyyy-MM-dd)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
$env:PAT_HOME = "$PWD\.qualify-home"      # keeps qualification state out of your real install
pat version --json
```

## Tier 1: offline (no downloads, no game)

```powershell
python tools/qualify_windows.py --tier offline --output docs/receipts
```

The script runs the unit tests, `manifest`, `describe`, `doctor`, `configure`, `dev setup --plan`
and the `project plan` of `examples/hello-zm`, then writes `tier1-offline.json`. Everything in
this tier must pass. A failure here is a toolkit bug on native Windows Python; fix it.

Commit: `git add docs/receipts && git commit -m "qualify(windows): tier 1 offline"`.

## Tier 2: backends (downloads, real gsc-tool and OpenAssetTools, no game)

```powershell
python tools/qualify_windows.py --tier backends --output docs/receipts
```

The script runs `dev setup --only gsc oat` (about 10 MB), `doctor`, then builds
`examples/hello-zm` with the real compiler and linker, reads it back and verifies the receipt with
`--inputs`. It then plans and builds `examples/hello-pack` (`module plan`, `module build`), verifies
that receipt and inspects the pack's `mod.ff`. It also runs `gsc compile` on a deliberately broken
script and confirms the error surfaces. It writes `tier2-backends.json` including the SHA-256 of
both produced `mod.ff` files.

If the real gsc-tool or Linker behaves differently from the fakes (argument order, output
directory layout, exit status on error), fix the adapter in `src/plutonium_agent_toolkit/dev/`
and add the real behaviour to `tests/fakes/` so the offline tests match reality.

Commit the receipt and fixes.

## Tier 3: game (touches the running Plutonium client)

Every command in this tier needs the human's explicit go-ahead in the chat, one command at a
time. The script does not automate this tier; the agent runs each command and the script
collects the outputs afterwards.

Configure paths and write the begin marker first (offline). The marker is how the collector
later tells this run's state files from stale ones:

```powershell
pat configure --plutonium-storage-t6 "$env:LOCALAPPDATA\Plutonium\storage\t6" --plutonium-launcher "C:\path\to\plutonium.exe" --json
pat game mods --json
python tools/qualify_windows.py --tier game --begin
```

Then, with the game **not** running, ask for permission and run:

| Step | Command | What proves it |
| --- | --- | --- |
| 3a | `pat game status --json` | `windows` is empty, `foreground` is your terminal |
| 3b | `pat game launch --json` | `launch_requested: true`. Watch what happens on screen. Record whether the launcher showed a login or update prompt, whether the game window took focus, and what `focus_preserved` reported. If `config_missing` names the URI handler, that is a finding: record it and launch from the Plutonium launcher by hand instead. |
| 3c | wait for the main menu, then `pat game status --json` | exactly one window, title `Plutonium T6 Zombies` or `Plutonium T6 Zombies (rNNNN)` |
| 3d | `pat game info --json` | fresh `state` with `mapname`, `fs_game`, `sv_running` |
| 3e | `pat game load-map town --json` | `load_id` returned; the game loads Town |
| 3f | `pat game check-load <load_id> --json` | `verified: true`, `state_matches: true`, logs `checked: true`. Let the load settle first: the check's engine query waits 8 s and the engine does not answer mid-load |
| 3g | look at the game | you or the agent (if it can see the screen) confirm a playable spawn in Town |
| 3h | `pat game install-mod "$env:PAT_HOME\qualify\hello_zm\mod.ff" hello_zm --json` (Tier 2 staged it there and printed the exact command), then `pat game select-mod hello_zm --json` | install receipt with `sha256`; then `load_id`; `fs_game` becomes `mods/hello_zm` |
| 3i | `pat game load-map town --json` then `pat game check-load <load_id> --json` with the new `load_id` | verified; the green hello-zm line appears on screen after spawn |
| 3j | `pat game fast-restart --json` then `pat game check-load <load_id> --json` | `load_id`; match restarts; check verified |
| 3k | `pat game disconnect --json` | `sv_running: "0"` |
| 3l | `pat game select-mod base --json` | `fs_game: ""` |
| 3m | `pat game quit --json` | `stopped: true`; the game exits cleanly |

After the run:

```powershell
python tools/qualify_windows.py --tier game --output docs/receipts --collect
```

The script reads the toolkit's state files (`last-launch.json`, `last-load.json`,
`last-load-check.json`, `last-result.json`, the `hello_zm` install receipt), accepts only files
written after the begin marker, checks that each records success (`verified: true`,
`engine-state-verified`, `launch_requested` and `game_detected`), redacts paths and writes
`tier3-game.json`. Then edit `human_observations` in that file with what the script cannot know:
did the launcher prompt, did focus move, was the spawn playable, did the hello-zm line appear.
A Tier 3 receipt with `null` human observations does not qualify any route at level `game`.

## Common native failures and what they mean

| Symptom | Likely cause | Where to fix |
| --- | --- | --- |
| `game_not_found` with the game open | Title regex does not match this Plutonium build, or the agent is elevated while the game is not | `game/native.py` `TITLE`; run the agent unelevated |
| `Cannot attach to the game's external console` | Console host is not the classic conhost, or the console window was closed | `docs/GAME-CONTROL.md` troubleshooting; do not change terminal defaults |
| `busy: console is busy or contains typed text` forever | Prompt regex `Plutonium r\d+ > ` does not match this build's prompt | `game/native.py` `PROMPT` |
| `delivery_uncertain: Fresh engine reply timed out` | Dvar output format changed, or console buffer wider than expected | `game/engine.py` parse patterns |
| `config_missing` from `launch` | `plutonium://` handler not registered | finding, not a fix: record it |
| `backend_failed` from real gsc-tool with exit 0 | Error line format differs from the fake | `dev/scripts.py` `ERROR` pattern and `tests/fakes/fake_gsc.py` |
| `Rawfile did not round-trip` | Unlinker output layout differs | `dev/projects.py` readback path |
| `load-map` reports `sv_running` `1`, then the client returns to the main menu (`SV_Shutdown: hostquit` right after the Town gump loads) | Open. The console `map` path connects the local client through the mod-download check where the menu uses its party lobby. The `*_zm` weapon and `common_zm` ipak not-found lines are noise: identical in a playable menu-started match | Issue #8. Diff the console log of a menu start against the toolkit load before changing anything |

## Flipping routes to `available`

For each route with a passing receipt in Tier 2 or Tier 3, change its `status` in the owning
`routes.py` from `"implemented"` to `"available"`, update its row in `docs/SUPPORT.md` to level
`native` (Tier 2) or `game` (Tier 3) with a link to the receipt file, and add a line under
`## [Unreleased]` in `CHANGELOG.md`. Routes that failed stay `implemented` with the failure
described in `docs/SUPPORT.md`.

## Open the pull request

```powershell
git add -A
git commit -m "qualify(windows): native receipts for <what passed>"
git push -u origin HEAD
gh pr create --fill
```

Use the pull request template. Under "Native Windows receipt" link the three receipt files.
Under "Not verified" list every step that did not run or did not pass. The automated reviewer
will comment; fix what is real, reply to each thread, push again.
