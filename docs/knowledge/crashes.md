# Crashes: reading the evidence before naming a cause

## Where the evidence is

`storage/t6/main/console_zm.log` is the Zombies client's console log. It holds script errors,
asset load failures, the reason the server shut down, and Lua UI errors. `pat game check-load`
counts new error lines in it after a load; read the lines themselves for the cause. The log is
appended across sessions: use timestamps and the load you issued to find the right slice.

Beyond the log: the exact package hash that was installed, the map, the base, the player count,
and the timestamp of the failure. A crash without those is an anecdote.

## Classify first

| Class | What it looks like | Where the cause is |
| --- | --- | --- |
| Script error | `script error(s)`, `Unresolved external: <name> with N parameters`, a script runtime error line | The script: a helper that did not resolve, a builtin that is not exposed, a wrong parameter count. Fix the script, not the engine |
| Load refused | `too early to loadmod!`, a map that returns to the menu with `SV_Shutdown: hostquit` | Sequencing: a mod command while a match runs, or a match started from the console rather than a lobby (`plutonium-t6.md`) |
| Fixed pool exhausted | An error naming a set that is "out of space" (actor client fields), the DObj bone error, an asset registration failure at entry N | The complete loaded composition exceeded a pool: count the map's and base's use plus yours (`zombies-contracts.md`) |
| Allocation failure | An "Out of memory" dialog while loading, hunk or virtual-address failures | The package's reserved bytes (sound banks first); free host RAM is not the constraint |
| Renderer or driver | The process dies with no script line; a GPU or driver message | Outside the mod; record and separate |
| Host OOM kill | The process vanishes; the OS log shows an OOM kill | Host memory; not a bug in the mod or the game |
| UI Lua error | `LUI_ERROR`, a `.lua:<line>` index error on a menu transition | Often a pre-existing menu path, unrelated to the mod being tested; preserve it separately |
| Havok Script Panic | The engine's own script VM panic | Rare; usually a corrupt or mismatched compiled script |
| Shape marker | A routine engine line that names a shape which will fail or has failed, not a fault line by itself | The script whose shape it names; read the marker to find the suspect, then a separate condition (a missing pass, a count) to decide whether it actually failed |

An OpenAssetTools core dump is a tool crash, not a game crash. One clean startup is not a
crash-free game. A passing offline suite before a crash is normal: most failures that reach a
player passed every offline check first.

## Signatures seen after clean compiles and readbacks

Each row is a build that passed compile, link and readback and then produced this line. The
cause beside it is the one that was found and fixed, not the only possible one. After each fix a
regression that consumes the failed artifact was added; the preflight playbooks collect them.

