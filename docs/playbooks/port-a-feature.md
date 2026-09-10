# Port a feature into a T6 mod

Bring a feature (a script behaviour, a weapon, a HUD element) from another mod or title into a
recipe-based T6 mod, on a clean base, with every offline gate before the first load.

## Preconditions

- The destination mod has a recipe and builds (`first-build.md`).
- The foundation is chosen and named (`docs/knowledge/foundations.md`): base plus this one
  module is the whole test package.
- You have read `docs/knowledge/zombies-contracts.md` for the feature's class, and the class
  preflight playbook exists for it (`preflight-weapon-rig.md`, `preflight-hud-text.md`) or you
  will write the checklist first.
- The source is on disk. For a fastfile source, `pat ff inspect <source.ff> --output <out> --json`
  lists what it ships; `pat ff extract <source.ff> --types <types> --output <out> --json` writes
  the assets out. For a saved BO3 capture, `pat weapon catalog` inventories it.

## Steps

1. Inventory the feature completely before writing anything: scripts, models, animations,
   textures, sounds and their aliases, effects, strings, and every helper the scripts call. Write
   the list into the module's README; it is the checklist for step 4.
2. Resolve every call against what T6 will have loaded: engine builtins on that VM, includes
   from the base, and your own scripts. Anything unresolved is a port task, not a compile
   warning. Compile each script alone (`add-a-script.md` step 2).
3. Convert assets to T6 formats through the toolkit's routes: `pat model inspect` then
   `pat model convert --format cast` for models and animations (with `--rig` for an
   animation-only file), `pat audio convert --format wav --rate 48000 --channels 1` for sounds,
   `pat image convert` for textures. Inspect the converted artifact, not the exit status: bone
   names, hierarchy and counts for a rig; sample rate and channels for audio.
4. Run the class preflight checklist and record each item's result in the module's README.
5. Write ownership and limits into the scripts before the first test: per-player and global caps,
   cleanup for every lifecycle event, a generation identity for workers.
6. Build the module alone on the foundation and verify:
   ```sh
   pat project build <module>/project.json --output ../jobs/<module>-build-NNN --json
   pat project verify ../jobs/<module>-build-NNN/receipt.json --inputs --output ../jobs/<module>-verify-NNN --json
   ```
   Proof: `ok: true` both; `rawfiles_verified` matches the recipe.
7. Read the package back for the engine-facing facts the linker does not check: the asset names
   the engine will ask for, the weapon or alias fields you set, and anything the preflight
   named:
   ```sh
   pat ff inspect ../jobs/<module>-build-NNN/packages/mod.ff --output ../jobs/<module>-inspect-NNN --json
   ```
8. Package and install per `package-and-install.md`; loading needs the user's go.

## Do not

- Start from an installed composition or a "latest" folder; start from the foundation.
- Skip the preflight because the conversion "succeeded"; every rig that failed in game had
  converted cleanly.
- Infer an engine limit from one observation and design to it as a budget; count what the whole
  composition uses.
- Present a normal-only weapon as a finished port; normal plus PAP is the unit.
- Carry the previous base's acceptance to this build.

## Stop conditions

- An unresolved call or an unconvertible asset with no T6 equivalent: stop and report exactly
  which, with what would be needed.
- A preflight item fails: stop, fix, rerun that item; do not build around it.
- Build, verify and preflight all pass: the offline part is complete. Every step after that
  touches the game and needs the user's explicit go per command.

## Report

State separately: **offline verified** (receipts, package hash, preflight results); the
foundation identity; what was converted and what was adapted (native substitutes, retimed clips);
what remains unverified until a load (registration pressure, appearance, audio playback, cleanup
under lifecycle events); and that nothing is **installed**, **loaded** or **accepted**.
