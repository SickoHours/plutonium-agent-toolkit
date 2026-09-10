# Agent instructions for the Plutonium Agent Toolkit

You are operating or developing this toolkit on behalf of a user who may have no modding or
programming experience. You own routine file inspection, setup, commands, tests and evidence.
The user owns intent, gameplay feedback and live-game authorization. Ask only for material
decisions. Never ask for passwords, tokens or launcher credentials.

## Read first

1. `README.md` for the product and its current status.
2. `docs/SUPPORT.md` for what each route has actually earned. Never present a `planned` route as
   working, a Wine result as native Windows, or a compile as a gameplay pass.
3. `pat manifest --json` once per session; then `pat describe <group> <action> --json` for a known
   route. Discovery never executes anything.
4. For development work, `CONTRIBUTING.md` and `docs/contributors/`.

## Operating rules

- Use the returned `argv` arrays. Run one invocation at a time for game operations.
- Keep every invocation's stdout JSON **and** exit status. Together they are the receipt.
- Every job needs a new output directory. The toolkit refuses to overwrite; do not delete outputs
  to make a retry succeed.
- `error_code: delivery_uncertain` means inspect fresh state, not retry. Never replay an uncertain
  game command.
- Setup and discovery send no game input. Launching, loading, restarting, capturing or quitting the
  game requires the user's authorization for that specific test.
- Do not focus, minimize, kill or send keystrokes to the game as a workaround. Report the failure.
- Do not install other agents, change provider configuration, elevate privileges, edit the registry
  beyond documented per-user PATH entries, or read process memory, launcher arguments or logins.
- Keep the user's paths, receipts, recordings and logs local. Sanitize before sharing anything.

## Reporting

Lead with what was verified and what was not. Separate: offline verified, installed, launched,
playable, captured, player-accepted. If you cannot inspect an image, say the visual checkpoint is
unverified. A failed original attempt stays failed even if a later attempt recovers.

## Developing the toolkit

- Work on a branch; never commit to `main` directly.
- Every change ships code, tests, docs and an entry under `## [Unreleased]` in `CHANGELOG.md`.
- Run `python -m unittest discover -s tests -v`, `python tools/private_scan.py` and
  `python tools/release_check.py` before opening a pull request.
- New routes register in the owning `routes.py` with an honest `status`. A route becomes
  `available` only with a native Windows receipt recorded in `docs/SUPPORT.md`, produced by
  `tools/qualify_windows.py` per `docs/WINDOWS-QUALIFICATION.md`.
- Never add a generic console-string, memory-write or arbitrary-function escape hatch.
- Never commit game assets, recordings, logs, credentials or personal paths. `tools/private_scan.py`
  runs in CI and blocks them.

`CLAUDE.md` imports this file. Other agents read it directly.
