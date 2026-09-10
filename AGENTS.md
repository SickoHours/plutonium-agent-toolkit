# Agent instructions for the Plutonium Agent Toolkit

You are an agent reading this. That is the assumption behind everything in this repository. A
person asked their coding agent, you, to help them mod Plutonium Black Ops II Zombies, and you are
running in some harness with local file and terminal access: Claude Code, Codex, T3 Code, Gemini
CLI, Cursor, or another. This toolkit is built to be operated and adapted by you, not read by the
human. The human describes the outcome they want. You read these docs, install and configure the
toolkit for their exact machine, run the commands, debug what breaks, and report evidence.

## This toolkit is yours to change

The most important thing to understand: **nothing here is fixed.** This is open source, MIT-free
Apache-2.0 code with no hidden state, and it is meant to be modified to fit whoever is using it.
When you are helping someone set it up, assume from the start that you may and should adapt it to
their environment:

- **Configure to their machine.** Paths come from `pat configure`, the `PAT_HOME` environment
  variable, and the `PAT_BACKEND_<NAME>` overrides. Nothing assumes a fixed install location. If
  their Plutonium storage, Python, or a backend tool lives somewhere unusual, point the toolkit at
  it rather than moving their files.
- **Edit the code when it does not fit.** If an adapter's assumption is wrong for their build of a
  tool, their Windows version, or their setup, change it. The adapters in `src/` are small and
  documented for exactly this. Read the file, understand the contract in
  `docs/contributors/ARCHITECTURE.md`, make the change, add a test, and tell the user what you
  changed and why.
- **Extend it.** Adding a command, a backend, a map recipe or a mod recipe is a documented,
  expected activity. See `docs/contributors/`. A user who needs a route that does not exist should
  get it from you, not a "not supported".
- **Debug on their machine.** Every command returns one JSON document with a stable `error_code`
  and a `hint`, and every job writes a `receipt.json`. When something fails, read the receipt, read
  the step log it points at, and fix the cause. The failure modes are enumerated in
  `docs/GAME-CONTROL.md`, `docs/WINDOWS-QUALIFICATION.md` and each guide's troubleshooting table.

Treat "make it work for this person's setup" as the job, not an exception to it.

## Read first

1. `README.md` for the product and its current status, then `docs/TRACK-RECORD.md` for what this
   workflow has produced and how far past the packaged routes you are expected to go.
2. `docs/FOR-AGENTS.md` for how to operate and adapt the toolkit, and the modding behaviours
   (foundation-first modular building, mod organization, the lessons that shaped the safety rules).
   Then `CONTEXT.md` for the words, `docs/knowledge/README.md` (T6 and Plutonium facts, once
   per session) and the playbook in `docs/playbooks/README.md` that matches the task; run the
   `docs/playbooks/preflight-*.md` gates before a build's first install. `skills/pat-help`
   names the flow for a situation.
3. `docs/SUPPORT.md` for what each route has actually earned. It is canonical for the evidence
   levels (`contract`, `offline`, `native`, `game`, `accepted`); read the definitions there and do
   not restate them from memory. Separately, `pat manifest` reports a route's implementation
   **status** (`available`, `implemented`, `planned`, `deferred`, `unsupported`). Never present a
   `planned`, `deferred` or `implemented` route as verified, a Wine result as native Windows, or a
   compile as a gameplay pass; a route reaches `available` only when `docs/SUPPORT.md` links a
   native receipt for it.
4. `pat manifest --json` once per session, then `pat describe <group> <action> --json` for a known
   route. Discovery never executes anything and needs no authorization.
5. For development work, `CONTRIBUTING.md` and `docs/contributors/`.

## Assume a harness, assume local access

You do not need this repository to install another agent, a provider account, an API key or a paid
service. Whoever is using it already has you. Use the file and terminal access you have. If you are
a chat with no local access, say so plainly, because you cannot run these tools by reading a file;
the human needs a terminal-capable agent on the same machine as Plutonium.

## Operating rules

These are how the toolkit is built, so that you can extend it without breaking its guarantees:

- One JSON document per invocation on stdout. Keep it and the exit status together; that pair is
  the receipt. Diagnostics go to log files, never to stdout.
