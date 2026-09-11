---
name: pat-port
description: Port a weapon, item or behaviour from a donor game into one T6 Zombies module on a clean base. Use when the user names a donor (Black Ops, Black Ops III, a capture) or asks to "bring over" or "convert" a feature. Runs the rig, script, HUD and audio preflights before the first install.
---

# pat port

A port is a module built alone on a named base from a sealed donor, with every gate that earlier
ports learned run before a person tests it. Words: `CONTEXT.md`. Facts:
`docs/knowledge/other-titles.md`, `docs/knowledge/zombies-contracts.md`,
`docs/knowledge/engine-limits.md`. Steps: `docs/playbooks/port-a-feature.md`; for a Black Ops III
Workshop map as the donor, `docs/playbooks/inspect-a-bo3-map.md` first and then
`docs/playbooks/port-a-bo3-weapon.md` (`docs/knowledge/bo3-workshop-formats.md` has the containers).

## Before the first command

- Prior art searched when no donor was handed over: `docs/playbooks/find-prior-art.md` ran, its
  leads table sits in the module README, and the donor below came from it or from the user.
- Decisions settled in one `pat-grill` round: base, maps, both forms or normal only, donor,
  menu route, acceptance scope.
- Donor sealed: `pat weapon catalog` receipt or an equivalent hashed inventory.
- Base named by foundation id and tag; the module builds on it alone
  (`docs/knowledge/foundations.md`).

## What makes a port different from a build

- Every WeaponDef starts from its complete native T6 counterpart, then art and inventory are
  applied explicitly. Field-prefix copying missed the impact type once; it is not used.
- Rigs are adapted, not encoded. Bone parents are matched to T6 hands, engine camera roots stay
  native, offsets are subtracted before encoding and added back in an independent pose check,
  and every pose in both forms is inspected as an image. `docs/playbooks/preflight-weapon-rig.md`.
- Audio is re-derived for T6 and the emitted headers are inspected, not the encoder's source.
  Reservation is measured for the whole composition. `docs/playbooks/preflight-audio-memory.md`.
- Behaviour is traced in the reference in full (acquisition, offer, hold, expiry, cleanup) before
  an adaptation is written. Copying dimensions and text from a reference missed its timing once.
- Assets are marked retained, adapted or explicitly unsupported. A donor listing is a lead, not
  a payload.

## Ends at

A handoff record: candidate hash, base identity, donor catalog hash, dependencies, checks run,
preflight results, gates pending, menu route and typed test route. Then `pat-review`. Nothing in
this skill touches the running game.

## Report

Offline verified with hash and preflights. Forms built and not built. Maps targeted and not
tested. Installed, launched, playable, captured, accepted: no, each said.
