# Weapon camo: how a T6 `weaponCamo` asset renders, and the four ways a port gets it wrong

These facts were paid for on the authoring workspace's two BO3 weapon ports to a stock T6 Zombies
map, where the Pack-a-Punch camo took four rejected builds. Words: `CONTEXT.md` (Normal and PAP,
donor, preflight). Contracts: `zombies-contracts.md` ("A weapon is normal plus
Pack-a-Punch"). Steps: `docs/playbooks/port-a-bo3-weapon.md`.

## What the asset is

A T6 `weaponCamo` asset is an ordered list of `camoMaterials` slots. A slot holds materials, and
each material carries:

| Part | Meaning |
| --- | --- |
| `materialOverrides` | pairs of `baseMaterial` (a material on the model) and `camoMaterial` (the replacement) |
| `shaderConsts[0..1]` | the pattern's UV tiling |
| `useColorMap`, `useNormalMap`, `useSpecularMap` | which maps the camo material supplies |

A weapon definition names one table in its `camo` field. The override is the whole mechanism: a
table repaints only a gun whose materials the override names, so a native table cloned unchanged
does nothing at all to a port.

## Slot geometry

- A stock map's tables carry four slots; tables from DLC maps carry more (two were read at 13 and
  14), with zombies content in slots 3, 8 and 12.
- A Pack-a-Punched zombies weapon renders slot 3 in every stock table checked.
- The camo option index is 1-based: index 0 is no camo and index *i* selects
  `camoMaterials[i - 1]` (measured by cycling indices 0 to 3 through the developer menu on a
  stock table). Setting that index on a held weapon at runtime is what cleared the gun, so the
  accepted design never sets it (below).

## One weapon per camo

Changing a held weapon's camo at runtime cleared the gun on three builds. `updateweaponoptions`,
the call Origins makes on its nesting dolls, did not rebuild a held primary's view model: a
tactical grenade is not evidence about a primary. Re-giving the weapon with
`GiveWeapon(name, 0, options)` is the native loadout path, but the accepted build does not use
it. What held up was one weapon per camo: each variant is its own definition with its own table,
only the Pack-a-Punch slot filled, exactly like every stock zombies gun. No option index is ever
set, so the unresolved index rule cannot bite, and the developer menu chooses the weapon instead
of the camo.

## The four ways a port gets it wrong

| Way | What the player reports | The offline check that catches it |
| --- | --- | --- |
| The cloned table still targets the template's material | "the camo does nothing"; no PAP look | Read the camo asset back; assert every `materialOverrides.baseMaterial` is a material the ported model carries |
| The template's `shaderConsts[0..1]` tiling is inherited | "the camo doesn't look good"; the pattern is huge or blotchy | Measure both models' UV density and scale by the ratio; record densities and result |
| `useColorMap: false` on a detailed gun | "it's blurry when I aim"; panel lines vanish under tiled noise | Ship slots both ways; record which blends the gun's own colour |
| A static or colourless technique for an animated look | "it doesn't look animated"; a grey specular surface | Read the technique's inputs and constants; embed and read back its images |

The first failure: a cloned `camo_m1911` left the port's surfaces untouched because its override
named the M1911's material. The second: measured UV density was 0.0897 on the M1911 and 0.0446 on
the port, a ratio of about 2, so the inherited tiling rendered at double size; scaling by that
ratio was confirmed better. The third: stock zombies entries set `useColorMap` false, so the
camo's colour replaces the gun's albedo; on a detailed gun that reads as blur after aiming. The
fourth: a stock map's load carried only two camo techniques, and the animated one (Diamond's
sparkles) has no colour input — its five maps are a detail normal, a sparkle map, a warp map,
specular-and-gloss and radiant — so artwork fed to it only produces a grey specular surface. An
animated technique from a zone the map does not load (the Buried glow technique) does scroll two
maps over time and does take a colour map. It can be imported with that zone loaded at link time
only, kept out of the runtime "provided" set so everything taken from it must embed, and its
technique set and images checked in the package readback.

## Check before install

- Every `materialOverrides.baseMaterial` in every used slot names a material the ported model
  actually has; the camo asset reads back from the linked package with that override.
- `shaderConsts[0..1]` was scaled from measured UV density on both models
  (`sqrt(sum of UV area / sum of world area)`), and both densities and the ratio are recorded;
  no native tiling was carried unchanged.
- Each slot's `useColorMap` is a recorded choice, and at least one slot preserves the gun's own
  colour when the detail matters.
- Every animated slot uses a technique with a colour input and scroll constants; the imported
  technique and its images were embedded and read back from the package.
- The slot the Pack-a-Punched form renders (slot 3 in every stock table checked) is filled, and
  extra slots above the stock four are deliberate.
- The accepted design sets no camo option index: one weapon per camo, so nothing in the build
  depends on the 1-based index mapping.
