# Compose a pack from declared modules

Build several modules into one mod on a named base and map, and prove the result read back. The
formats are in `docs/MODULES.md`; the words in `CONTEXT.md` (module, composition, profile).

## Preconditions

- Every module has a `project.json` recipe that builds alone (`first-build.md` or
  `add-a-script.md`) and a `module.json` declaration beside it that names the base and maps it
  was built for, its dependencies, conflicts and resource contract.
- The base and the one map for this pack are decided (`pat-grill` settles them). Modules that do
  not declare that base are rebuilt and tested there first; a declaration is extended after a
  test on that base, never before.
- A composition recipe named `<base>_<feature>_<stage>` lists the module directories and, if
  you have measured, a budget.
- Backends `gsc` and `oat` are installed (`pat doctor --json`).

## Steps

1. Plan the composition without running a backend:
   ```sh
   pat module plan <pack>/composition.json --output ../jobs/<pack>-plan-001 --json
   ```
   Proof: `ok: true`, `result.modules[]` in dependency order, `result.resource_totals`,
   `result.backends_available: true`. A refusal names the exact cause: a missing dependency, a
   declared conflict, a module not declared for this base or map, two modules producing the same
   file, or a budget exceeded. Fix the declaration or the selection; do not edit a module's
   `bases` to make a plan pass.
2. Build it:
   ```sh
   pat module build <pack>/composition.json --output ../jobs/<pack>-build-001 --json
   ```
   Proof: `ok: true`, `result.mod_ff` equals `packages/mod.ff`, `result.rawfiles_verified`
   equals the number of scripts plus rawfiles across every module; `receipt.json` has
   `status: succeeded`.
3. Run the preflights for every class any module touches: `preflight-scripts.md` always;
   `preflight-weapon-rig.md`, `preflight-hud-text.md`, `preflight-audio-memory.md` when those
   assets are in the pack. Proof: each gate recorded as pass, fail or unknown against the
   `mod.ff` hash. Audio reservation and effect unions are counted for the whole pack, not per
   module.
4. Verify the receipt when the pack will be reused:
   ```sh
   pat project verify ../jobs/<pack>-build-001/receipt.json --inputs --output ../jobs/<pack>-verify-001 --json
   ```
   Proof: `ok: true`.
5. Install and hand off per `package-and-install.md`, using the composition's `name` as the
   folder. Loading is a game operation and needs the user's go.

## Do not

- Compose modules that were never built alone on this base; a pack is where interactions are
  tested, not where a module earns its first verdict.
- Raise a budget to make a plan pass; a budget is a measured decision.
- Build two packs into the same `--output`; every job gets a new directory.
- Rename `mod.ff` or the install folder to reuse an old verdict; a pack's acceptance is its own.

## Stop conditions

- `plan` refuses: the message names the module and the rule; change the selection or the
  declaration honestly and plan again.
- `backend_failed` on build: read the step log the receipt names; the failing module is the one
  whose script or asset the log names.
- Step 4 passes: the pack is **offline verified**. Everything after is `package-and-install.md`.

## Report

State separately: **offline verified** (the plan and build receipts, the `mod.ff` hash, the
modules and versions in dependency order, the resource totals); the preflight results per gate;
**installed / launched / loaded / playable / accepted**: not done, or done with the evidence.
Say which modules had been accepted alone on this base before, and that the pack's own verdict is
still to be earned.
