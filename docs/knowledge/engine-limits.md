# Engine limits observed in T6

Each limit below was hit in a real build. A number here is what the engine reported or what a
fix had to satisfy; it is not a specification and does not transfer to other maps, clients or
compositions without measurement. Unknown occupancy stays unknown.

| Resource | Observed bound | How it was hit | How to count it |
| --- | --- | --- | --- |
| Assembled model bones (DObj) | 160 per assembly | A bow counted 125 for its own model; inherited staff attachments pushed the assembly over | Character hands + weapon + every attachment the template inherits, per view |
| Actor client field set | Filled by existing composition | Three new bits for two weapons | Sum every actor field across map, mod and global scripts; other sets (world, player, scriptmover) are separate |
| Projectile FX registrations | 40 | Composition sat at 39 with one spare | Union of projectile FX across the full loaded set |
| Sound assets | 32 | Aggregate of map plus mod banks | Count banks and assets across the whole load |
| Streamed audio voices | 10 (`snd_max_stream_voice`) | Multi-layer gunshot fully streamed | Layers per shot times overlapping shots |
| HUD font scale | Minimum 1.0 | Scales 0.75 to 0.95 rendered enormous | Every `fontscale` assignment |
| Sound bank preload reservation | Tens to hundreds of MiB | Eleven preloaded banks at 134 MiB; "Out of memory" at map load | Bank sizes from OAT inspection plus fastfile virtual block |
| Streamed FLAC block | 1,024 samples | 4,096-sample blocks played glitchy | Actual emitted codec headers, not encoder source |
| Scripts per recipe | 128 | Toolkit bound | Recipe rows |
| Source tree size per recipe | 4,096 files, 2 GiB | Toolkit bound | Declared trees |

## Reading the table honestly

- A bound observed on one map with one client build is evidence for that scope. Do not raise a
  claimed limit, patch an executable, or import a donor's expanded-limit assumptions.
- Free host memory, disk space and fastfile size on disk are not on this table.
- Where a limit came from a toolkit bound, changing the toolkit changes the bound; where it came
  from the engine, no toolkit change helps.
