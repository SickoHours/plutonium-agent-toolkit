# Engine limits observed in T6

Each limit below was hit in a real build. A number here is what the engine reported or what a
fix had to satisfy; it is not a specification and does not transfer to other maps, clients or
compositions without measurement. Unknown occupancy stays unknown.

| Resource | Observed bound | How it was hit | How to count it |
| --- | --- | --- | --- |
| Assembled model bones (DObj) | 160 per assembly | A bow counted 125 for its own model; inherited staff attachments pushed the assembly over | Character hands + weapon + every attachment the template inherits, per view |
| Actor client field set | Filled by existing composition | Three new bits for two weapons | Sum every actor field across map, mod and global scripts; other sets (world, player, scriptmover) are separate |
| Projectile FX registrations | 40 | Composition sat at 39 with one spare | Union of projectile FX across the full loaded set |
| Sound assets | 32 | Aggregate of map plus mod banks; 21 per-gum banks on Der Riese's six exceeded it at mod selection (2026-09-14) | Every `.all` bank the loaded zones carry plus every bank the pack ships, each counted twice: the listing shows the `.all` row and the engine opens its localized companion beside it, which no listing shows. Der Riese: 6 banks = 12; 10 pack banks = 20; 32 fits, 33 does not |
| Rawfile assets | 1,024 | Two packs rooted model-export GLBs and source WAVs as rawfiles beside the compiled models and banks; the client refused the mod at selection | Every rawfile in the map's zones plus every rawfile the pack embeds (compiled scripts, animation tables, accuracy graphs, text); authoring inputs count when they are rooted |
| Image bank slots | 16 open image banks | A pack's zone header read six donor banks on top of the client's startup set; the seventeenth open failed with `no free ipak slots` | The client's startup set (twelve on a full retail install) plus every distinct `>level.ipak_read` line the header adds; a bank the zone folder lacks is skipped and costs nothing |
| Streamed audio voices | 10 (`snd_max_stream_voice`) | Multi-layer gunshot fully streamed | Layers per shot times overlapping shots |
| HUD font scale | Minimum 1.0 | Scales 0.75 to 0.95 rendered enormous | Every `fontscale` assignment |
| Sound bank preload reservation | Tens to hundreds of MiB | Eleven preloaded banks at 134 MiB; "Out of memory" at map load | Bank sizes from OAT inspection plus fastfile virtual block |
| Streamed FLAC block | 1,024 samples | 4,096-sample blocks played glitchy | Actual emitted codec headers, not encoder source |
| Scripts per recipe | 128 | Toolkit bound | Recipe rows |
| Source tree size per recipe | 4,096 files, 2 GiB | Toolkit bound | Declared trees |

The table is also data: `src/plutonium_agent_toolkit/knowledge/engine-limits.json` names, per row,
the occupancy field that counts against it, and `pat knowledge limits --map <zm_map> --json`
reports what the zones the engine loads for that map already carry against each row (counts from
listings, decompiled text and WeaponDefs, never runtime pools; `null` stays unknown). A mod's
own contribution is added on top of the map's number, never instead of it.

## Counting image bank slots

A `>level.ipak_read,<name>` header line asks the client to open `zone/all/<name>.ipak`. A name the
folder does not carry is skipped with `ipak file not found` and costs no slot, so counting every
header line is a floor on what the pack spends and an over-count of what the engine charges it.
The difference is real: a composition read four banks beyond the startup set on 2026-09-15
(`lowmip`, `code_post_gfx_zm`, `common_zm`, `zm_factory`) and only `zm_factory.ipak` was on that
machine, so three of the four counted reads opened nothing.

`pool:image-bank-slots` therefore counts every distinct read beyond the startup set unless it is
given evidence: an optional `banks_present` list on a map's row in `knowledge/occupancy.json`,
naming the banks that map's client zone folder carries. With it, a read naming a bank outside the
list becomes its own `not_counted` row — "skipped by the engine, costs no slot" — and is left out
of the count; without it nothing changes, because which banks a stranger's install carries is not
readable offline. The field is optional and absent from the shipped table; only a generator that
measured a real `zone/all` should fill it, and the list is that machine's inventory, not a claim
about anyone else's.

## Reading the table honestly

- A bound observed on one map with one client build is evidence for that scope. Do not raise a
  claimed limit, patch an executable, or import a donor's expanded-limit assumptions.
- Free host memory, disk space and fastfile size on disk are not on this table.
- Where a limit came from a toolkit bound, changing the toolkit changes the bound; where it came
  from the engine, no toolkit change helps.
