# Diagnose a crash or a dropped match

The player said "crashed", the game returned to the menu, or the process closed. Produce an honest
account from the evidence, preserve the failure, and name the smallest change that tests the
cause. Diagnosis reads; it changes nothing.

## Preconditions

- You know which package was installed (its hash from the install receipt) and which load was
  issued (its load ID from the last `check-load` result). `pat game mods --json` names the
  folders but reports no hash; if the install receipt is gone, hash the installed `mod.ff`
  yourself or record the package hash as unknown.
- On Windows with the game configured: `pat game info --json` is available for fresh state. On
  Linux, or with no game, you work from the log and receipts only.
- `docs/knowledge/crashes.md` is read: the classes and where each cause lives.

## Steps

1. Freeze the facts: package hash, map, base, player count, the timestamp of the failure, and the
   phase (startup, first use, replacement, expiry, disconnect). Write them down before reading
   anything else.
2. Get fresh state if a game is running and the user allows one query:
   ```sh
   pat game info --json
   ```
   Proof: `result.state` with `sv_running`, `fs_game`, `mapname`. `sv_running: "0"` with the
   mod still selected is a dropped match, not a closed game.
3. Read the log slice for that load: `storage/t6/main/console_zm.log` from the load's timestamp.
   If the client and its console are still running and the load ID is still valid (ten minutes),
   `pat game check-load <load-id> --json` reports `logs.<log>.error_lines` for it
   (`checked: false` means the log gate is unverified, not clean). After a closed-process
   crash `check-load` cannot attach and fails; read the log slice directly. Find the first
   error line, not the last.
4. Classify with the table in `crashes.md`: script error, load refused, pool exhausted,
   allocation failure, renderer, host OOM, UI Lua, script panic. `pat knowledge signature --log
   <slice> --json` matches the slice against the recorded signatures line by line. One class per failure; a second
   failure on the way out (a menu Lua error on disconnect) is recorded separately.
5. Correlate: what changed since the last good load of the same map (package hash, base, loose
   `raw/` files); whether the same line appears in a playable session (then it is noise); which
   lifecycle path was active.
6. Preserve: keep the failed package and its build receipt, copy the log slice beside them
   (privately), and note the load ID. A later fix does not overwrite them.
7. Name the smallest experiment that distinguishes the top two candidate causes, and what result
   would confirm each.

## Do not

- Retry the load "to see if it happens again" before steps 1 to 6; the second run overwrites the
  evidence of the first.
- Resend a command that reported `delivery_uncertain`.
- Claim a leak, a limit or a fix from a pattern search or a screenshot.
- Blame the mod for a host OOM kill, an OpenAssetTools tool crash or a pre-existing menu Lua error.
- Fix anything in this playbook.

## Stop conditions

- The class and first error line are identified with the phase and the diff since the last good
  load: the diagnosis is complete; hand the fix to `add-a-script.md` or `port-a-feature.md`.
- The evidence is ambiguous after step 5: stop and say so, with the two candidates and the
  experiment from step 7. Do not assemble confidence out of guesswork.
- Any further game command needs the user's go.

## Report

1. What failed and what it was doing (phase, first error line, load ID, package hash).
2. The most likely mechanism, with what the evidence proves separated from what you infer.
3. Whether the original failure is preserved and where.
4. What would confirm the cause and the smallest change that tests it.
