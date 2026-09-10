# Saved BO3 weapons: catalog and plan

`pat weapon catalog` and `pat weapon plan` are offline checks over a **sealed donor**: a private
directory of assets captured from Black Ops III, indexed by SHA-256. They never launch or attach
to a game, never run a converter, and never copy asset bytes anywhere. They exist so that the
inputs to a weapon port are verifiable before anyone spends hours converting.

## Donor receipt

```json
{
  "root": "D:\\donors\\shadows-capture",
  "index": "index.json",
  "index_sha256": "<64 hex of index.json>",
  "map": "zm_zod",
  "pid": 4242,
  "start_ticks": "133700000",
  "adapter_index": "native/index.json",
  "adapter_index_sha256": "<64 hex>"
}
```

`adapter_index` and `adapter_index_sha256` are optional; omit both when the donor has no native
adapter capture.

`index.json` is `{"files": {"<relative path>": "<sha256>", ...}}` covering every file the capture
depends on, including the capture manifest and every 4096-byte snapshot page named
`<16 hex>.bin`. The manifest is the `bo3-page-capture-v1` record produced by the capture tool:
`map_before`, `map_after`, `pid`, `start_ticks`, `captured_bytes`, `pages`, and `models`,
`animations`, `weapons` arrays.

```powershell
pat weapon catalog D:\donors\shadows.json --capture capture-03/manifest.json --output ..\jobs\catalog-001 --json
```

Catalog re-hashes every indexed file, checks page count and size, checks that map and process
identity did not change during capture, rejects duplicate asset names and writes `library.json`.
Bounds: 16384 indexed donor files and 2 GiB per donor, 2048 adapter-index files, 16000 snapshot
pages (each page is an indexed file), 4096 records per asset kind, 2 MiB recipe and index JSON,
16 MiB capture manifest.

## Recipe

Schema 1 needs exactly these fields:

| Field | Meaning |
| --- | --- |
| `schema`, `source_engine`, `target_engine` | `1`, `t7`, `t6` |
| `family`, `adapter` | lowercase family ID and the owning project's converter name |
| `hands_model` | captured hand rig model |
| `variants` | `normal` and `pap`, optional `left` |
| `required_files` | donor-relative media the port depends on |
| `keep_loaded_prefixes`, `resident_cap_bytes` | resident sound namespaces (`family_` prefixes) and a cap of at most 16 MiB |
| `menu_route` | where the weapon appears in the user's test menu |

Each variant has `role`, `source_weapon`, `target_weapon`, `view_model`, `world_model`, `clips`
(at least `idle`, `fire`, `reload`), `native_template`, `inventory_type` (`dwlefthand` for
`left`, otherwise `primary`).

```powershell
pat weapon plan .\recipes\ar.json --library ..\jobs\catalog-001\library.json --output ..\jobs\plan-001 --json
```

Plan re-verifies the donor against the library (a changed donor fails with `input_changed`),
then reports `declared_inputs_available`, `missing` per asset kind, and which native templates
the owning converter must supply. A plan that succeeds with missing assets is a useful result: it
tells you what to capture next.

## What this is not

There is no generic BO3-to-T6 weapon converter in this toolkit. The recipe names an `adapter`;
a project that owns that adapter runs it. The `required_gates` list in every plan names the
things a real port has to prove afterwards: relative-track binding, packaged model offsets,
native camera and ADS ownership, hand tracks, reload sound events, complete native weapon
fields, left-slot handling, resident audio cap, memory promotion, package read-back, and a
normal and Pack-a-Punch playtest. `plan` proves none of them.