| Log text | Cause found | Fix that worked |
| --- | --- | --- |
| `COM_ERROR (6): **** Unresolved external : "get_players" with 0 parameters` at map load, then `SV_Shutdown` | Module script re-cut without its stock `#include` lines; the call compiled but could not link | Restore the includes (or qualify the call); `module plan` `externals:` rows catch it offline |
| `Unresolved external: precachemodel with 1 parameters` | Server-only builtin called from a client script | Remove the client call; keep the server precache |
| `Unresolved external: setclientfield with 2 parameters` | The include that exports the method was missing | Add the direct include; resolve helpers per instance |
| `bad animtree token: '{'` | Animation-tree leaves wrapped in an anonymous brace block | Emit a bare leaf list |
| Server registered `<tree A>` where client registered `<tree B>` | Registration inserted at different positions on server and client | Register at the same relative position on both sides |
| `Trying to assign 1 bits for netfield <name> but Client Field Set actor is out of space.` | New actor field bits in an already full composition | Remove the bits; reuse existing FX through owned entities |
| `Could not load default asset 'defaulttracer' for asset type 'tracer'.` | Tracer reference registered before its default | Preserve parent registration order; require the default first |
| `dobj for xmodel '<name>' has more than 160 bones` | Assembly counted one model, not hands plus attachments | Count the full assembly; remove inherited attachments |
| `G_ParseSpawnVars: closing brace without data` | Whitespace between quoted tokens lost in an entity edit | Preserve token separators and every original key |
| `Exceeded limit of 32 'sound' assets` | Aggregate sound assets across map plus mod | Merge banks; it is an aggregate-load concern |
| `Exceeded limit of 1024 'rawfile' assets` at mod selection | The map's zones plus the mod embedded more rawfiles than the pool; model-export GLBs and source WAVs rooted as rawfiles beside the compiled assets filled it | Mark authoring inputs `deliver: false` in the recipe (or drop them from the seed's roots), keep the compiled assets; `pool:rawfile-assets` in the plan names the largest contributors |
| `no free ipak slots loading pak <path>.ipak with N index entries` | The mod's zone header read more image banks than the client had slots for after its startup set | Read only the banks the pack's images need, or consolidate donor textures into one pack-owned bank; `pool:image-bank-slots` counts the header lines |
| `BG_AnimStateDef_Parse: state '<state>' ... not found in its animtree` | Two members each replaced the map's animation state and tree files with their own additions; the copy that loaded named a state the tree did not carry | One shared service module owns the map's `.asd`/`.atr` pair and merges every member's state blocks onto the native base; members depend on it and ship no copy |
| `Client and server clientfield registrations don't match` | Two causes carry this line. The halves registered at different points: a server registration ran before native init while the client half ran from a loose `scripts/zm/*.csc`, which executes after the client's own fields are registered. Or the pack registered on one VM only: `_zm_powerups::add_zombie_powerup` registers the toplayer field its client-field-name argument names (the ninth argument on the server, the second on the client) on whichever VM is passed one — a call without that argument registers nothing, which is why the point drops and `full_ammo` need no client half — and where the map's client include list leaves the powerup out the client half never runs, so the field exists on the server alone | Either remedy closes it. Register on both VMs at the same point: redirect the map script's `_zm::init` import on server and client to an adapter that registers, then chains to native init. Or ship the missing half as a loose `scripts/zm` script — a `.csc` for a server registration, a `.gsc` for a client one — that registers the same name with the same width and version (`registerclientfield("toplayer", <name>, 1, 2, "int", undefined, 0, 1)` is what `add_zombie_powerup` emits: Int, 2 bits, version 1), running after its own VM's native rows exactly as the other half runs after that VM's, so both sides append the field in the same order. Either way the registration must be **unconditional** on both sides: guarding one half on state only that VM holds (a weapon in `level.zombie_weapons`) inverts the mismatch on the loads the guard excludes instead of curing it. `clientfield-symmetry` in a composition plan refuses a one-sided or one-sidedly-guarded pack offline |
| `cannot cast undefined to bool` in `_visionset_mgr::monitor`, `_zm_powerups::powerup_hud_monitor` or `_audio::monitor_player_sprint`, then an access violation | A per-frame read of per-player state that only the connect hook writes, for a player that never received `on_player_connect` on a DLC5 foundation; the vision manager, the power-up HUD and the sprint audio monitor all read it | Backfill the per-player state through the manager's own arrays from a guard script before the read runs; the crash report's last-error field names the read, not the cause |
| `last gsc error message 'undefined is not an array, string, or vector'` in the Plutonium crash text; seen in `_visionset_mgr::monitor`, then an access violation | The VM read an undefined value as a container. Where it was found this was the same missing per-player state as the cast above, but the line does not name its site, so any script can raise it | Read the `last gsc pos` line beside it to name the script and function first; where the site is a per-player state read, backfill it as for the cast above |
| `last gsc pos 0x<addr> <script>::<function>` in the Plutonium crash text (`plutonium-r*.txt`) | Not a defect of its own: it names the script and function the VM was in when it died. The fatal GSC line is written only to the crash text, never to the console log, so a matcher that reads the console tail alone sees nothing | Read `plutonium-r*.txt` as a log source beside the console; pair this line with the `last gsc error message` line above it to name both the failure and its site |
| Access violation in `include_zombie_weapon` / `precacheitem` during map weapon registration | An imported WeaponDef overrode a weapon the map's own registration list precaches | Keep the map's native definitions for weapons it already registers; the pack adds new weapon names instead of overriding native ones |
| `COM_ERROR ... Unresolved external` naming a stock script the target map does not carry (`_zm_perk_divetonuke` on Beta 2 Der Riese) | The module was cut against a map that carried the script; the target's zones do not | `map-scripts:<script>` rows in the plan refuse an include or qualified call into a path the target map lacks; port the dependency or leave the member out |
| `BG_AnimStateDef_Parse ... referenced missing <anim>` | Animation-state entry without a compiled tree reference | Add the reference to both compiled aitypes |
| `Could not play rumble asset '<name>' because it was not registered and loaded` | A converted donor clip kept its compiled event tail; a `rmbnt#` entry names a rumble the donor game had and T6 does not; the match ends (`SV_Shutdown`) on first play | Rewrite the event tail at conversion: drop `rmbnt#` events, resolve `sndnt#` events through the weapon's notetrack sound map or drop them; poses and frames untouched |
| `Unable to find client function: "init" in "scripts/zm/<name>"`, then `******* Linking to default stub function instead ******` | Not a fault on its own: the client VM calls `main()` and `init()` on every loose mod `.csc` and links a no-op stub for whichever is absent. One passing load printed 32 such lines, including the server twin for about twenty `main`-less scripts that work | Read it as a *shape marker* only — a `.csc` that defines `main()` but no `init()` is doing its work in the early pass (`gsc.md`). Scope the matcher to `scripts/zm`: every healthy load also prints the same line for `"soundNotify" in "clientscripts/mp/_dogs"` |
| The same line **with zero `CSC Executed` lines in the slice** (a healthy load prints 14, or 18 when the pack carries two client halves of its own); the crash text has an empty `last gsc error message` and a `last gsc pos` naming a per-frame monitor loop | A client `main()` that does work. It runs in the early pass, before the client's own `_zm` rows exist, and the whole client-script pass dies there before the first `CSC Executed` line. Observed: `include_weapon` called from `main()` for weapon names the target map never registers, reaching native `addzombieboxweapon` — the registration-time twin of `box-weapon-not-found`. No script error is raised, so neither crash-text field names the site | Leave `main()` empty and do the work in `init()`, and check that every weapon name the script includes exists on the target map. `csc-main-body:<target>` rows in `module plan` and `project plan` refuse the shape offline. Do not name a script from `last gsc pos` when `last gsc error message` is empty |
| `ERROR: sound bank failed to load <name>.all. You have a build problem.` | Not established, and the row says so. Seen four times in one session for four of one pack's banks while the pack's other banks in the same folder loaded; every named `.all.sabl` was beside `mod.ff` under exactly that name, and the same four had loaded from that folder the day before. The session's log slice is gone, so what separated those four is unknown | No repair is recorded for this line yet. Read the load's own console first: a bank that loads prints `Adding prioritized sound bank "<name>.all" from zone "mod"`, `Attempting to load soundbank <name>.all`, `Soundbank <name>.all has load asset bank <name>.all.sabl` and `SOUND Header load success ... <name>.all.sabl`. Check that every bank the zone names sits beside `mod.ff` under exactly that name, then count the pack's banks against the 32 `sound` asset limit |
| "Out of memory" dialog at map load | Preloaded sound-bank reservation plus the fastfile's virtual block | Stream large samples losslessly; keep critical one-shots loaded |

