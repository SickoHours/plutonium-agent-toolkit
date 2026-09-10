# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/) (tags) with the equivalent PEP 440 form in code.
Every entry states what shipped, on which platform it was verified, and what remains unverified.

## [Unreleased]

### Added

- Release automation: `tools/bump_version.py` (moves the version everywhere and promotes the
  `Unreleased` section), `tools/release_notes.py` (changelog section as release notes), and
  `.github/workflows/release.yml` (tag push verifies, tests on Windows, builds, publishes a
  GitHub Release with checksums; pre-release tags flagged automatically).
- Pilot acceptance journeys: `docs/PILOT-USER.md` and `docs/PILOT-CONTRIBUTOR.md`.
- Maintainer checklist for the Windows qualification pull request:
  `docs/contributors/REVIEWING-QUALIFICATION.md`.
- Windows qualification procedure: `WINDOWS-QUALIFY-PROMPT.md` for the agent on the Windows PC,
  `docs/WINDOWS-QUALIFICATION.md` (three tiers, human-authorized game tier),
  `tools/qualify_windows.py` producing redacted receipts under `docs/receipts/<version>/`.
- Windows-gated development routes implemented: `gsc compile|decompile`,
  `ff inspect|link|extract`, `project init|plan|build|verify`, `model
  inspect|convert|transform|rename-bones|retime|preview` (background Blender with the bundled
  worker and pinned Cast add-on), `audio inspect|convert`, `image convert`, `lua decompile`.
  Jobs run backends inside a Windows Job Object (process group elsewhere for tests), bound log
  and output size, and write `receipt.json` on every exit path.
- `weapon catalog|plan` implemented (any platform): sealed BO3 donor verification and recipe
  planning; `docs/WEAPONS.md`.
- `game` group implemented behind the Windows gate: `status`, `mods`, `info`, `launch`,
  `select-mod`, `reload-mod`, `load-map`, `fast-restart`, `map-restart`, `disconnect`,
  `check-load`, `quit`. Native Win32 console transport (attach, screen read, one bounded input
  write), marker-bracketed engine queries, verified map settings before `map`, DLC5 zone guard,
  ordered mod transactions, receipt-bound `check-load` with log error counts only, `quit`
  without force-kill. Launch goes through the fixed `plutonium://play/t6zm` URI and reports
  request, detection and focus preservation as separate facts. One bounded worker per command
  under a named mutex; uncertain outcomes are never replayed. `docs/GAME-CONTROL.md`.
- `game install-mod <mod.ff> <folder>`: file-only install into storage with hash verification;
  refuses to overwrite without `--replace`, which moves the old folder aside.
- `core/jobs.py` job runner, `PAT_BACKEND_<NAME>` override for tests and pre-installed tools,
  `implemented` and `deferred` route statuses alongside `planned` and `available`.
- Fake gsc-tool, Linker, Unlinker, ffmpeg/ffprobe, ImageConverter, CoDLuaDecompiler and Blender
  under `tests/fakes/` so every adapter is unit-tested offline, including compiler errors reported
  with exit zero, backend crashes, tampered outputs and recipe path escapes.
- C2Mv3 3.0.5 hash pinned (optional, never redistributed).

### Changed

- `capture` and `test` routes are `deferred` (product decision 2026-09-10): registered, refuse
  with `not_implemented`, and excluded from the beta and 1.0 bars in `docs/SUPPORT.md`.
- Repository made public on 2026-09-10 at 0.1.0a1 so the program can use branch rulesets,
  secret scanning and private vulnerability reporting. Readiness is unchanged: see docs/SUPPORT.md.
- CI uses actions/checkout v7, setup-python v7 and upload-artifact v7 (Node 24 runtime).

### Fixed

