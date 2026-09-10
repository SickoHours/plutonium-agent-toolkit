# Support matrix for `0.1.0a1`

This file is the single source of truth for what each route has earned. Update it in the same
pull request that changes a route. `tools/release_check.py` verifies the version in the first line.

## Evidence levels

| Level | Meaning |
| --- | --- |
| contract | Route is registered with name, effect and owner. Answers `not_implemented`. |
| deferred | Registered contract, explicitly excluded from this release. Answers `not_implemented`. |
| offline | Implemented; unit tests pass with synthetic fixtures and fake backends on any platform. Executes on Windows but has no native receipt. |
| native | Ran on a native Windows 11 x64 host with a sanitized receipt linked below. Wine, WSL and CI runners do not count. |
| game | Produced a verified effect in a running Plutonium T6 Zombies instance with a fresh engine reply and a decoded non-black frame where applicable. |
| accepted | A human played the result and recorded a scoped verdict. |

A level applies only to the exact scope in the receipt. "Loaded Town once" is not "loads every map".

## Platform

| Item | Status |
| --- | --- |
| Windows 11 x64, native Python 3.11+ | Tiers 1 (offline) and 2 (real backends) passed on Windows 11 25H2, build 26200, Python 3.12.0: [receipts/0.1.0a1/tier1-offline.json](receipts/0.1.0a1/tier1-offline.json), [receipts/0.1.0a1/tier2-backends.json](receipts/0.1.0a1/tier2-backends.json). Tier 3 not yet run. |
| Windows 10 | untested |
| Windows on ARM64 | unsupported |
| Wine / Proton / WSL | unsupported for execution; discovery and unit tests only |
| Linux, macOS | discovery and unit tests only; a Linux distribution is a separate future project |

## Routes

| Route | Effect | Level | Owner | Receipt / notes |
| --- | --- | --- | --- | --- |
| `version`, `manifest`, `describe` | inert | native | core | [receipts/0.1.0a1/tier1-offline.json](receipts/0.1.0a1/tier1-offline.json) steps `version`, `manifest`, `describe game load-map`; tests/test_cli.py |
| `doctor` | inert | native | core | presence and configuration only; [receipts/0.1.0a1/tier1-offline.json](receipts/0.1.0a1/tier1-offline.json) step `doctor before configure`, [receipts/0.1.0a1/tier2-backends.json](receipts/0.1.0a1/tier2-backends.json) step `doctor after setup` |
| `configure` | writes-config | native | core | absolute paths, unknown keys rejected; [receipts/0.1.0a1/tier1-offline.json](receipts/0.1.0a1/tier1-offline.json) step `configure fake storage` (isolated `PAT_HOME`, fake storage path) |
| `dev backends` | inert | offline | core | pins validated |
| `dev setup` | downloads-backends | native | core | `--only gsc oat`: gsc-tool 1.4.10 and OpenAssetTools 0.33.0 downloaded over HTTPS, SHA-256 verified, extracted, and re-verified on rerun ([receipts/0.1.0a1/tier2-backends.json](receipts/0.1.0a1/tier2-backends.json) steps `dev setup gsc oat`, `dev setup rerun verifies`); `--plan` in [receipts/0.1.0a1/tier1-offline.json](receipts/0.1.0a1/tier1-offline.json). Archive safety tested with synthetic zips. **The other seven pinned backends have no native download** |
| `gsc compile` | writes-output | native | thread-1 | real gsc-tool 1.4.10: minimal script compiles, broken script fails with `backend_failed` exit 1, and every hello-zm build compile ([receipts/0.1.0a1/tier2-backends.json](receipts/0.1.0a1/tier2-backends.json) steps `gsc compile minimal script`, `gsc compile broken script fails structurally`, `project build hello-zm`). Fake covers log-error-with-exit-zero, crash, missing input |
| `gsc decompile` | writes-output | offline | thread-1 | fake gsc-tool only; **no native run** |
| `ff inspect`, `ff extract` | writes-output | native | thread-1 | real OpenAssetTools 0.33.0 Unlinker on the hello-zm `mod.ff` ([receipts/0.1.0a1/tier2-backends.json](receipts/0.1.0a1/tier2-backends.json) steps `ff inspect mod.ff`, `ff extract rawfiles`) |
| `ff link` | writes-output | offline | thread-1 | Linker plus Unlinker readback ran natively inside `project build` ([receipts/0.1.0a1/tier2-backends.json](receipts/0.1.0a1/tier2-backends.json) step `project build hello-zm`), but **the standalone route did not run** |
| `project plan/build/verify` | writes-output | native | thread-1 | `examples/hello-zm` with real gsc-tool and OpenAssetTools: compile, stage, link, read back, byte-compare one rawfile, verify with `--inputs` ([receipts/0.1.0a1/tier2-backends.json](receipts/0.1.0a1/tier2-backends.json) steps `project plan hello-zm`, `project build hello-zm`, `project verify --inputs`); `plan` and the `output_exists` refusal also in [receipts/0.1.0a1/tier1-offline.json](receipts/0.1.0a1/tier1-offline.json). One script, no assets, no loads |
| `project init` | writes-output | offline | thread-1 | unit tests only; **no native run** |
| `model inspect/convert/transform/rename-bones/retime/preview` | writes-output | offline | thread-1 | background Blender with the bundled worker; fake Blender in tests. **Real Blender and Cast untested** |
| `audio inspect/convert` | writes-output | offline | thread-1 | fake ffmpeg/ffprobe cover parameter mismatch and no-stream input |
| `image convert` | writes-output | offline | thread-1 | fake ImageConverter |
| `lua decompile` | writes-output | offline | thread-1 | fake CoDLuaDecompiler |
| `weapon catalog/plan` | writes-output | offline | thread-1 | synthetic sealed donor: altered/short pages, duplicates, identity mismatch, stale library, recipe rules. No live BO3 capture, no converter. `docs/WEAPONS.md` |
| `game install-mod` | writes-output | offline | thread-2 | file copy with hash check; refuses overwrite without `--replace`; moves old folder aside |
| `game status`, `game mods` | inert | offline | thread-2 | window enumeration and disk inventory; `mods` ran natively against an empty fake storage ([receipts/0.1.0a1/tier1-offline.json](receipts/0.1.0a1/tier1-offline.json)); **`status` has no native run** |
| `game info`, `game check-load` | query-engine | offline | thread-2 | marker-bracketed queries, receipt-bound re-attach, log counts only; fake console |
| `game launch` | changes-game | offline | thread-2 | fixed `plutonium://play/t6zm` URI; `launch_requested`, `game_detected` and `focus_preserved` are reported separately. **Whether the handler exists and whether focus is preserved are open native questions** |
| `game select-mod/reload-mod/load-map/fast-restart/map-restart/disconnect/quit` | changes-game | offline | thread-2 | verified settings before `map`, DLC5 zone guard, ordered mod transaction, never-replay; fake console. **Real console attach untested** |
| `capture *`, `test *` | mixed | **deferred** | thread-2 | Not in this release by product decision (2026-09-10). Contracts stay registered; every route answers `not_implemented`. Research notes for a later release are in the project history. |