Of the two rows above, `csc-main-only` (class `shape-marker`, regex
`Unable to find client function: "init" in "scripts/zm/([a-z0-9_]+)"`) is now in the shipped
signature data; it arrived with this export. `client-script-pass-died` is a *pairing* — that marker
plus zero `CSC Executed` lines in the slice — which the line-oriented matcher cannot express, so it
stays documented here only and the generator skips it rather than deriving a row from its wording.
The `Exception Address` that came with them is one observed address on one client build and stays a
corroborating field, never the key.

The table's promise — a cause that was found and fixed — holds for every row but one.
`sound-bank-failed-to-load` records a line whose cause was never found: the evidence rotated away
before the diagnosis ran, and the two obvious explanations, a bank missing from the mod folder and a
bank under the wrong name, were both checked and ruled out. It is here so the next occurrence is
recognised rather than rediscovered. Read a match as "read the console and the mod folder", never as
"this is what happened".

The rows are data too: `src/plutonium_agent_toolkit/knowledge/crash-signatures.json` holds each
as a regex with its class, cause and fix, and `pat knowledge signature --log <slice> --json`
matches a slice line by line with the timestamp prefix stripped. A slice with no match is a line
nobody has recorded yet, not a clean load; record it here in the same change as the fix.

## Correlate

- Which load produced it: the load ID and the `check-load` result before the failure.
- What changed since the last good load: package hash, base, loose files under `raw/`.
- Whether it happened at startup, at first use, at replacement, at expiry or at disconnect.
  Each phase has its own cleanup path, and a stale worker from a previous life is a distinct
  cause from a first-use failure.
- Whether the same log line appears in a playable session too. Weapon and package not-found
  lines that also appear in a working session are noise.

## Report

1. What failed and what it was doing (the phase, the log line, the load ID).
2. The most likely mechanism, separating what the evidence proves from what you infer.
3. Whether the original failure is preserved: the failed package, its receipt and the log slice
   stay; a later success does not erase them.
4. What would confirm the cause, and the smallest change that tests it.

If the cause is ambiguous, say so. Never claim a leak, a fixed crash or a crash-free game from a
pattern search, a screenshot or an unrelated passing suite. Diagnosis reads; it does not fix.
`docs/playbooks/diagnose-a-crash.md` is the finite version of this page.

Composition checks front known signatures: `pool:sound-assets` refuses a counted floor over
32 banks; `pool:projectile-fx-registrations` needs exact FX union evidence and otherwise remains
uncounted; `pool:actor-client-field-set` remains uncounted without a numeric bound.
`symbols:<script>` retains compiler-reported unresolved externals/errors before linking;
compiler success does not establish runtime export availability.
`clientfield-symmetry` groups every clientfield the pack's staged `.gsc` and `.csc` scripts
register, directly or through a helper such as `add_zombie_powerup`, by set and name; a name
registered on exactly one script VM fails before the engine ever compares the two lists.
