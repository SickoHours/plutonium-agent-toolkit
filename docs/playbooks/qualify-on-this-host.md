# Qualify a route on this host

`docs/SUPPORT.md` names the exact host each route has a receipt from. When your host is not one
of them, or a row says a route is unverified here, the route is not broken and not forbidden: it
is unmeasured. This playbook measures it, produces the receipt that would make the claim true,
and ends with a pull request the maintainers can merge. It is how the support matrix grows.

## Preconditions

- The toolkit is installed and `pat version --json` returns `ok: true`.
- The host is a real Windows or Linux machine, not Wine, WSL or a CI runner; `tools/qualify.py`
  refuses those, and a receipt from them proves nothing.
- You have read the route's row in `docs/SUPPORT.md` and know which tier covers it: Tier 1
  (offline: discovery, configure, plan) needs no downloads; Tier 2 (backends) downloads the
  pinned programs, and with `--media` also FFmpeg, Blender and Cast (about 510 MB, 2 GB on disk).
- Disk and network for the tier you will run, and the user's awareness that downloads happen.
  Nothing here touches the game.

## Steps

1. Run Tier 1 with an isolated toolkit home so the user's configuration is untouched:
   ```sh
   PAT_HOME=<scratch>/pat-home python tools/qualify.py --tier offline --output docs/receipts
   ```
   Proof: the last line is `PASSED: N/N steps` and `docs/receipts/<version>/<platform>-tier1-offline.json`
   exists with `environment.compatibility_layer: null` and `environment.git_dirty: false`.
2. Run Tier 2, adding `--media` when the route you are qualifying is under `audio` or `model`:
   ```sh
   PAT_HOME=<scratch>/pat-home python tools/qualify.py --tier backends [--media] --output docs/receipts
   ```
   Proof: `PASSED`, and the receipt's `steps[]` contains a passed step whose name covers your
   route (for example `audio convert tone.wav 48 kHz mono`, `model convert cube.obj to cast`).
3. Read the receipt yourself before anything else: no username, hostname, home path or work
   directory survives (`tools/qualify.py` redacts them; you confirm). Run
   `python tools/private_scan.py`. Proof: `"ok": true`.
4. If a step failed, the fake backend in `tests/fakes/` lied about the real program on this
   host. Fix the adapter under `src/plutonium_agent_toolkit/dev/`, make the fake reproduce the
   real behaviour, add a regression test, rerun the tier. Proof: the failed receipt is kept
   beside the passing one (the tool moves it aside as `*.superseded-*.json`), and the new
   receipt passes.
5. Update `docs/SUPPORT.md`: the route's row names this host and links the receipt; the
   Platform table gains or extends the host's row. Do not raise a route above what the receipt's
   steps actually ran. Add a line under `## [Unreleased]` in `CHANGELOG.md`.
6. Run the three checks and open a pull request from a branch named `qualify/<platform>-<date>`
   with the template filled in, "Not verified" included:
   ```sh
   python -m unittest discover -s tests -v
   python tools/private_scan.py
   python tools/release_check.py
   ```
   Proof: all green; the pull request lists the receipt files and the rows it changed.

## Do not

- Hand-write or edit a receipt; the tool writes them and the review reads them.
- Present a Wine, WSL or CI run as native, or a passing tier as gameplay evidence.
- Flip a route to `available` on a host whose receipt does not contain a step for it.
- Skip the private scan because the redactor ran; the redactor is a tool, the scan is the gate.
- Run the game tier off Windows, or on Windows without the user's go for each command.

## Stop conditions

- The host is a compatibility layer: stop; tell the user a real host is needed.
- A tier fails and the cause is outside the toolkit (the upstream program does not run on this
  host at all): stop, keep the failed receipt, and report the program, its version and the
  error; the pull request can still land the receipt as a documented failure.
- Both tiers pass and the pull request is open: complete. Merging is the maintainer's call.

## Report

State the host (OS, version, Python), which tiers ran, which route steps passed, the receipt
paths, what the redaction check found, and what is still unverified on this host (routes with
no step, and every route on the other OS). Then the six build facts as always: this playbook
earns **offline verified** and **native** for the named steps and nothing further.
