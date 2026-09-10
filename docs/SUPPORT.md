# Support matrix for `0.1.0a1`

This file is the single source of truth for what each route has earned. Update it in the same
pull request that changes a route. `tools/release_check.py` verifies the version in the first line.

## Evidence levels

| Level | Meaning |
| --- | --- |
| contract | Route is registered with name, effect and owner. Answers `not_implemented`. |
| offline | Implemented; unit tests pass with synthetic fixtures and fake backends on any platform. Executes on Windows but has no native receipt. |
| native | Ran on a native Windows 11 x64 host with a sanitized receipt linked below. Wine, WSL and CI runners do not count. |
| game | Produced a verified effect in a running Plutonium T6 Zombies instance with a fresh engine reply and a decoded non-black frame where applicable. |
| accepted | A human played the result and recorded a scoped verdict. |

A level applies only to the exact scope in the receipt. "Loaded Town once" is not "loads every map".

## Platform

| Item | Status |
| --- | --- |
| Windows 11 x64, native Python 3.11+ | target; not yet exercised |
| Windows 10 | untested |
| Windows on ARM64 | unsupported |
| Wine / Proton / WSL | unsupported for execution; discovery and unit tests only |
| Linux, macOS | discovery and unit tests only; a Linux distribution is a separate future project |

## Routes

| Route | Effect | Level | Owner | Receipt / notes |
| --- | --- | --- | --- | --- |
| `version`, `manifest`, `describe` | inert | offline | core | tests/test_cli.py |
| `doctor` | inert | offline | core | presence and configuration only |
| `configure` | writes-config | offline | core | absolute paths, unknown keys rejected |
| `dev backends` | inert | offline | core | pins validated |
| `dev setup` | downloads-backends | offline | core | archive safety and reinstall verification tested with synthetic zips; all nine backends pinned including C2Mv3; **no native download yet** |
| `gsc compile`, `gsc decompile` | writes-output | offline | thread-1 | fake gsc-tool covers log-error-with-exit-zero, crash, missing input; **real gsc-tool untested** |
| `ff inspect`, `ff link`, `ff extract` | writes-output | offline | thread-1 | fake Linker/Unlinker; **real OpenAssetTools untested** |
| `project init/plan/build/verify` | writes-output | offline | thread-1 | hello-zm round-trips through fakes: compile, stage, link, read back, byte-compare, verify with --inputs |
| `model convert/inspect` | writes-output | contract | thread-1 | Blender + Cast |
| `audio convert` | writes-output | contract | thread-1 | |
| `image convert` | writes-output | contract | thread-1 | |
| `lua decompile` | writes-output | contract | thread-1 | |
| `weapon catalog/plan` | writes-output | contract | thread-1 | saved BO3 asset libraries; no live BO3 capture, no generic converter |
| `game status/info/mods/check-load` | inert / query-engine | contract | thread-2 | |
| `game launch` | changes-game | contract | thread-2 | direct launch via `plutonium://play/t6zm` and focus preservation are separate results |
| `game select-mod/load-map/reload-mod/quit` | changes-game | contract | thread-2 | |
| `capture start/status/screenshot/mark/save-clip/stop` | captures-display | contract | thread-2 | Windows.Graphics.Capture + WASAPI process loopback + hardware encoder: Stage 1 spike |
| `test plan/start/status/cancel/report` | mixed | contract | thread-2 | |

## Explicitly out of scope for this release

- Native gameplay input (fire, ADS, reload, Use). Refused rather than simulated.
- The in-game typed feature receiver. A standalone Apache-2.0 receiver is a 1.0 deliverable.
- Display-off / monitor-asleep capture. To be qualified per condition, never assumed.
- Greyhound, Husky and C2M live extraction through the toolkit. The GUIs can be downloaded; their
  use is manual.
- BO3 live asset capture and generic weapon conversion.
- Multiplayer, co-op, other Call of Duty titles, Linux, Stream Deck, desktop GUIs, MCP wrapper.

## Beta and 1.0 bars

**`0.1.0-beta.1`** requires the first complete workflow at level `game` on a native host from
shipped materials: setup prompt, install, `examples/hello-zm` build and verify, install into
storage, `capture start`, `game launch`, `game load-map town`, fresh engine reply plus decoded
non-black frame, `capture screenshot`, `capture stop`, sanitized report.

**`1.0.0`** additionally requires: standalone receiver with one shipped feature scenario at level
`game`; capture qualified per display condition; published frametime and encoder measurements;
frozen JSON, exit-code and schema contracts; both pilot journeys (user and contributor) passed
by agents on a different harness than the one that built the toolkit.
