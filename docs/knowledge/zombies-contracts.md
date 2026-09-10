# Zombies feature contracts: what the engine holds you to

Numbers marked **measured** were hit on a real T6 install; the others are working rules from
ports that failed and were repaired. Treat a limit as a fact about that observation, not a
universal budget, until you measure it in the composition you are shipping.

## Weapons

- **A weapon is normal plus Pack-a-Punch.** Finished means a real upgraded weapon definition with
  the purchase relationship, upgrade camo, PAP sound and appropriate damage and ammo, and the
  player accepted both forms. A normal-only weapon is a milestone, not a port.
- **Inventory type is per hand.** A dual-wield pair's left definition keeps the native
  `dwlefthand` inventory type; overwriting it with `primary` creates a selectable "left helper"
  that consumes a second slot. Verify one selectable primary for the pair.
- **Shared ammo groups collide.** Unique ammo and clip names do not isolate `sharedAmmoCapName`.
  A temporary item that inherits a native group with cap zero conflicts with a native item using
  cap one during startup. Give each temporary item its own group and cap.
- **Projectile weapons start from their native counterpart.** Copying `proj*` fields is not
  enough; `impactType`, penetration, sentient flags and surface bounce live outside them. Compare
  against the complete native weapon (a rocket pistol used `grenade_explode`, the copy kept
  `bullet_small`).
- **Box membership is separate from registration.** Adding a definition to the weighted pool does
  not make a visible box preview; PAP forms stay out of ordinary rolls.
- **Mesh and rig limits.** The assembled first-person model (arms, weapon and every attachment,
  including ones inherited from a native template) must stay under the engine's bone cap;
  **measured**: 160 bones triggers a DObj error and ends the match. Count the assembly, not the
  standalone mesh. See `docs/playbooks/preflight-weapon-rig.md`.
- **Animation-tree ownership.** Weapon animation leaves must not key the engine's camera roots
  (`tag_view`, `tag_ads`, `tag_cambone`). The native aim layer owns `tag_torso` only.

## HUD and text

- **Font scale at or above 1.0.** T6 renders HUD text with a scale below 1.0 enormously
  oversized (**measured**, reproduced twice). Clamp every `fontscale` to `[1.0, 1.15]` even when
  a mockup asks for smaller type.
- HUD elements need an allocation pool that is actually visible in the composed client; a
  server-side allocation success and a local element count do not prove visibility.
- Menu D-pad navigation must not activate carried equipment; a held Select must not carry into a
  nearby pickup after the menu closes.

## Effects, fields and pools

- **Projectile effect union.** One composition's projectile FX set is held at 39 of a 40-entry
  gate with one spare (**measured** as a load failure at the gate). Moving effect calls into
  scripts does not remove rendering pressure.
- **Actor and world network fields** are separate budgets from each other and from host memory.
  An actor client-field set that is out of space fails during registration of a *native* field,
  not the new one. Account for the complete loaded composition, including the map's own fields,
  before adding bits.
- **Entity grammar.** Map entity strings need whitespace between quoted tokens; a parser that is
  more forgiving than the engine passes what the engine rejects.

## Audio

- **Sound bank count and reserved bytes.** An aggregate load failure was observed near 32 sound
  assets (**measured** once; a concern, not a per-mod budget). Eleven banks reserved 128 MiB of
  sound data in one composition; streaming large samples losslessly freed most of it. Check the
  whole map-plus-mod reservation, not a new feature's delta.
- Native streamed FLAC uses 1,024-sample blocks; encoders must set and check it. Decoded PCM
  equality does not prove audible playback; listen.
- Reload and mechanical animations need sound notetracks resolved to loaded aliases; an imported
  clip with none plays silently.
- Ten stream voices are the saved client default; several concurrent shot layers streamed at once
  can exhaust them. Keep critical one-shots as loaded PCM.

## Acceptance scope

Record acceptance against the exact package hash, map, base and player count. "Der Riese solo,
normal and PAP accepted" says nothing about other maps, co-op or a later base. Untested maps,
co-op and performance stay listed as untested. A feature also keeps a route in whatever developer
menu the composition uses, so testing stays repeatable.

## Performance gate, when a test is authorized

Compare the same workload against the accepted baseline: idle, ordinary combat, worst intended
simultaneous use. Report frame-time p50, p95 and p99 in milliseconds, not average FPS. After each
effect's longest lifetime plus one second, owned live resources return to baseline. Twenty
equip/use/replace cycles plus down, revive, death, respawn, menu and disconnect cases; then a
representative soak. A crash, pool exhaustion or sustained growth blocks acceptance regardless of
percentages.
