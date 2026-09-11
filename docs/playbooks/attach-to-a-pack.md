# Attach a module to a pack

Add one module to an existing pack, on the base and map the pack is for, and prove the result
read back. The pack stays untouched; the result is a new composition and a new profile. Words:
`CONTEXT.md` (base pack, seed, decision). Formats: `docs/MODULES.md`.

## Preconditions

- The pack is on disk as a directory with `composition.json` (transparent), or as a folder with
  `mod.ff` and its soundbanks (opaque). For an opaque pack, `pat module declare <pack>/mod.ff
  --output <out> --json` has written `seed.json` and a draft `module.json` beside the package,
  and you filled `bases` and `maps` from what the pack was actually tested on.
- The module declares the pack's base and map under `bases` and `maps`. If it does not, this
  playbook does not apply yet: build the module alone on that base and map first
  (`port-a-feature.md`, `package-and-install.md`), earn its verdict, extend the declaration.
- The base's zones the linker needs are on disk (`loads`), and the base's zone header lines are
  known (`zone_header`); a previous composition on the same base has both.
- Backends `gsc` and `oat` are installed (`pat doctor --json`).

## Steps

1. Write the composition, named `<base>_<feature>_pack`, with the pack as the base member and
   the module (and its dependencies) as members:
   ```json
   {"schema": 1, "name": "b2_enhanced_penetrator_pack", "base": "b2", "map": "zm_factory",
    "modules": [{"path": "../dlc5-enhanced", "role": "base"}, "../penetrator", "../penetrator_registration"],
    "loads": ["../base/common_zm.ff", "../base/zm_factory-inspect.ff"],
    "zone_header": [">level.ipak_read,common_zm", ">level.ipak_read,zm_factory"]}
   ```
   Proof: the file exists and `name` follows `<base>_<feature>_<stage>`.
2. Plan:
   ```sh
   pat module plan <pack>/composition.json --output ../jobs/<pack>-plan-001 --json
   ```
   Proof: `ok: true`, `result.base_member` is the pack, `result.modules[]` lists the pack's
   modules first, then the attached module in dependency order. A refusal names the rule: a
   base or map the module does not declare, a missing dependency, a declared conflict, a seed
   whose hash changed.
3. Resolve every row under `result.undecided`. Each names the collision (a file target, a
   weapon or string name, a seed asset), the modules involved and how to record the owner. Add
   one `{"collision": …, "owner": …, "reason": …}` per row under `decisions` in the composition,
   or rename a target in the module you own. Plan again. Proof: `result.undecided` is empty and
   every recorded decision appears under `result.decisions` with `resolution: recorded decision`.
4. Build:
   ```sh
   pat module build <pack>/composition.json --output ../jobs/<pack>-build-001 --json
   ```
   Proof: `ok: true`, `result.rawfiles_verified` equals the scripts and rawfiles across every
   recipe module, `result.seed_roots_verified` equals the roots across every seed, `receipt.json`
   has `status: succeeded`. `packages/` holds `mod.ff` and every seed's soundbanks.
5. Run the preflights for every class the attached module touches (`preflight-scripts.md`,
   `preflight-weapon-rig.md`, `preflight-hud-text.md`, `preflight-audio-memory.md`). Audio
   reservation and effect unions are counted for the whole pack. Proof: each gate recorded as
   pass, fail or unknown against the `mod.ff` hash.
6. Verify and install per `package-and-install.md`, copying the soundbanks beside the package
   into the profile folder. Loading needs the user's go.

## Do not

- Edit the pack's own files, or copy its profile folder and add to it; the pack is a member,
  and the result is a new profile.
- Edit a module's `bases` or `maps` to make step 2 pass; a declaration grows by receipts.
- Record a decision you did not think about; the reason field exists so the next agent knows why
  the pack's HUD won.
- Attach a module whose seed is `private` and not on this machine; ask its owner for the package
  or plan around it.

## Stop conditions

- Step 2 refuses for base or map: stop, and qualify the module there first.
- Step 3 leaves a collision you cannot decide (two weapons registering the same name from two
  packs you do not own): stop and report it; do not pick at random.
- Step 4 passes: the pack is **offline verified**. Everything after is `package-and-install.md`.

## Report

State separately: **offline verified** (the plan and build receipts, the `mod.ff` hash, the
base member, the modules in order with `recipe` or `seed`, the decisions recorded and why, the
resource totals); the preflight results per gate; **installed / launched / loaded / playable /
accepted**: not done, or done with the evidence. Say that the pack's own verdict on the base and
map was earned before, and that the new composition's verdict is still to be earned.
