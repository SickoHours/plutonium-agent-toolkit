# GSC and CSC scripts

## Two virtual machines

T6 runs two script VMs. Server scripts (`.gsc`) own game rules, entities, weapons and most mod
logic. Client scripts (`.csc`) own client-side effects, HUD fields and anything that must run per
client. They have separate builtins and separate helper libraries; a function that exists on one
side may not exist on the other, and a same-named helper on the other side does not make a
server builtin resolve. Compile server and client scripts separately (`-i server` or `-i client`;
the toolkit infers it from the suffix) and check each against its own side.

## Where scripts live in a mod

The engine loads `scripts/zm/<name>.gsc` from the mod's fastfile as a rawfile, for every Zombies
map. A map-specific script sits under `maps/mp/zm_<map>.gsc` in the map's own fastfile. A loose
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

## Iterating

`map_restart` reruns the loaded scripts and is the fast loop for script logic. It does not reread
the fastfile: after a rebuild, reinstall and `reload-mod`. A compile plus a clean startup is
cheaper than a gameplay pass and must be reported as the cheaper thing.
