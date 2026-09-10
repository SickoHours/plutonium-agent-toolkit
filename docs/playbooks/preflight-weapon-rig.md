# Preflight: weapon rig and animations

Run before the first package of a weapon whose first-person model or animations were converted
from another title. Every item is a check that has failed in a real game after a clean
conversion; the numbered list is the gate, not a suggestion.

## Preconditions

- The converted model and every animation clip exist as files the toolkit can inspect
  (`.cast`, `.gltf`, `.glb`, `.fbx`, `.obj` or `.blend`).
- Blender and the Cast add-on are installed (`pat dev setup --only blender cast --json`) or
  `PAT_BACKEND_BLENDER` points at a Blender that has Cast.
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
   one donor) is a blocker until retargeted.
3. Reconstruct the runtime transform convention. T6 adds the weapon model's local translation to
   animation offsets; derive offsets from the standalone packaged weapon, subtract them before
   encoding, and never subtract hand bind positions or apply an offset twice. Evaluate idle,
   ADS, fire, equip and reload poses with the offsets applied; a floating cartridge or distorted
   arm at idle is this item failing.
4. Confirm animation-tree ownership: no weapon leaf keys `tag_view`, `tag_ads` or `tag_cambone`;
   the aim layer touches `tag_torso` only; a one-bone ADS donor is not expanded to a whole pose.
5. Retime clips to the destination rate with `pat model retime --fps <n>` when the donor rate
   differs, then re-inspect; keep every pose and keyframe.
6. Validate every reload slot (including left and empty reloads) has sound notetracks that
   resolve to loaded aliases; a clip with none plays silently.
7. Compare the weapon definition field by field with its native counterpart: inventory type per
   hand, shared ammo group and cap, impact type and projectile physics, animation and sound alias
   names. Write the differences down; each is intentional or a bug.
8. Record all seven results in the module README with the inspect receipt paths.

## Do not

- Count bones from the standalone weapon mesh and call it the assembly.
- Take a clean `model convert` as proof of the rig; it proves the file converted.
- Verify a roundtrip against itself using the same wrong convention; compare against the native
  reference pose.
- Build the package before items 1 to 7 have a recorded result.

## Stop conditions

- Any item fails: stop, fix, rerun that item. A failing bone count is a mesh partition or
  attachment task, never an engine-limit patch.
- All items pass: continue with `port-a-feature.md` step 6.

## Report

State the bone count of the assembly, the hierarchy result, the offset convention used and how it
was verified (numerical, image), the retime applied, the reload sound result, and the field
differences from the native weapon. Then say **offline verified** and that appearance in game is
**not observed**.