## Explicitly out of scope for this release

- Screen recording, screenshots and the autonomous test runner (`capture`, `test`). Deferred.
- Native gameplay input (fire, ADS, reload, Use). Refused rather than simulated.
- The in-game typed feature receiver.
- Greyhound, Husky and C2M live extraction through the toolkit. The GUIs can be downloaded; their
  use is manual.
- BO3 live asset capture and generic weapon conversion.
- Multiplayer, co-op, other Call of Duty titles, Linux, Stream Deck, desktop GUIs, MCP wrapper.

## Beta and 1.0 bars

**`0.1.0-beta.1`** requires [WINDOWS-QUALIFICATION.md](WINDOWS-QUALIFICATION.md) Tiers 1 to 3 passed
on a native host from shipped materials, with receipts under `docs/receipts/`: install, real
backends building `examples/hello-zm`, `install-mod`, `launch`, `load-map town`, `check-load`,
`select-mod hello_zm`, and a human-observed playable spawn with the hello-zm line on screen.

**`1.0.0`** additionally requires: the remaining dev routes (`model`, `audio`, `image`, `lua`,
`weapon`) at level `native`; frozen JSON, exit-code and schema contracts; both pilot journeys
([PILOT-USER.md](PILOT-USER.md) and [PILOT-CONTRIBUTOR.md](PILOT-CONTRIBUTOR.md)) passed by
agents on a different harness than the one that built the toolkit. Capture and testing are a
separate later release.

## Release mechanics

`python tools/bump_version.py <version>` moves every version statement at once and promotes the
`Unreleased` changelog section. `python tools/release_check.py --tag v…` must pass. Pushing the
tag runs `.github/workflows/release.yml`: tests on Windows, release check against the tag, wheel
and sdist with SHA-256 sums, GitHub Release with the changelog section as notes. Pre-release
tags (`-alpha`, `-beta`, `-rc`) are marked pre-release automatically.