- Findings of the first native Windows run (Windows 11 25H2 build 26200, Python 3.12.0), Tier 1 of
  `docs/WINDOWS-QUALIFICATION.md`:
  - The documented `PAT_HOME` at `<repo>/.qualify-home` was not ignored by git, so `configure` put
    the user's absolute storage path where `tools/private_scan.py` lists untracked files and the
    Tier 1 private scan failed. `.gitignore` ignores it; `tests/test_release_tools.py` checks that
    the documented location stays ignored.
  - `src/plutonium_agent_toolkit.egg-info/` was tracked, so `pip install -e .` dirtied the tree and
    every receipt recorded `git_dirty: true`. Untracked and ignored, with a test that refuses
    tracked egg-info.
  - Windows job runner: a backend tree terminated through the Job Object (timeout, output bound,
    cancellation) kept its inherited handle to the step log for up to a scheduler tick after
    `process.wait()` returned, so deleting the job directory immediately failed with
    `ERROR_SHARING_VIOLATION` about one time in ten and made `test_finish_rechecks_output_bound`
    flaky. `_run_windows` now waits, bounded, for the log to be released after closing its own
    handle and records `log_still_open` on the step if it is not. `tests/test_jobs_windows.py`
    (native Windows only) covers the wait and the timeout path.
  - `tools/qualify_windows.py` overwrote an earlier receipt on rerun. It now moves the previous
    file to `<name>.superseded-<utc stamp>.json` and notes it, so a failed attempt survives the fix
    as `docs/contributors/RECORDING-A-RECEIPT.md` requires.
  - The tier commands said `--output docs/receipts/qualify`, contradicting `docs/receipts/README.md`
    and this changelog; they say `--output docs/receipts` now.

- Maintainer review of the Tier 1 and 2 receipts: the failed first-attempt receipt embedded
  `private_scan`'s own hit excerpt, a truncated `C:\Users\m`, which the redactor missed because it only
  knew the exact `USERPROFILE`; other accounts' and other drives' `Users` paths would also have
  survived. `tools/qualify_windows.py` now replaces any drive-letter `Users` path for any account,
  in either slash style, including account names that contain spaces, before the account-specific
  patterns; strips `excerpt` from embedded scan hits; and gains `--redact-existing <file>`, which reapplies the current rules to a committed
  receipt in place, is idempotent, notes the rewrite and runs on any platform. The affected receipt
  was re-redacted with it, not hand-edited. `redactor()` is unit-tested directly with the
  reviewer's five inputs plus the JSON-escaped form.
- Windows job runner: when the step log is still held after the bounded wait, the step records
  `log_release_wait_seconds` next to `log_still_open`.
- `tools/qualify_windows.py --tier game --begin`, exactly as `docs/WINDOWS-QUALIFICATION.md` writes it
  (no `--output`), was refused by argparse because `--output` was unconditionally required, so the
  Tier 3 marker could never be written as documented. `--output` is now required only when a
  receipt is written, and only for `--tier game`: `--tier offline --begin` or `--tier backends --begin`
  without `--output` is refused up front instead of running the whole tier and crashing at the end.
  Found on the first native Tier 3 attempt; regression tests added.
- `game check-load` capped the new console output it would inspect at 128 KiB and reported the log
  gate `checked: false` above that. A single native Town load emits far more (about 4000 lines:
  fastfile, ipak and per-weapon lines), so `check-load` could never verify a real `load-map`. The
  bound is now 4 MiB, matching a job's backend log; regression test with a map-load-sized log.
  Found on the first native Tier 3 attempt.

### Verified

- Native Windows Tier 1 (offline) receipt `docs/receipts/0.1.0a1/tier1-offline.json`: Windows 11
  25H2 build 26200, Python 3.12.0, clean tree. 13/13 steps: unit tests, `version`, `manifest`,
  `describe`, `doctor`, `configure`, `game mods` on an empty storage, `dev setup --plan`,
  `project plan` of `examples/hello-zm`, the `output_exists` refusal, the deferred-route refusal,
  private scan and release check. `version`, `manifest`, `describe`, `doctor` and `configure`
  move to level `native` in `docs/SUPPORT.md`. The failed first attempt is kept alongside as
  `tier1-offline.superseded-*.json`.

- Native Windows Tier 2 (backends) receipt `docs/receipts/0.1.0a1/tier2-backends.json`: same host,
  clean tree, 10/10 steps on the first attempt. gsc-tool 1.4.10 and OpenAssetTools 0.33.0
  downloaded, SHA-256 verified and re-verified on rerun; `examples/hello-zm` compiled, linked,
  read back, byte-compared and verified with `--inputs` (`mod.ff` 384 bytes, SHA-256 in the
  receipt); `ff inspect` and `ff extract` on the result; a broken script fails with
  `backend_failed`; a minimal script compiles. `gsc compile`, `ff inspect`, `ff extract` and
  `project plan|build|verify` become `available` and move to level `native`; `dev setup` moves to
  `native` for `gsc` and `oat`.

