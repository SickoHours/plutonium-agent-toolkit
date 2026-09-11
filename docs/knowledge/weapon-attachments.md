# Attachment models: a BO3 weapon's sights may not be in the gun

The authoring workspace's second BO3 weapon port spent four builds treating "no iron sight picture at ADS" as
an aim-clip problem. It was not: the sights are a separate attachment model that BO3 mounts at
runtime, so a capture of the weapon model alone yields a barrel with no sights, and no aim clip
can put a sight picture on geometry that is not there. This page gates the model conversion step
of `docs/playbooks/port-a-bo3-weapon.md` and is read before any aim work (`weapon-aim.md`).
Words: `CONTEXT.md` (donor, sealed donor, assembly, preflight).

## The sights are a second model

- A BO3 weapon's model carries mount bones; ported rigs in the donor carry `ja_ads_attachment`
  and `def_c_*` bones for exactly this. The sight or optic is an `attach_*` model placed on the
  mount bone at runtime.
- In the worked port the sight was `attach_<gun>_sight_on_vm` (one bone, `def_c_sight_on`) plus
  a reflex dot quad and a side display quad, and the upgraded form's optic was another
  `attach_*_optic_*_vm`. The sight alone added about 4,100 vertices.
- Attachment models are resident only while the weapon is held. Capture with the weapon
  equipped, per form, and seal the capture like any donor input. The first capture did not have
  them because they are not in the weapon's own model; the second, with the weapon held, found
  them.

## Finding the attachment

| Step | What to read |
| --- | --- |
| Donor rig | The captured gun's `def_c_*` bones and a `ja_ads_attachment` bone are the sign that BO3 mounts something there at runtime; the base view model carries no sight geometry of its own |
| Name convention | For each `<gun>_vm`, list the mod's `attach_*` models whose name contains the same family stem — `attach_<gun>_sight_on_vm`, `attach_<gun>_optic_*_vm` |
| Bones | The gun's `def_c_*` bones name the mount points and the optic families; `ja_ads_attachment` is the shared mount the idle clip can pose |
| World model | World and dropped variants of the same attachments exist and are needed for the world model, not only the first-person one |

When the attachment rows were not captured with the first pass, the name convention above is
what found the models; capture the candidates and keep the ones the weapon's mount bones name.

## Merging at the donor's bone convention

- Fuse each attachment into the T6 model at its bone's bind transform: re-express its vertices
  in the gun's model space and weight them to the gun ROOT, not to the mount bone.
- Weighting to the mount bone is wrong because the idle clip can pose it: the upgraded gun's
  idle holds `ja_ads_attachment` at a constant 90 degrees, and geometry weighted under it landed
  about 9 units to the left of the gun.
- Keep the donor's `hideTags`: it names the folded irons to hide under an optic, which is what
  the donor does.
- Solve the aim end pose from the merged geometry (`weapon-aim.md`), never by adjusting fields
  to compensate.
- Readback: the added vertex count, exact skeleton parents and zero weight error; and the whole
  assembly (hands, gun, sights, optics and any inherited attachments) still under the 160-bone
  limit (`zombies-contracts.md`).

## Reticles, lenses and the display shader

- A reticle is not a lit surface. Clone the native game's reflex reticle material (the engine's
  glowing-dot-on-a-lens material) and give the clone the donor's reticle colour map; the engine's
  detail-noise image can stay. Where the donor's dot image was absent from its own packages, the
  native reticle image was kept instead.
- The optic body and lens go through the ordinary lit path: colour to DXT1, specular to DXT5
  with gloss in alpha, normal to BC5, at the native optic's texture size.
- A donor on-gun readout (an ammo counter) is driven by a BO3 display shader. T6 has no
  equivalent material input and no script route to drive a weapon surface at runtime, so that
  quad can only ship as a static rendition, or not at all; the HUD still counts.

## Check before install

- For every view model, the `attach_*` models named after it and the optic families its
  `def_c_*` bones name are listed, and the donor's attachment rows agree where they were read.
- The attachment models were captured with the weapon held (both forms, view and world) and the
  capture is sealed and hashed.
- Each attachment is fused at its bone's bind transform and weighted to the gun root; readback
  records the added vertices, exact skeleton parents and zero weight error.
- The donor's `hideTags` is carried, and the merged rear aperture and front post centres are
  recorded for the aim solve.
- Reticle quads use a clone of the native reticle material with the donor's colour map; optic
  surfaces use the native lit-material template at the native optic's texture size.
- A display-shader readout is static or absent; nothing claims a live on-gun counter.
- The whole assembly stays under the 160-bone limit.
- The packaged clip and model were projected offline; the on-screen sight picture remains a
  player check.
