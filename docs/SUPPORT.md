# Support matrix for `0.1.0b1`

This file is the single source of truth for what each route has earned. Update it in the same
pull request that changes a route. `tools/release_check.py` verifies the version in the first line.

## Evidence levels

| Level | Meaning |
| --- | --- |
| contract | Route is registered with name, effect and owner. Answers `not_implemented`. |
| deferred | Registered contract, explicitly excluded from this release. Answers `not_implemented`. |
| offline | Implemented; unit tests pass with synthetic fixtures and fake backends on any platform. The file tools execute on Windows and Linux; game control and capture execute on native Windows only. No native receipt. |
| native | Ran on a real host of the OS named in the receipt, not Wine, WSL or a CI runner, with a sanitized receipt linked below. Receipts exist for native Windows 11 x64 and for native Arch Linux (Omarchy); each row names which. |
| game | Produced a verified effect in a running Plutonium T6 Zombies instance with a fresh engine reply and a decoded non-black frame where applicable. |
| accepted | A human played the result and recorded a scoped verdict. |

A level applies only to the exact scope in the receipt. "Loaded Town once" is not "loads every map".

## Platform

The development (file) tools run on Windows and Linux. Verified hosts: Windows 11 x64 and Arch
Linux (Omarchy). macOS is untested and has no pinned backends; it is not claimed. Game control and
capture use the Win32 console and run on native Windows only.

Backends are pinned per platform in `src/plutonium_agent_toolkit/dev/backends.json`: gsc-tool,
OpenAssetTools, FFmpeg and Blender on Windows and Linux; CoDLuaDecompiler, Greyhound, Husky and C2M
on Windows only; the Cast add-on anywhere. Where a platform has no pin, `dev setup` reports
`override-required` and `PAT_BACKEND_<NAME>` supplies the tool.

