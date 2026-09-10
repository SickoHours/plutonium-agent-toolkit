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

An OpenAssetTools core dump is a tool crash, not a game crash. One clean startup is not a
crash-free game. A passing offline suite before a crash is normal: most failures that reach a
player passed every offline check first.

## Signatures seen after clean compiles and readbacks

Each row is a build that passed compile, link and readback and then produced this line. The
cause beside it is the one that was found and fixed, not the only possible one. After each fix a
regression that consumes the failed artifact was added; the preflight playbooks collect them.

| Log text | Cause found | Fix that worked |
| --- | --- | --- |
| `Unresolved external: precachemodel with 1 parameters` | Server-only builtin called from a client script | Remove the client call; keep the server precache |
| `Unresolved external: setclientfield with 2 parameters` | The include that exports the method was missing | Add the direct include; resolve helpers per instance |
| `bad animtree token: '{'` | Animation-tree leaves wrapped in an anonymous brace block | Emit a bare leaf list |
| Server registered `<tree A>` where client registered `<tree B>` | Registration inserted at different positions on server and client | Register at the same relative position on both sides |
| `Trying to assign 1 bits for netfield <name> but Client Field Set actor is out of space.` | New actor field bits in an already full composition | Remove the bits; reuse existing FX through owned entities |
| `Could not load default asset 'defaulttracer' for asset type 'tracer'.` | Tracer reference registered before its default | Preserve parent registration order; require the default first |
| `dobj for xmodel '<name>' has more than 160 bones` | Assembly counted one model, not hands plus attachments | Count the full assembly; remove inherited attachments |
| `G_ParseSpawnVars: closing brace without data` | Whitespace between quoted tokens lost in an entity edit | Preserve token separators and every original key |
| `Exceeded limit of 32 'sound' assets` | Aggregate sound assets across map plus mod | Merge banks; it is an aggregate-load concern |
| `BG_AnimStateDef_Parse ... referenced missing <anim>` | Animation-state entry without a compiled tree reference | Add the reference to both compiled aitypes |
| "Out of memory" dialog at map load | Preloaded sound-bank reservation plus the fastfile's virtual block | Stream large samples losslessly; keep critical one-shots loaded |

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
