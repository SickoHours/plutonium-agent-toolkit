# Preflight: weapon rig and animations

Run before the first package of a weapon whose first-person model or animations were converted
from another title. Every item is a check that has failed in a real game after a clean
conversion; the numbered list is the gate, not a suggestion.

## Preconditions

- The converted model and every animation clip exist as files the toolkit can inspect
  (`.cast`, `.gltf`, `.glb`, `.fbx`, `.obj` or `.blend`).
- Blender and the Cast add-on are installed (`pat dev setup --only blender cast --json`).
  `PAT_BACKEND_BLENDER` may point at another Blender, but the Cast add-on is always loaded from
  the toolkit's own `backends_dir/cast`, so `--only cast` is required either way.
- The native T6 weapon you are basing on is known, and its definition has been extracted from a
  base fastfile (`pat ff extract ... --types weapon`), so fields can be compared.

## Steps

1. Inspect the assembled first-person model, not the standalone mesh:
   ```sh
   pat model inspect <weapon>.cast --output ../jobs/<weapon>-inspect-NNN --json
   ```
   Proof: `result.before.objects[]` lists the armature and meshes; count the bones of the
   *assembly* (character arms, the weapon and every attachment, including ones a native template
   adds). The engine bone cap is a hard failure (**measured**: 160 bones ends the match). Record
   the count.
2. Check the hierarchy and names against the destination's hand variant and weapon root: bind
   matrices, weights and parent chains. A parent mismatch on shared bones (eleven were found in
   one donor) is a blocker until retargeted. For a native `weaponType=melee` weapon, evaluate the
   model at `tag_knife_attach` below `j_wrist_le`, not at the firearm attachment
   `tag_weapon`. If the clip was authored for `tag_weapon`, solve the melee tag relative
   to its actual parent: `inverse(world(j_wrist_le)) * world(desired_grip)`. Check the
   packaged attachment against the intended grip through idle, attack, equip, put-away,
   sprint, crawl and dive. A preview using the firearm tag can hide this fault while
   the game draws only a small piece of the blade between the hands. Retain the native
   hand tracks and events when adapting movement clips; record position and orientation
   errors from the packaged animation, and still inspect a fresh in-game frame.
3. Reconstruct the runtime transform convention. T6 adds the weapon model's local translation to
   animation offsets; derive offsets from the standalone packaged weapon, subtract them before
   encoding, and never subtract hand bind positions or apply an offset twice. Evaluate idle,
   ADS, fire, equip and reload poses with the offsets applied; a floating cartridge or distorted
   arm at idle is this item failing. Test the preview's skin transform at bind pose:
   it must reproduce the unposed mesh in the chosen coordinate system. An inverse
   bind matrix already includes its model-to-joint conversion; applying another
   coordinate rotation after it can make the preview disagree with the game.
4. Confirm animation-tree ownership (`docs/knowledge/weapon-dual-wield.md` for a pair): no weapon leaf keys `tag_view`, `tag_ads` or `tag_cambone`;
   the aim layer touches `tag_torso` only; a one-bone ADS donor is not expanded to a whole pose.
5. Retime clips to the destination rate with
   `pat model retime <clip>.cast --fps <n> --output ../jobs/<weapon>-retime-NNN --json` when the
   donor rate differs, then re-inspect the output; keep every pose and keyframe.
6. Validate every reload slot (including left and empty reloads) has sound notetracks that
   resolve to loaded aliases; a clip with none plays silently.
7. Inspect every converted clip's event tail: no `rmbnt#` rumble event survives conversion and every
   `sndnt#` event resolves to an alias the module or the base carries; a survivor ends the match on
   first play (`crashes.md`, rumble row).
8. Compare the weapon definition field by field with its native counterpart: inventory type per
   hand, shared ammo group and cap, impact type and projectile physics, animation and sound alias
   names. Write the differences down; each is intentional or a bug. Enumerate
   animation slots from the destination schema (`WFT_ANIM_NAME` in T6), not a
   suffix heuristic: `dtp_in`, `dtp_loop`, `dtp_out` and their `dtp_empty_*`
   counterparts do not end in `Anim`; neither do `fireAnimLeft` and
   `meleeAnimEmpty`. For each normal and empty dive phase, verify the packaged
   weapon points to the converted clip and measure its attachment relative to
   the intended wrist. Checking only converted files can miss an unconverted
   slot that still resolves successfully from the base.
9. Check material inputs with the packaged geometry: lit triangles need nonzero UV
   area so tangent-space generation has valid directions. Sampling one palette point
   at all three corners makes every UV difference zero; use a small UV rectangle
   inside the solid-color tile instead. Specular RGB and gloss alpha are separate
   controls; an opaque-only texture does not author gloss. Inspect the result under
   both indoor and outdoor lighting rather than accepting a flat offline preview.
10. Record all ten results in the module README with the inspect receipt paths.

## Do not

- Count bones from the standalone weapon mesh and call it the assembly.
- Take a clean `model convert` as proof of the rig; it proves the file converted.
- Verify a roundtrip against itself using the same wrong convention; compare against the native
  reference pose.
- Build the package before items 1 to 9 have a recorded result.

## Stop conditions

- Any item fails: stop, fix, rerun that item. A failing bone count is a mesh partition or
  attachment task, never an engine-limit patch.
- All items pass: continue with `port-a-feature.md` step 6.

## Report

State the bone count of the assembly, the hierarchy result, the offset convention used and how it
was verified (numerical, image), the retime applied, the reload sound result, and the field
differences from the native weapon. Then say **offline verified** and that appearance in game is
**not observed**.