| Item | Status |
| --- | --- |
| Windows 11 x64, native Python 3.11+ | Tiers 1 (offline) and 2 (real backends) passed on Windows 11 25H2, build 26200, Python 3.12.0: [receipts/0.1.0a1/tier1-offline.json](receipts/0.1.0a1/tier1-offline.json), [receipts/0.1.0a1/tier2-backends.json](receipts/0.1.0a1/tier2-backends.json). Tier 3 (running game) attempted, [receipts/0.1.0a1/tier3-game.json](receipts/0.1.0a1/tier3-game.json): `launch` and console attach work, but a console-started match is dropped by the client right after it loads (issue #8; see the `game` rows). No `game` route earned level `game`. |
| Arch Linux (Omarchy), native Python 3.11+ | Tiers 1 (offline) and 2 (real backends, with `--media`) passed on Omarchy 4.0.2 (Arch), Python 3.14.7: [receipts/0.1.0b1/linux-tier1-offline.json](receipts/0.1.0b1/linux-tier1-offline.json), [receipts/0.1.0b1/linux-tier2-backends.json](receipts/0.1.0b1/linux-tier2-backends.json). Real gsc-tool 1.4.10, OpenAssetTools 0.33.0, FFmpeg 9.0 and Blender 5.2.1 with Cast 2.00 were downloaded, verified and run; `examples/hello-zm` produced a `mod.ff` byte-identical to the Windows build (same SHA-256). Game control and capture are not available: their transport is the Win32 console. |
| macOS | untested; no pinned downloads; not claimed. The file tools may run with every backend supplied through `PAT_BACKEND_<NAME>`, and `doctor` and `dev setup` say so in a `note`; no receipt exists and none is planned. |
| Windows 10 | untested |
| Windows on ARM64 | unsupported |
| Wine / Proton / WSL | Not used for qualification and never counted as native. Run the development tools on Linux directly instead; game control needs a real Windows host. |

## Routes

| Route | Effect | Level | Owner | Receipt / notes |
| --- | --- | --- | --- | --- |
| `version`, `manifest`, `describe` | inert | native | core | Windows: [receipts/0.1.0a1/tier1-offline.json](receipts/0.1.0a1/tier1-offline.json); Linux: [receipts/0.1.0b1/linux-tier1-offline.json](receipts/0.1.0b1/linux-tier1-offline.json); steps `version`, `manifest`, `describe game load-map`; tests/test_cli.py |
| `doctor` | inert | native | core | presence and configuration only; Windows: [receipts/0.1.0a1/tier1-offline.json](receipts/0.1.0a1/tier1-offline.json) step `doctor before configure`, [receipts/0.1.0a1/tier2-backends.json](receipts/0.1.0a1/tier2-backends.json) step `doctor after setup`; Linux: same steps in [receipts/0.1.0b1/linux-tier1-offline.json](receipts/0.1.0b1/linux-tier1-offline.json) and [receipts/0.1.0b1/linux-tier2-backends.json](receipts/0.1.0b1/linux-tier2-backends.json) |
| `configure` | writes-config | native | core | absolute paths, unknown keys rejected; step `configure fake storage` (isolated `PAT_HOME`, fake storage path) in [receipts/0.1.0a1/tier1-offline.json](receipts/0.1.0a1/tier1-offline.json) and [receipts/0.1.0b1/linux-tier1-offline.json](receipts/0.1.0b1/linux-tier1-offline.json) |
| `dev backends` | inert | offline | core | pins validated |
| `dev setup` | downloads-backends | native | core | Windows: `--only gsc oat`, gsc-tool 1.4.10 and OpenAssetTools 0.33.0 downloaded over HTTPS, SHA-256 verified, extracted, and re-verified on rerun ([receipts/0.1.0a1/tier2-backends.json](receipts/0.1.0a1/tier2-backends.json) steps `dev setup gsc oat`, `dev setup rerun verifies`); `--plan` in [receipts/0.1.0a1/tier1-offline.json](receipts/0.1.0a1/tier1-offline.json). Linux: the same two plus `--only ffmpeg blender cast` (FFmpeg 9.0 tar.xz, Blender 5.2.1 tar.xz with its library symlinks written as copies, Cast 2.00 zip) in [receipts/0.1.0b1/linux-tier2-backends.json](receipts/0.1.0b1/linux-tier2-backends.json) steps `dev setup gsc oat`, `dev setup rerun verifies`, `dev setup ffmpeg blender cast`. Archive safety tested with synthetic zips and tars. **CoDLuaDecompiler, Greyhound, Husky and C2M have Windows pins that no native run has exercised yet, and no Linux pin exists for them** |
| `gsc compile` | writes-output | native | thread-1 | real gsc-tool 1.4.10: minimal script compiles, broken script fails with `backend_failed` exit 1, and every hello-zm build compile; steps `gsc compile minimal script`, `gsc compile broken script fails structurally`, `project build hello-zm` in [receipts/0.1.0a1/tier2-backends.json](receipts/0.1.0a1/tier2-backends.json) (Windows) and [receipts/0.1.0b1/linux-tier2-backends.json](receipts/0.1.0b1/linux-tier2-backends.json) (Linux). Fake covers log-error-with-exit-zero, crash, missing input |
| `gsc decompile` | writes-output | offline | thread-1 | fake gsc-tool only; **no native run** |
| `ff inspect`, `ff extract` | writes-output | native | thread-1 | real OpenAssetTools 0.33.0 Unlinker on the hello-zm `mod.ff`; steps `ff inspect mod.ff`, `ff extract rawfiles` in [receipts/0.1.0a1/tier2-backends.json](receipts/0.1.0a1/tier2-backends.json) (Windows) and [receipts/0.1.0b1/linux-tier2-backends.json](receipts/0.1.0b1/linux-tier2-backends.json) (Linux) |
| `ff link` | writes-output | offline | thread-1 | Linker plus Unlinker readback ran natively inside `project build` on both hosts ([receipts/0.1.0a1/tier2-backends.json](receipts/0.1.0a1/tier2-backends.json), [receipts/0.1.0b1/linux-tier2-backends.json](receipts/0.1.0b1/linux-tier2-backends.json) step `project build hello-zm`), but **the standalone route did not run** |
| `project plan/build/verify` | writes-output | native | thread-1 | `examples/hello-zm` with real gsc-tool and OpenAssetTools: compile, stage, link as zone `mod` so the output is a readable `packages/mod.ff`, read back, byte-compare one rawfile, verify with `--inputs`; steps `project plan hello-zm`, `project build hello-zm`, `project verify --inputs` in [receipts/0.1.0a1/tier2-backends.json](receipts/0.1.0a1/tier2-backends.json) (Windows) and [receipts/0.1.0b1/linux-tier2-backends.json](receipts/0.1.0b1/linux-tier2-backends.json) (Linux; the `mod.ff` SHA-256 in both receipts' notes is identical). `plan` and the `output_exists` refusal also in [receipts/0.1.0a1/tier1-offline.json](receipts/0.1.0a1/tier1-offline.json) and [receipts/0.1.0b1/linux-tier1-offline.json](receipts/0.1.0b1/linux-tier1-offline.json). One script, no assets, no loads |
| `project init` | writes-output | offline | thread-1 | unit tests only; **no native run** |
| `model inspect`, `model convert` | writes-output | native | thread-1 | Linux only: real Blender 5.2.1 with the bundled worker and Cast 2.00 on a synthetic OBJ cube, `inspect` and `convert --format cast` ([receipts/0.1.0b1/linux-tier2-backends.json](receipts/0.1.0b1/linux-tier2-backends.json) steps `model inspect cube.obj`, `model convert cube.obj to cast`). No rig, no animation, no Cast input; in-game appearance untested. **Not run natively on Windows** |
| `model transform/rename-bones/retime/preview` | writes-output | offline | thread-1 | background Blender with the bundled worker; fake Blender in tests. **No native run** |
| `audio inspect/convert` | writes-output | native | thread-1 | Linux only: real FFmpeg 9.0 ffprobe/ffmpeg on a generated 440 Hz stereo WAV, `inspect` and `convert --format wav --rate 48000 --channels 1` with the stream parameters verified by ffprobe ([receipts/0.1.0b1/linux-tier2-backends.json](receipts/0.1.0b1/linux-tier2-backends.json) steps `audio inspect tone.wav`, `audio convert tone.wav 48 kHz mono`). In-game playback untested. **Not run natively on Windows.** Fake ffmpeg/ffprobe cover parameter mismatch and no-stream input |
| `image convert` | writes-output | offline | thread-1 | fake ImageConverter |
| `lua decompile` | writes-output | offline | thread-1 | fake CoDLuaDecompiler |
| `weapon catalog/plan` | writes-output | offline | thread-1 | synthetic sealed donor: altered/short pages, duplicates, identity mismatch, stale library, recipe rules. No live BO3 capture, no converter. `docs/WEAPONS.md` |
| `game install-mod` | writes-output | offline | thread-2 | file copy with hash check; refuses overwrite without `--replace`; moves old folder aside |
| `game status`, `game mods` | inert | offline | thread-2 | `status` ran natively and returned the game window and foreground correctly ([receipts/0.1.0a1/tier3-game.json](receipts/0.1.0a1/tier3-game.json)); `mods` ran natively against real storage and an empty fake storage. Both stay `offline`: inert routes do not earn `game`, and Tier 3 as a whole did not pass. |
| `game info`, `game check-load` | query-engine | offline | thread-2 | `info` attached to the live external console (Windows Terminal host) and returned fresh dvar state natively ([receipts/0.1.0a1/tier3-game.json](receipts/0.1.0a1/tier3-game.json)). `check-load` returned `delivery_uncertain` when run while the map was still loading, and its 128 KiB log-tail bound was too small for a real load (fixed to 4 MiB this PR). Neither earned `game`. |
| `game launch` | changes-game | offline | thread-2 | ran natively ([receipts/0.1.0a1/tier3-game.json](receipts/0.1.0a1/tier3-game.json)): the `plutonium://play/t6zm` handler started the game with no launcher login/update prompt, and `focus_preserved` was **false** (the console and game window took focus about 5 s after the request). Both native questions answered; stays `offline` because Tier 3 did not reach a playable spawn. |
| `game select-mod/reload-mod/load-map/fast-restart/map-restart/disconnect/quit` | changes-game | offline | thread-2 | `load-map town` ran natively ([receipts/0.1.0a1/tier3-game.json](receipts/0.1.0a1/tier3-game.json)) and set the UI/gametype dvars, but the match does not survive: the level loads (Town gump loaded) and the client then drops it with `SV_Shutdown: hostquit`, returning to the menu, with or without a mod. Menu-started matches on the same install play to completion (`EXE_MATCHENDED`). The gametype configs exec at frontend init in both paths and the weapon and `common_zm` not-found lines are identical in the playable session, so neither is the cause; the console `map` path differs in connecting the local client through the mod-download check where the menu uses its party lobby. Root cause open in issue #8; no allowlist change made. `select-mod zm_gobblegums` and `select-mod base` ran natively with verified `fs_game` changes, and `quit` stopped the client through the engine's own `quit` (same receipt); restarts and `disconnect` were not exercised. All stay `offline`: a `game` flip needs a playable spawn (issue #8). |
| `capture *`, `test *` | mixed | **deferred** | thread-2 | Not in this release by product decision (2026-09-10). Contracts stay registered; every route answers `not_implemented`. Research notes for a later release are in the project history. |

## Explicitly out of scope for this release

- Screen recording, screenshots and the autonomous test runner (`capture`, `test`). Deferred.
- Native gameplay input (fire, ADS, reload, Use). Refused rather than simulated.
- The in-game typed feature receiver.
- Greyhound, Husky and C2M live extraction through the toolkit. The GUIs can be downloaded; their
  use is manual.
- BO3 live asset capture and generic weapon conversion.
- Multiplayer, co-op, other Call of Duty titles, macOS (untested), Stream Deck, desktop GUIs, MCP wrapper.

## Release bars

The release program ships in halves. The development toolchain runs on Windows and Linux and is
native-verified on both; game control is Windows-only and follows once issue #8 is resolved; capture
and testing are a later release.

**`0.1.0-beta.1` (development tools)** requires Tiers 1 and 2 of
[WINDOWS-QUALIFICATION.md](WINDOWS-QUALIFICATION.md) passed on a native host with receipts under
`docs/receipts/`: install, `dev setup` downloading and verifying the real backends, and
`examples/hello-zm` built, read back and verified with `gsc compile`, `ff` and
`project plan|build|verify`. This is met: see the Tier 1 and Tier 2 receipts. The beta ships game
control as `implemented` and documents it as not yet qualified.

**Game-control beta** requires a native Tier 3 receipt reaching a human-observed playable Town with
the hello-zm line, through the toolkit. That is blocked on
[issue #8](https://github.com/SickoHours/plutonium-agent-toolkit/issues/8): a console-started match
is dropped by the client right after it loads. The likely resolution is that `load-map` operates
inside a running private match rather than cold-starting one; the retest and any doc or scope
change land before this bar is called met.

**`1.0.0`** additionally requires: the remaining dev routes (the other `model` actions, `image`,
`lua`, `weapon`) at level `native` and the `audio`/`model` routes native on Windows too; and frozen
JSON, exit-code and schema contracts. A pilot is simply a
different person's agent, on a harness that did not build the toolkit, using the repo and succeeding;
it is not a benchmark and there is no model-scoring gate. The contributor pilot
([PILOT-CONTRIBUTOR.md](PILOT-CONTRIBUTOR.md)) is the 1.0 quality check; the user pilot
([PILOT-USER.md](PILOT-USER.md)) is a soft, post-launch confidence check, not a hard gate. Capture
and testing are a separate later release. [BENCHMARK.md](BENCHMARK.md) scores repeatable offline
modding tasks from receipts to compare models and harnesses; it gates nothing.

## Release mechanics

`python tools/bump_version.py <version>` moves every version statement at once and promotes the
`Unreleased` changelog section. `python tools/release_check.py --tag v…` must pass. Pushing the
tag runs `.github/workflows/release.yml`: tests on Windows, release check against the tag, wheel
and sdist with SHA-256 sums, GitHub Release with the changelog section as notes. Pre-release
tags (`-alpha`, `-beta`, `-rc`) are marked pre-release automatically.
