# GSC and CSC scripts

This page is T6. On IW5 there is one server VM, the client compiles source itself, and gsc-tool
is a syntax gate only: `iw5.md`.

## Two virtual machines

T6 runs two script VMs. Server scripts (`.gsc`) own game rules, entities, weapons and most mod
logic. Client scripts (`.csc`) own client-side effects, HUD fields and anything that must run per
client. They have separate builtins and separate helper libraries; a function that exists on one
side may not exist on the other, and a same-named helper on the other side does not make a
server builtin resolve. Compile server and client scripts separately (`-i server` or `-i client`;
the toolkit infers it from the suffix) and check each against its own side.

## Where scripts live in a mod

A module script is delivered **loose** as a compiled file under the profile folder,
`mods/<profile>/scripts/zm/<name>.gsc`; the engine logs `Script source "scripts/zm/<name>.gsc"
loaded successfully from raw` and calls its `main()` and `init()`. The same script packed only as
a `rawfile` inside `mod.ff` is **not** executed on stock Black Ops II (observed 2026-09-13: eight
packaged scripts, none executed, no registration prints; the loose copies ran). `module build`
therefore writes every compiled script under `packages/scripts/` beside `mod.ff` as well as into
the zone. `game install-mod` copies only `mod.ff` (and optional soundbanks), never
`packages/scripts/`, so a full install takes a manual second step: after
`pat game install-mod <build>/packages/mod.ff <profile>`, copy the build's `packages/scripts/`
directory **contents** into the profile's `scripts/` directory, so `packages/scripts/zm/<name>.gsc`
lands at `mods/<profile>/scripts/zm/<name>.gsc`. Copy the contents, never the directory itself
into a path that already ends in `scripts/` or `zm/`, or the loose scripts land under
`mods/<profile>/scripts/scripts/` or `.../zm/zm/` and the engine never sees them. A map-specific
script sits under `maps/mp/zm_<map>.gsc` in the map's own fastfile. A loose
global script under the storage folder's `raw/scripts/zm/` loads for every mod, which is how a
shared developer menu is delivered; use that only for tooling shared across mods.

`examples/hello-zm` is the smallest working mod: one server script whose `main()` starts a
thread that waits for players to connect and spawn. Its recipe maps `scripts/hello.gsc` to the
target `scripts/zm/hello_zm.gsc`.

## Compiling

`pat gsc compile <file>` runs gsc-tool in `comp` mode for `t6`, platform `pc`, with the
instance for the file's side. `--includes <dir>` adds a directory searched for `#include` files
and hashes it into the receipt. Decompiling a compiled script uses the same tool in `decomp` mode.

gsc-tool compiles a script that only uses engine builtins with no include files at all. Once a
script calls helpers from the game's own scripts, it needs the includes those helpers come from,
and the *engine* must have those scripts loaded too.

## Traps that compile and fail at load

- **Unresolved external at link time aborts the map.** `COM_ERROR (6): Unresolved external "get_players"
  with 0 parameters` then `SV_Shutdown`; the client exits and reopens its console log, so the
  evidence is in the rotated `console_zm.log.NNN`, not the live file. An unqualified call to a
  stock utility export needs the matching `#include` (`common_scripts\utility`, `maps\mp\_utility`,
  `maps\mp\zombies\_zm_utility`) or a fully qualified call; `module plan` now reports these as
  `externals:` check rows from `knowledge/stock-exports.json`. The include must be on the script's
  own VM: a `.csc` resolves against `clientscripts\mp\_utility` and
  `clientscripts\mp\zombies\_zm_utility`, and no stock client script includes a `maps\...` path.
  **The link signature is the name and the argument count together, and the script's includes are
  the whole scope.** A bare call resolves only against the script's own functions and the scripts it
  `#include`s; nothing else the engine has loaded is reachable without a qualified path. Where two
  stock scripts export one name at different arities the scope decides which you get, so the arities
  are never merged: `get_players` takes no argument in `maps\mp\_utility` and one in
  `common_scripts\utility`, and on 2026-09-15 `qol_instant_nuke` (both included) linked while
  `qol_max_ammo` (only `maps\mp\_utility`) died at `Unresolved external "get_players" with 1
  parameters`. Passing *fewer* arguments than the declaration lists is ordinary and safe — GSC binds
  undefined to the rest, and 564 bare calls in the `patch_zm` decompile do it — so only an excess
  fails. Qualifying a call to the wrong stock script is the same refusal: `register_tactical_grenade_for_level`
