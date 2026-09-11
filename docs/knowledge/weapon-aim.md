# Weapon aim: donor tuning, outlier templates and the two places aim breaks

"Blurry when I aim down sights" was reported four times across the authoring workspace's first
weapon port and reappeared on the second, and it was never a texture. Aim breaks in two independent
places: the `ads*` field block inherited from a native weapon, and the geometry that lines the
sights up. Words: `CONTEXT.md` (Normal and PAP, donor, gate). Steps:
`docs/playbooks/port-a-bo3-weapon.md`.

## Donor aim tuning does not transfer

A donor game's aim fields are authored against its own aim model. Carrying them over gave the
the pistol port kept a 0.2 s aim-in and 0.25 s aim-out against the native 0.1 s, 0.3 spread on an aimed shot
where a native pistol is pinpoint at zero, and more than double the aimed view kick (65/50, and
100 on the upgraded form, against 45/25).

The rule: take no `ads*` field from the donor. Only the aim animation clips are the ported
weapon's own; the whole block comes from the native template.

## A native template can still be an outlier

Picking a native weapon of the right class is not enough. The M1911, the obvious template for a
pistol port, is an outlier twice over among stock zombies weapons:

| Field | M1911 (the template) | Ordinary peer (five-seven) |
| --- | --- | --- |
| Aim depth of field | 5 to 13, the strongest of any pistol; 29 stock zombies weapons checked have none at all | 0.1 to 10 |
| Zoom field of view | 65, equal to the default field of view of 65, so aiming zooms nothing | 60 (the judge and kard also use 60) |
| Aim-in time | inherited 0.1 s (the port's 0.2 s came from the donor) | 0.125 s |
| Zoom-in fraction | 0.42 | 0.6 |

A port built on it faithfully inherits a gun that blurs the whole scene and does not zoom, which
is exactly what "zoom in is still blurry" describes. Swapping the whole `ads*` block to
`fiveseven_zm` fixed it. The second port confirmed the rule from the other side: its SMG block (idle 2,
zoom 50, depth of field 2 to 2.7, spread 0) is ordinary among SMGs and stayed whole.

The rule: diff an inherited field block against the distribution of each field across the game's
weapons of the same class before trusting it. Build the distribution from the target map's own
zone listings (extract the WeaponDefs of the class and compare), and treat a value that is unique
or at an extreme — the M1911's depth of field, its zoom equal to the default field of view — as a
warning rather than a preference.

The field names above are the WEAPONFILE keys `adsZoomFov`, `adsZoomInFrac`, `adsDofStart` and
`adsDofEnd` as OpenAssetTools exports them; compare the same keys across the class.

## The geometry half: the sight tag against `tag_ads`

After the field block is native, aim can still fail because the sights are not where the engine's
aim reference is. The second port spent four builds with "no iron sight picture at ADS" for this reason:
the donor's sight tag against the native viewhands' `tag_ads` alignment convention. The engine
owns the camera roots (`tag_view`, `tag_ads`, `tag_cambone`) and weapon animation leaves must not
key them (`zombies-contracts.md`); the gun's sight geometry has to end up on that aim reference.

The fix is geometric: capture the sights if they are a separate model
(`weapon-attachments.md`), merge them at their bone's bind transform, then solve the aim end pose
so the rear aperture and the front post land on the camera axis, with the rear aperture at a
native gun's measured rear-sight distance (10.671 units forward of the eye was measured on the
native SMG used as the timing donor) and the timing from that native clip.

## Do not derive the view model camera offline

One build of the second port rigid-moved the assembly about 12 units on an assumed camera and the gun was
invisible at ADS. The end pose is solved from the sight geometry against a native gun's measured
aim end; offline you project the packaged clip and the packaged model to verify the sight points
land on the axis. The projection verifies the work; it is not a substitute for the native
measurement. Do not invent an eye transform or translate the gun by an assumed offset.

## Check before install

- No `ads*` field came from the donor; only the aim clips are the port's own.
- The complete `ads*` block is compared against the same-class distribution built from the
  target map's own zone listings, and every outlier value is either replaced or recorded as a
  deliberate choice.
- For a pistol: aim depth of field is a native-normal range (none, or about 0.1 to 10), zoom
  field of view is below the default field of view, aimed spread is zero, and the aim-in time is
  about 0.1 to 0.125 s.
- Both forms carry the checked block, each checked against its own native peer.
- The merged sight geometry is recorded, the aim end pose is solved so the rear aperture and
  front post sit on the camera axis, and the rear-sight distance comes from a native weapon's
  measured aim end.
- The packaged clip and model were projected offline before install; on-screen ADS feel remains
  a player check.