- Exit statuses: 0 ok, 1 failure, 2 usage, 130 cancelled. Error codes are stable strings in
  `src/plutonium_agent_toolkit/core/errors.py`. Add new codes; never repurpose old ones.
- Every job needs a new `--output` directory. The toolkit refuses to overwrite. Do not delete
  outputs to force a retry; investigate instead.
- `error_code: delivery_uncertain` means inspect fresh state, not retry. Never replay an uncertain
  game command.
- Setup, discovery, `dev`, `gsc`, `ff`, `project`, `model`, `audio`, `image`, `lua`, `weapon` and
  `game mods`/`install-mod` touch no running game. `game launch/info/load-map/select-mod/
  reload-mod/fast-restart/map-restart/disconnect/check-load/quit` control the running client and
  need the user's go-ahead for that specific test.
- The development (file) routes run on Windows and Linux; macOS is untested and not claimed. Game
  control and capture use the Win32 console and run on native Windows only; off Windows they refuse
  with `unsupported_platform` before acting.
- A development route `docs/SUPPORT.md` marks unverified on your Windows or Linux host is
  unmeasured, not unsupported. Measure it: `docs/playbooks/qualify-on-this-host.md` produces the
  receipt and the pull request. Never tell the user a route "does not work here" when the truth
  is that nobody has run it here yet.
- Do not focus, minimize, kill or send keystrokes to the game as a workaround. Report the failure.
- Do not elevate privileges, read process memory, launcher arguments or logins, or change registry
  keys beyond a documented per-user PATH entry.
- Never ask the user for, or use, a password, token, launcher credential or login database. You do
  not need any of them to install, configure, adapt or run this toolkit. If a step seems to require
  one, that is a signal to stop and report, not to request it.
- Keep the user's paths, receipts, recordings and logs on their machine. Sanitize before sharing.
- There is no arbitrary console-string, memory-write or arbitrary-function route, and you should
  not add one. Adapting the toolkit means new typed, validated routes, not an escape hatch.

## Work efficiently

The toolkit is cheap per call, and every call is a receipt; spend calls on new facts, not on
re-reading known ones.

- Read `pat manifest --json` at most once per session; `describe` only a route you will run.
- Read `docs/knowledge/README.md` once, then work from it. T6 facts there were paid for with real
  crashes; do not re-derive them by trial builds.
- Read the playbook in `docs/playbooks/` for the task before the first command and follow its
  "Do not" list; the lists name the wasted commands for that task.
- A receipt with `status: succeeded` is the fact. Do not re-run a job to "confirm" it.
- Rebuild only after an input changed. The receipt lists every input hash; compare them.
- Keep outputs outside the source tree; one new `--output` per job; never delete one to retry.
- Never replay a `delivery_uncertain` game command; inspect fresh state and decide.
- Say which facts are unverified instead of adding checks that cannot verify them. "Offline
  verified; not loaded" is a complete, honest report.

## Reporting

Lead with what was verified and what was not. Keep these six separate: offline verified, installed,
launched, playable, captured, player-accepted. If you cannot inspect an image, say the visual
checkpoint is unverified. A failed original attempt stays failed even if a later attempt recovers.

## Developing or adapting the toolkit

- Work on a branch; never commit to `main` directly. For a user's local one-off adaptation a branch
  is still the clean way, and it makes the change easy to upstream if it helps others.
- Change code, tests and docs together. Add an entry under `## [Unreleased]` in `CHANGELOG.md`.
- Run `python -m unittest discover -s tests -v`, `python tools/private_scan.py` and
  `python tools/release_check.py` before opening a pull request.
- New routes register in the owning `routes.py` with an honest `status`. A route becomes
  `available` only with a native receipt in `docs/SUPPORT.md`, produced by `tools/qualify.py`
  on Windows (per `docs/WINDOWS-QUALIFICATION.md`) or on Linux. Only game control and capture
  require native Windows, because their transport is the Win32 console.
- Never commit game assets, recordings, logs, credentials or personal paths. `tools/private_scan.py`
  runs in CI and blocks them.

`CLAUDE.md` imports this file for Claude Code. Every other harness reads this file directly; it is
the single source of truth for how to operate here.
