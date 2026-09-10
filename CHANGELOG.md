# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/) (tags) with the equivalent PEP 440 form in code.
Every entry states what shipped, on which platform it was verified, and what remains unverified.

## [Unreleased]

### Changed

- Repository made public on 2026-09-10 at 0.1.0a1 so the program can use branch rulesets,
  secret scanning and private vulnerability reporting. Readiness is unchanged: see docs/SUPPORT.md.
- CI uses actions/checkout v7, setup-python v7 and upload-artifact v7 (Node 24 runtime).

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