- Native Windows Tier 3 (running game) attempted, receipt `docs/receipts/0.1.0a1/tier3-game.json`
  (3/5 collector checks): `game launch` started T6 Zombies through the `plutonium://play/t6zm`
  handler with no launcher prompt (`focus_preserved` false, ~5 s); `game status` and `game info`
  attached to the live external console and returned correct window and dvar state. `load-map town`
  set the dvars and sent `map` but did not start a survival match, so `check-load` could not verify.
  `select-mod zm_gobblegums`, `select-mod base` (verified `fs_game` changes) and `quit` (stopped through
  the engine) ran natively. No `game` route earned level `game`; all stay `offline`.

### Not verified

- No `game` route qualifies at level `game`. `load-map` starts the match but the client then drops it.
  Console-log diff on this install: every toolkit-started load reaches `Initializing game`, loads the
  Town gump, and ends within seconds with `SV_Shutdown: hostquit` and `Dropping client num 0:
  EXE_DISCONNECTED`, returning to the menu; the two menu-started matches play to completion and end
  with `EXE_MATCHENDED`. The gametype settings configs (`zm/gamesettings_*.cfg`) exec at frontend init
  in both paths, and the `Could not load weapon` and `ipak file not found: common_zm` lines appear
  identically in the playable session, so neither the config nor the base assets is the cause (the
  `zm_transit` zone set is complete and unchanged since 2025-10). The console `map` path connects
  the local client through the mod-download check (`Searching for files required to download mod`),
  which the menu's party-lobby path does not. Root cause remains open in issue #8; no command
  allowlist change was made. `reload-mod`, restarts, `disconnect` and `install-mod` in game were not
  exercised. Issue #9 tracks the opt-in focus restore after launch.
- `gsc decompile`, `project init` and the standalone `ff link` route did not run natively and stay
  `implemented`. The seven other pinned backends were not downloaded.

## [0.1.0a1] - 2026-09-09

First private foundation commit. Nothing in this version has run on a native Windows host.

### Added

- `pat` command with `version`, `manifest`, `describe`, `doctor`, `configure`, `dev backends` and
  `dev setup`. One JSON document per invocation; exit statuses 0/1/2/130; stable `error_code` values.
- Core contracts: `Failure` with stable codes, result envelope with `schema_version` and
  `request_id`, per-user configuration under `PAT_HOME` or `%LOCALAPPDATA%\PlutoniumAgentToolkit`,
  receipts with input/output hashes, platform gate that refuses backend and game operations off
  Windows and detects Wine.
- Pinned backend catalogue with licenses: OpenAssetTools 0.33.0, gsc-tool 1.4.10, CoDLuaDecompiler
  2.4.2, FFmpeg 9.0 (BtbN build), Blender 5.2.1, Cast 2.00, Greyhound 1.46.3.2, Husky 0.8.0.0.
  C2Mv3 listed as optional and unpinned. Setup verifies SHA-256, extracts with path-safety checks,
  refuses to overwrite a changed tree and runs no vendor installer.
- Route contracts for every planned capability across `gsc`, `ff`, `project`, `model`, `audio`,
  `image`, `lua`, `weapon`, `game`, `capture` and `test`. Planned routes answer `not_implemented`
  and execute nothing.
- Contributor foundation: `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `SECURITY.md`,
  `CODE_OF_CONDUCT.md`, `NOTICE`, `PROVENANCE.md`, issue and pull request templates, CODEOWNERS.
- `tools/private_scan.py` blocks personal paths, private identifiers, tokens and old internal
  command names. `tools/release_check.py` verifies that the package version, `pyproject.toml`,
  the top changelog entry, `docs/SUPPORT.md` and the tag agree.
- GitHub Actions workflow running the unit tests, both tools and a packaging build on
  `windows-latest`.
- `docs/SUPPORT.md` qualification matrix, `docs/GETTING-STARTED.md`, contributor guides and the
  first engineering-history note.
- `examples/hello-zm`: the first-run mod used by the qualification loop.
- Installable agent skill and `SETUP-PROMPT.md`.

### Verified

- Unit tests, private scan and release check pass on the Linux authoring host.

### Not verified

- Anything on native Windows. Backend downloads, game control and capture have no receipts yet.
