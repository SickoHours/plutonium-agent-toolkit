# Dual-wield ports: the left slot, clip ownership and resident audio

A dual-wield T6 weapon is two definitions the engine pairs at runtime: the right-hand primary
and an internal left-hand helper. The authoring workspace's Black Ops III revolver pair failed
three separate ways after clean compiles, readbacks and an accepted right-hand form, and each
failure reproduces on any dual-wield port. This page gates steps 4 and 7 of
`docs/playbooks/preflight-weapon-rig.md` and the audio step of
`docs/playbooks/port-a-bo3-weapon.md`. Words: `CONTEXT.md` (Normal and PAP, donor, gate).

## 1. The left helper keeps its native inventory type

The native left-hand definition (`m1911lh_upgraded_zm` is the stock example) carries
`inventoryType dwlefthand` and is named by the right-hand form's dual-wield field. A port that
starts from a native template and then applies one shared "art and inventory" adaptation to all
three definitions overwrites that field with `primary`. The engine then grants the helper as a
second selectable weapon that consumes its own slot: the player picks up the pair and sees two
guns in the cycle. Hiding the helper's menu row cannot fix an engine slot type.

Rule: adapt each definition independently. Right and normal stay `primary`; the left helper
keeps `dwlefthand` and the dual-wield relationship. The helper's assets stay packaged, since the
pair fires through it. Read `inventoryType` back per definition after the link; the accepted fix
changed exactly one field and nothing else.

## 2. Each clip keys only what it owns

Native weapon clips leave the engine-owned roots (`tag_view`, `tag_ads`, `tag_cambone`) to the
engine, and BO3 aim clips are one-bone tracks on `tag_torso`. A retargeting encoder that
serializes the full pose into every clip breaks both: the arms distort, the gun sits wrong, and
ejected cartridges float, idle included. Three ownership rules were enforced in the encoder and
checked in readback:

- No weapon leaf keys `tag_view`, `tag_ads` or `tag_cambone`.
- An ADS clip keys `tag_torso` only, and the aim displacement is not baked into the aimed firing
  pose a second time.
- A fire or reload clip keys only its own hand branch (or an independent shot poses the other
  hand), so the opposite hand keeps whatever it was doing.

Translations have a separate trap. T6 adds each XModel's local translation to the animation
offset at evaluation, so an encoder that emits already-composed parent-local positions applies
the gun's bind offset twice. Subtract each standalone weapon model's local translation before
encoding and add it back in verification; the offsets come from the packaged gun rigs, not from
the retarget skeleton, whose hand attachment and donor bind frames differ. Viewhand runtime
translation arrays are zero, so hands are not adjusted.

## 3. Keep the pair's own sounds resident

Streaming every layer of a multi-layer gunshot exhausts the streamed-voice pool
(`snd_max_stream_voice`, 10; `engine-limits.md`): shots fade or cut as they overlap, and a
dual-wield pair overlaps constantly. Keep the weapon's own aliases resident under a byte cap,
route ordinary fire through the ordinary gunshot bus, and stream only the large sounds the
rest of the pack already streams.

The donor's dual reload clips carry `clip_out` and `clip_in` mechanical events but no sound
events. Bind the recovered cylinder and shell foley to those frames in both hands (and the
empty-reload hammer event on the right), instead of inventing notetracks the donor never had.
`preflight-weapon-rig.md` step 6 checks every reload slot, left and empty included.

## Report

Per definition: inventory type read back. Per clip: the bones it keys and whether the model
offsets were subtracted. Per alias: resident or streamed, with the resident byte total. Each is
an offline fact; a single selectable primary, both hands firing and reloading, and swap and
down behaviour are what the player verifies.
