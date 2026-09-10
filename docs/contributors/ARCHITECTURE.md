# Architecture

## One CLI, three components, one core

```
pat <group> <action> [options]
        │
        ├── core/        errors · envelope · config · receipts · platform · discovery
        ├── dev/         backends (setup, doctor) · gsc · ff · project · model · audio · image · lua · weapon
        ├── game/        status · info · launch · select-mod · load-map · reload-mod · check-load · mods · quit
        └── testing/     capture start/status/screenshot/mark/save-clip/stop · test plan/start/status/cancel/report
```

Every group registers `Route` objects in its `routes.py`. `cli.py` imports those modules, which
populates the registry behind `manifest` and `describe`. A route's `status` is a promise: `planned`
routes must raise `not_implemented`; `available` routes must have a native Windows receipt in
`docs/SUPPORT.md`.

## Invariants

1. **One JSON document per invocation** on stdout. Diagnostics go to log files under the job's
   output directory, never to stdout.
2. **Exit statuses** 0 ok, 1 failure, 2 usage, 130 cancelled. Derived from `Failure.code`.
3. **Stable error codes** in `core/errors.py`. Add, never repurpose.
4. **New output directory per job.** `receipts.new_output_dir` refuses existing paths.
5. **Receipts** record argv, input hashes, output hashes, status, exit code and log paths. Failed
   and cancelled jobs write receipts too.
6. **Platform gate** before side effects. `platform.require_windows(...)` in every route that
   touches backends, the game or the display. Wine is detected and reported as not native.
7. **No home-directory assumptions.** All paths come from `PAT_HOME`, `%LOCALAPPDATA%` or explicit
   configuration.
8. **No replay of uncertain game commands.** `delivery_uncertain` is terminal for that invocation.
9. **No escape hatches.** No raw console strings, memory reads, arbitrary GSC calls, input synthesis.

## Backend execution (Thread 1)

Backends live under `<backends_dir>/<id>/`. Jobs run them as child processes inside a Windows Job
Object so the whole tree is terminated on timeout or cancel. Output size and log size are bounded.
Receipts record the backend's pinned SHA-256 alongside the job so a result can be tied to the exact
tool build.

## Game control (Thread 2)

Process identity is PID plus creation time from `GetProcessTimes`. The transport attaches to the
game's existing external console (`AttachConsole`, `WriteConsoleInputW`) and brackets fresh dvar
queries with random markers so stale output is rejected. One named mutex serializes live work
across all toolkit copies. Launch uses the registered `plutonium://play/t6zm` handler; focus
events are logged during the whole startup interval and reported as a separate result.

## Capture (Thread 2)

Planned stack: Windows.Graphics.Capture for the game window (works unfocused and occluded),
WASAPI process loopback for game-only audio, hardware encoder via FFmpeg. One full recording plus
a short replay ring; `mark` protects recent footage before anything else happens. Finalization
probes the file and decodes one frame. Display-off behavior is qualified per condition.

## Testing runner (Thread 2)

A plan pins package hashes, map recipe, capture profile and limits. `test start` admits one plan,
arms capture, launches or loads, runs the recipe and writes a sanitized report. `test cancel` stops
automation and leaves recording running for the human. Uncertain or lost steps are preserved, never
repeated.
