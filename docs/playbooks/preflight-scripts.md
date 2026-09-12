# Preflight: scripts

Gates to run on a build's output before its first install when any GSC or CSC script was added
or changed. Every gate below caught a build that compiled, linked and read back cleanly and then
failed at map load.

## Preconditions

- A build receipt with `status: succeeded` and its `mod.ff` hash.
- The extracted readback under the build's output (`project build` writes it) or a fresh
  `pat ff extract <mod.ff> --types rawfile --output <new dir> --json`.

## Steps

1. Resolve builtins per instance. For every call in every server script, the name and arity
   resolve against the server export list or an included script; the same for client scripts
   against the client list; `pat knowledge builtin <name> --json` gives the VMs and argument
   counts shipped native scripts call a name with. Proof: no unresolved name remains and the two
   lists were never pooled. Failure it prevents: `Unresolved external: <name> with N parameters`.
2. Check includes. Every `#include` names a script present in the package or in a dependency
   load the game also loads. Proof: each include resolves. Failure: a method that exists in
   the engine but is exported through an include the script omitted.
3. Check animation-tree shape. Every `.atr` rawfile is a bare list of leaves with unique names,
   and every leaf names an animation present in the package. Proof: no brace-wrapped block
   exists. Failure: `bad animtree token: '{'`.
4. Check registration order. Server and client register the same animation trees and script
   movers in the same relative order; a new registration is inserted at the same position on
   both sides. Proof: the two ordered lists match. Failure: server registered one tree where
   the client registered another.
5. Check network fields. New client fields are counted against the full loaded set for their
   set (actor, world, player, scriptmover), including map and global scripts. Proof: the
   count with the new bits is recorded and below the observed capacity, or the bits were
   removed; `pat knowledge limits --map <zm_map> --json` gives the map's own bits per set as the
   starting number. Failure: `Client Field Set <set> is out of space`.
6. Check cleanup paths. Each resource-owning thread reaches idempotent cleanup on completion,
   cancellation, replacement, down, death, respawn, disconnect and map transition, without
   relying on `endon` or on `waittill_any` for the later events. Proof: each owner has a
   listed cleanup path per event. Failure: stranded HUD, entities or sound loops after a
   life event.
7. Check WeaponDef invariants when the build adds weapons. Each temporary item has its own
   `sharedAmmoCapName`; dual-wield left hands keep `dwlefthand`; adapted projectile weapons
   have `impactType` and non-prefixed physics fields from their native counterpart. Proof: the readback diff lists these fields as intended. Failures: startup cap mismatch; a helper
   weapon that takes a slot; PAP grenades with bullet impacts.

## Do not

- Run the gates on the source tree instead of the readback; the package is what loads.
- Re-run a gate on the same `mod.ff` hash; the first result is the fact, record it.
- Wrap or stub a builtin that does not resolve; report the name and arity instead.

## Stop conditions

- Gate 1 finds a name that neither list exports and no include supplies: stop and report it. Do
  not wrap it or stub it.
- Gate 5 cannot establish the loaded set's occupancy: record it as unknown, not as passing.

## Report

Per gate: pass, fail, or not applicable, against the `mod.ff` hash. Name every builtin that resolved
through an include. Name every unknown occupancy.