lives in `maps\mp\zombies\_zm_utility`, so `maps\mp\zombies\_zm_weapons::register_tactical_grenade_for_level`
does not link. A bare name no export row owns and no builtin witness covers is reported separately as
  `externals-unknown:<script>`, `not_counted`: the toolkit cannot refuse on ignorance, but that name
  is where an unresolved external hides, as `register_zombie_damage_callback` did for
  `blast_furnace` before `maps\mp\zombies\_zm_spawner` was in the table.
- **Unresolved external.** A helper that compiled because a name matched, but the engine could not
  find it in a loaded script. `setclientfield` with two parameters lives in `maps/mp/_utility`;
  include it. Resolve every unqualified call against the includes and exports the engine will
  have, including code paths you think are unreachable.
- **A donor method that is not a T6 builtin.** A call that exists in Black Ops 1 or 3 may not be
  exposed by this client (`setanimknob` with four parameters was one). Compilation says nothing
  about builtin availability. Check a native T6 call site before relying on a method:
  `pat knowledge builtin <name> --json` reports the VMs and argument counts shipped Treyarch
  scripts call a name with (`src/plutonium_agent_toolkit/knowledge/builtins.json`); `unknown`
  means no shipped script calls it there, not that it is absent, and a name a script exports
  resolves through that script's include, never through the engine.
- **Server and client registration order.** Network fields (`clientfield`) must be registered on
  both sides in the same order; both sides having the same assets is not enough.
- **`waittill_any` semantics.** The native utility waits for its first event and installs `endon`
  for the later ones, so cleanup after it is skipped when a later event fires. A thread that owns
  resources must not use `endon` in a way that skips its own cleanup; give it one `waittill`
  per event and converge on an idempotent cleanup.
- **Precache in init.** Models, effects and strings a script uses must be precached during
  initialization before the first use.

## Writing scripts an engine will keep running

- Every thread, helper entity, HUD element, effect loop and cached collection has an owner and a
  cleanup path for completion, cancellation, replacement, down, death, respawn, disconnect and
  round or map transition.
- Set per-player and global limits before the first test. Reserve before allocating. Overflow
  falls back to a documented bounded behaviour, never to an unbounded queue of waiting threads.
- Do work per tick that is bounded by design: no whole-collection sorts, string rebuilds, traces
  or `setmodel` every frame unless a measurement justifies it.
- A stale worker from a previous life must not erase a newer worker's fields; carry a generation
  or life identity.

## A ported script still asks which map it is on

A map-specific script guards its own entry: `main()` or `init()` opens with
`if ( getdvar( "mapname" ) != "zm_transit" ) return;`, or the same test against `level.script`, or
an `==` whose `else` returns. On its own map the guard is invisible. Ported to another map the
script still compiles, still links, still loads and still runs — the entry point returns on the
first line and everything after it never happens. Nothing reports this: there is no unresolved
external, no missing asset, no console line, and `gsc check` passes, because the script is
correct. It is simply answering a question about a map it is no longer on. The symptom in the game
is a member that is installed and does nothing, which reads like a broken feature rather than a
port that was never finished. A guard may name several maps at once
(`getdvar("mapname") != "a" && getdvar("mapname") != "b"`), which is the same statement over a set.
Read the top of `main()` and `init()` before porting anything, and change the guard to the new map,
widen its set or drop it; `module plan` reads it for you as `map-guard:<script>`, and reads only a
conditional that sits first and returns unconditionally, so a map test further down is still yours
to find.

## Iterating

`map_restart` reruns the loaded scripts and is the fast loop for script logic. It does not reread
the fastfile: after a rebuild, reinstall and `reload-mod`. A compile plus a clean startup is
cheaper than a gameplay pass and must be reported as the cheaper thing.

## Declared function replacements

Call `replaceFunc` from the generated `main()` before the target executes; module registration
runs from generated `init()`. Engine entry points (`CodeCallback_*`, map/gametype main and
`gamemode_callback_setup`) belong to the foundation and cannot be detoured by a module.
One effective registration exists per target, so duplicate declarations are refused rather
than relying on last-registration-wins behavior. Detours clear on fast_restart; load and
re-registration evidence is required again. The literal source scan and generated-entry
readback are offline evidence only; they do not establish runtime detour behavior or gameplay.
