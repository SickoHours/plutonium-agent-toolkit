# Black Ops III Workshop containers: what an agent can read on Linux

A BO3 Workshop map is the richest donor for a T6 port: its weapons, perks, enemies and scripts
already run on a Zombies engine one generation newer than T6. This page records what its files
are and how much of them can be read offline on Linux with tools a modder already has, so the
question "what does this map contain and how does it work" is answered from the mod's own
compiled data before any port is designed. Words: `CONTEXT.md` (donor, lead, sealed donor).
Steps: `docs/playbooks/inspect-a-bo3-map.md`. Every fact here was measured on one Workshop item
on Arch Linux with BO3 under Proton; sizes vary per map, formats do not.

## The files a Workshop item ships

| File | What it is | Readable offline |
| --- | --- | --- |
| `zm_<map>.ff` | The fastfile: scripts, weapon definitions, FX, string tables, rawfiles and the map itself, serialized as one zone | Yes when unencrypted (below); the zone is a serialized asset graph, not a file system, so names and rawfiles are recoverable and structured assets are not |
| `en_zm_<map>.ff` (one per language) | Localized strings and the names of sound aliases | Yes, same decompressor |
| `zm_<map>.xpak` | Images and meshes, compressed, with a plaintext index at the front | The index yes; the payloads need a decoder for each block format |
| `snd/all/*.sabl`, `*.sabs` | Sound banks: loaded and streamed, magic `2UX#`, version 15 | Headers and name table yes; each entry is a FLAC stream at its recorded offset |
| `zone/*.ff` for shared assets | The same fastfile format | Same rules |

## The fastfile

- Header magic `TAff0000`, a version word at offset 8 (`0x251` for current mod-tools output),
  the compression algorithm at byte 13 (`0` none, `1` and `2` zlib), an encryption flag at byte
  15, and the declared decompressed size at offset `0x90`. Workshop maps built with the public
  mod tools are unencrypted; a set encryption flag means the offline route stops.
- After a `0x248` byte header come blocks, each with a 16 byte header (compressed length, plain
  length, aligned length, and its own offset, which must equal the reader's position); a block
  with plain length zero pads to the next 8 MiB boundary. Concatenating the inflated blocks
  gives the zone. Refuse a block whose declared lengths do not fit, whose zlib stream does not
  end exactly at the plain length, or whose offset field disagrees with the position; a reader
  that skips these checks reads garbage as assets.
- Compiled scripts sit in the zone as serialized script-parse-tree records: two runs of eight
  `0xFF` pointer sentinels around a four byte length, followed by the script name and the
  compiled bytes. Carving by that pattern recovers every `.gscc` and `.cscc`; a bound on the
  count and on each length keeps a corrupt zone from producing millions of files.
- The community decompiler that also compiles T6 scripts decompiles these with the T7 game and
  PC platform flags. Custom function and variable names appear as `_id_` followed by a hash
  (FNV hashes the public tables do not know); string literals, numbers, asset names and every
  engine API call are readable, which is what a behaviour port needs. Expect a small number of
  scripts to fail to decompile; note them and move on.
- A regular-expression pass over the zone for `*_zm` weapon names, `specialty_*` perk ids, FX
  paths and rawfile names gives the roster of what the map registers before anything is decoded.

## The XPAK

- The index is plaintext records in the layout the open BO3 asset reader documents: name, type
  (image, mesh, probe volumes and a few others), offset, compressed and decompressed sizes,
  and for images the format and dimensions. Parsing it lists every image and mesh name in the
  map with no decoding; a map's mesh names say which weapons and characters were ported and
  from where, because porters keep origin prefixes.
- Payloads are LZ4 blocks. Images are block-compressed DDS once inflated (BC1, BC4, BC5, BC7);
  meshes are engine buffers that need the model schema to make sense of. Keep the index as the
  offline inventory and defer payload decoding to a port.

## The sound banks

- Version 15 banks carry a name table, so each alias resolves to an entry offset. The entry at
  that offset begins with a FLAC signature; carving the entry's recorded byte count from there
  yields a playable FLAC with no transcoding (the next entry's offset is only an upper bound;
  `bo3-sab-audio.md` has the carve table). Loaded banks (`.sabl`) hold the short sounds a weapon
  needs; streamed banks (`.sabs`) hold music and long voice lines.

## What only the running game holds

Structured assets (weapon definitions, model skeletons and skinning, animation curves,
materials) are pointer graphs the engine rebuilds in memory; they are not recoverable from the
zone bytes with a general tool. Reading them means reading the loaded game once, read-only,
under the contract in `docs/playbooks/inspect-a-bo3-map.md`: BO3 under Proton is an ordinary
Linux process, and the same user can read its memory through `/proc/<pid>/mem` when the kernel's
ptrace attach check allows it (Yama `ptrace_scope` 0 or 1 for a process you own, and the process
dumpable; the receipt host had scope 1 and needed no change). Where the host denies it, the
capture is not available and nothing here says to relax the scope. The asset-pool table and
string-table addresses are properties of one executable build and must be probed and verified
before a byte is trusted. The saved result is a
`bo3-page-capture-v1` manifest with hashed 4096 byte pages, the format `pat weapon catalog`
inventories (`docs/WEAPONS.md`).

## Sizes to expect

A large Workshop map on this machine: a 350 MB fastfile inflating to roughly 870 MB of zone,
about a hundred compiled scripts, a 9.5 GB XPAK indexing tens of thousands of image and mesh
records, and 3,000 sound entries. That scale is why a whole-map port is not a T6 project and a
module-by-module port is: T6's budgets (`engine-limits.md`) admit one weapon family or one
perk at a time, each built alone on a named foundation.

## Content and terms

A Workshop map's assets are the map author's and, for ported weapons, the origin games'. The
inspection above reads them for study; nothing read this way is redistributable unless the
author's terms say so, and a port that carries their bytes stays on the machine that made it
(`prior-art.md`, "Content and terms"; a `private` distribution in `docs/MODULES.md`).
