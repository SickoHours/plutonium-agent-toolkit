# Port a BO3 Workshop weapon to a T6 map that loads first time

The eight steps that took a Workshop map's starting pistol, both forms, onto a stock T6 map with
a playable spawn on the first load. They specialise `port-a-feature.md` for a donor that lives in
BO3 containers and a running BO3 process; the general playbook's gates still apply. Words:
`CONTEXT.md`. Formats: `docs/knowledge/bo3-workshop-formats.md`. Contracts:
`docs/knowledge/zombies-contracts.md`, `docs/knowledge/foundations.md`.

## Preconditions

- `inspect-a-bo3-map.md` ran: the feature inventory names the weapon, its scripts, models,
  clips, sounds and effects, and a sealed index covers the recovered files and the capture.
- A `pat-grill` round settled the base and map (a stock map needs no DLC base), both forms or
  normal only, the menu route and the acceptance scope.
- A destination module with a recipe that builds alone on the named foundation
  (`first-build.md`, `docs/knowledge/foundations.md`), and the toolkit's `gsc` and `oat`
  backends present (`pat doctor --json`).

## Steps

1. Read the compiled data first. From the decompiled scripts and the weapon tuning tables,
   write down what the weapon does in each form (damage, ranges, ammo, timing, projectile or
   bullet, charge or delay clips, PAP relationship) with the script line for each number.
   Proof: the numbers table in the module README, one source reference per row.
2. Use the target map's own zone listings as the truth for what T6 provides. Read back the
   stock zones the map loads (`pat ff inspect <zone.ff> --output <out> --json` for each: the
   common, patch, code-post-gfx and map zones) and keep the union of asset names as the
   "provided" list. Proof: the listing receipts and the combined list; every reference the
   module does not carry itself must be in it.
3. Pick native templates of the same kind from those zones and extract them: the closest
   native weapon definition for each form, its material, its camo, the native viewhands rig,
   its accuracy graphs, and the native alias rows on the firing, foley and explosion mixers
   (`pat ff extract <zone.ff> --types <types> --output <out> --json`). Proof: the extract
   receipts; the module README names each template beside the field or asset it seeds.
4. Recover the bytes the game does not keep in memory, from the sealed inputs only: audio
   carved as FLAC from the bank at each alias's offset; textures inflated from the XPAK to
   DDS. Proof: a per-file hash list under the sealed index; a prepare step that refuses to run
   when any input hash differs.
5. Convert one asset kind at a time and check each against a readback, not an exit status:
   - Models: decode the captured mesh and skin, rename the weapon attach tag to the native
     pistol's, write the model; check skin weights and skeleton parents equal after readback.
   - Animations: bake the donor curves onto the donor's hands-plus-gun assembly, retarget to
     the native T6 viewhands with a semantic finger map, drop the donor's sleeve bones no T6
     rig has, encode; check the global pose error is below a hundredth of a unit and that
     tracks and notetracks read back equal (`preflight-weapon-rig.md`). A donor clip T6 has
     no slot for (a charge before each shot) is baked in front of the clip that owns it.
   - Weapon definitions: start from the complete native template, then override only the
     fields the donor defines (damage, ranges, ammo, timing, spread, hit-location
     multipliers, a projectile block copied from the native projectile pistol when the PAP
     form is a projectile); keep native FX, icon, tracer, rumble, graphs and melee; check
     every field re-reads equal, timing through a verified millisecond encoder.
   - Audio: FLAC to canonical PCM WAV, each donor alias rebuilt on the native prototype row
     with volume, pitch, distance and priority converted, foley rows on the foley mixer, the
     secondary chain preserved; check every secondary resolves inside the bank and rows re-read
     equal (`preflight-audio-memory.md`).
   - Textures: colour to DXT1, specular to DXT5 with gloss in alpha, normal to BC5 with
     renormalised mips, at the size the native pistol uses; check mip storage equal after
     readback.
   Proof: one conversion receipt per kind with its equality check recorded.
6. Register with one loose server script, not a map patch: guarded by map name and an
   idempotent flag, it includes both forms, adds the PAP relationship, and, for a starting
   weapon, sets the level's start weapon so native spawn logic hands it out; developer-menu
   metadata beside it. No native script edited, no pack namespace. Proof: the script compiles
   alone (`add-a-script.md`) and `preflight-scripts.md` passes.
7. Build with refusal on any gap: link against the loaded stock zones, then require that every
   embedded asset is the module's own or a dependency the linker copied from a loaded zone,
   that no reference is unresolved, and that both definitions, every clip, material, skin,
   alias row and localized string read back equal.
   ```sh
   pat project build <module>/project.json --output ../jobs/<module>-build-NNN --json
   pat project verify ../jobs/<module>-build-NNN/receipt.json --inputs --output ../jobs/<module>-verify-NNN --json
   pat ff inspect ../jobs/<module>-build-NNN/packages/mod.ff --output ../jobs/<module>-inspect-NNN --json
   ```
   Proof: `ok: true` on all three; the inspect listing minus the provided list minus the
   module's own assets is empty. Expect the first link to fail on a missing native dependency
   (an accuracy graph was the one here); add the native file and link again.
8. Install under the user's lock, load through their runner or by their own hand, and read
   the evidence: the console log shows the registration script's init line and no missing
   asset for the module's namespace, the sound bank header loaded, a playable spawn holding
   the weapon, and the PAP form reachable. Then hand the match to the person. Proof: the
   install receipt, the load check, the screenshot, and the log lines quoted in the handoff.

## Do not

- Guess a number, a bone name or a field; every value comes from the donor's compiled data,
  the capture, or a native T6 asset of the same kind.
- Copy fields by prefix from the donor definition onto a T6 one; start from the complete
  native definition and override named fields.
- Compare converted animation bytes raw against the readback; the linker re-sorts
  compression categories, so compare decoded tracks.
- Ship a map patch, edit a native script, or reach for a DLC base for a stock map.
- Call the port done at a clean link, a clean startup or a playable spawn: firing feel,
  reload timing, the PAP machine transaction, co-op and performance are separate facts.

## Stop conditions

- A donor asset with no native template of its kind and no T6 equivalent: stop and report
  which, with what would be needed.
- A reference outside the provided list that no native dependency satisfies: stop; do not
  widen the loads to make it resolve.
- Any readback inequality or preflight failure: stop, fix that item, rerun it.
- Build, verify and inspect pass with an empty unresolved set: the offline part is complete;
  everything after needs the user's go per command.

## Report

State separately: **offline verified** (build and verify receipts, package hash, the empty
unresolved set, every per-kind equality check); the foundation and map; each asset marked
retained, adapted (native substitute, baked charge clip, dropped sleeve bones) or unsupported;
**installed**, **launched**, **loaded**, **playable** as observed with the log lines and the
screenshot named; and what stays unverified until a person plays it (sound and animation
feel, the PAP transaction, other maps, co-op, measured performance). The player's verdict is
separate from all of the above.
