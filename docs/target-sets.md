# Target sets: maps and survival locations as targets, placements as data

A **target** is one place a composition can be planned, built, checked and played. A stock map
is a target. So is a survival location: a fenced area of a stock map with its own spawns,
machines and route, such as BO2 Reimagined's or T6 QoL's Diner, Power Station, Cell Block or
The Crazy Place. A location is a target, never a module: it does not live in `modules/`, it
appears in the maps filter beside its parent map, and it has its own ledger rows. Diner
evidence says nothing about Town.

Placements (perk machines, Pack-a-Punch, wall buys, GobbleGum sites, rotation slots, fences)
are first-class data drawn from community routes, one **location table** per target and route.
A module
that needs a place declares what it needs, not where; a per-target provider supplies the site
at plan time from the table. Changing a coordinate is a table edit and a new build, never a
source edit in the module.

This page is the public format. A workspace keeps its own tables and its target file and
validates them here with `pat target validate`; coordinates and donor names stay in the
workspace, only the shapes are public.

## The target key

```
<foundation>/<map>/<mode>[/<location>]
```

| Part | Meaning |
| --- | --- |
| `foundation` | A foundation id from the workspace's `foundations/*.json` (`bo2-stock`, `dlc5-beta2`): lowercase letters, digits, dash |
| `map` | The engine's `mapname`: `zm_transit`, `zm_factory` |
| `mode` | The `ui_gametype` group: `zclassic`, `zsurvival`, `zgrief`, `zcleansed`, `zencounter` |
| `location` | The `ui_zm_mapstartlocation` for a location; absent for classic. Lowercase letters, digits, underscore |

A `zsurvival` target always names a location. The key is a path: the target's location table is
`registry/locations/<key>.json`, or `registry/locations/<key>.<route>.json` when a community
route rather than the engine provides it.

## The five target kinds

| Kind | Example | Parent | What the row adds |
| --- | --- | --- | --- |
| `stock-map` | `bo2-stock/zm_transit/zclassic` | none | The map as shipped on that foundation; its vanilla profile is the baseline every module is compared against |
| `stock-location` | `bo2-stock/zm_transit/zsurvival/town` | `zm_transit` | Stock's own survival start locations (Bus Depot, Town, Farm, Nuketown); shipped, not ingested; route `stock` |
| `survival-location` | `bo2-stock/zm_transit/zsurvival/diner` | `zm_transit` | A community-authored fenced area of a stock map with its own spawns, machines and route; the location script is the **route provider** |
| `dlc5-map` | `dlc5-beta2/zm_factory/zclassic` | none | A WaW/BO1 map on the DLC5 usermap foundation; per-map records supply placements |
| `custom-map` | `<foundation>/zm_<custom>/zclassic` | none | A usermap not shipped with the game, on its own foundation descriptor; placements come from its scripts or a measured table |

## Routes: one provider per entry, never a merge

A target names a **place**. A **route** names which provider implements it: `stock` (the
engine's own gamemode table), a community route such as a location script's, or a workspace
adapter id. One entry is one target on one route.

More than one provider often implements the same location — Reimagined and T6 QoL both ship a
Diner, with different machine counts at different sites. Those are two entries with one key and
two tables, never one merged row. The entry id carries the route as a discriminator:

```
<foundation>/<map>/<mode>[/<location>][@<route>]
```

The engine's own route needs none, so a `stock` entry's id is its key. Any other route appends
`@<route>`, whether or not a second provider exists for that target. `pat target list` reports
every such pair under `route_choices`, and `pat target inspect` on a bare key returns
`outcome: route_choice` with the routes rather than picking one.

The choice belongs to the composition, so the refusal lives at plan time: `module plan --target`
on a key two routes provide fails with `invalid_arguments` naming the pair, exactly as two
`replaceFunc` owners of one function are refused. Name one (`<key>@<route>`) and the plan
proceeds. The registry never picks a default.

## The target file: `registry/targets.json`

```json
{"schema": 1, "targets": 33, "entries": [
  {"id": "bo2-stock/zm_transit/zclassic", "target": "bo2-stock/zm_transit/zclassic", "kind": "stock-map",
   "foundation": "bo2-stock", "map": "zm_transit", "mode": "zclassic", "location": null, "parent": null,
   "title": "TranZit", "caption": "ZMUI_TRANSIT_CAPS", "route": "stock", "fence": null,
   "location_table": "registry/locations/bo2-stock/zm_transit/zclassic.json", "placements": 1,
   "vanilla_profile": null, "art": {"preview": "menu_zm_map_transit_blit", "loadscreen": null}, "ledger": []},

  {"id": "bo2-stock/zm_transit/zsurvival/diner@t6-qol", "target": "bo2-stock/zm_transit/zsurvival/diner",
   "kind": "survival-location", "foundation": "bo2-stock", "map": "zm_transit", "mode": "zsurvival",
   "location": "diner", "parent": "bo2-stock/zm_transit/zclassic", "title": "Diner",
   "caption": "ZMUI_DINER_CAPS", "route": "t6-qol",
   "fence": {"zones": ["zone_gas"], "rows": 20, "citations": ["scripts/zm/locs/zm_transit_loc_diner.gsc:49"]},
   "location_table": "registry/locations/bo2-stock/zm_transit/zsurvival/diner.t6-qol.json", "placements": 52,
   "vanilla_profile": null, "art": {"preview": "menu_zm_map_transit_blit_diner", "loadscreen": null}, "ledger": []}
]}
```

| Field | Meaning |
| --- | --- |
| `id` | The key with its route discriminator; unique in the file |
| `target` | The key alone. Optional; when present it must equal the id's key |
| `kind` | One of the five kinds; a location kind has a location in its key, a map kind has none |
| `foundation`, `map`, `mode`, `location` | The key's parts, repeated so a reader need not split the key; they must agree with it. `location` is `null` for classic |
| `parent` | For a location: its map's target on the same foundation, without a location, and that target is in the file. A `survival-location` always names one. A `stock-location` may have `null` only when its map has no classic target at all (Nuketown is survival-only, so it is a top-level row). For a map: `null` |
| `title`, `caption` | Shelf names, taken from the source's own lobby strings |
| `fence` | For a survival location: the zones the route enables, optionally the barriers and disabled spawns, a `rows` count, and `citations` of `"file:line"` in the route provider script (a `source` object naming the file is also accepted). A wiki room label is not a fence |
| `route` | The one provider this entry is for. It must equal the id's `@route`, and an id without one must be `stock` |
| `location_table` | The table this id and route name, `registry/locations/<key>[.<route>].json`, or `null`. A named table must exist at exactly that path |
| `placements` | The table's row count, or `null`. When both are present they must agree, so a stale entry is a defect rather than a quiet disagreement |
| `vanilla_profile` | Path of the generated vanilla profile for this target (Phase 2 "vanilla as modules"); `null` until the extractor exists |
| `art` | Preview and loadscreen material names; metadata only |
| `ledger` | Rows of `{module, rung, receipt}` for display. The module's own `evidence.json` is the authority; nothing here is inferred |

`targets` is optional and counts the **distinct target keys**, not the entries: a file with 33
targets and nine locations that two routes both provide holds 42 entries. A wrong count is a
defect, which keeps a hand-edited file honest about the pairs it carries.

The file itself is optional. Without it a workspace's targets are the maps its foundations
stage, each a `stock-map` or `dlc5-map` on route `stock`.

### How the app groups the maps filter

`pat target list` returns `groups`: one group per parent target, with the children under it in
id order, each child carrying its `route` and whether its `location_table` exists. The app's
maps filter renders each group as the parent map expanding to its locations: `TranZit` to
`Bus Depot`, `Town`, `Farm`, `Diner` (once per route), `Power Station`, `Tunnel`, `Cornfield`.
A location whose map has no classic target of its own is a top-level group. DLC5 maps and custom
maps are top-level groups with no children until a location is authored for them. Filtering on a
location narrows the shelf to modules whose ledger has a row on that target and shows "not yet
built here" for the rest; it never hides a module because its `maps` field lacks the location.

## The location table: `registry/locations/<key>[.<route>].json`

One JSON file per target **per route**. A `stock` table is `<key>.json`; any other route writes
`<location>.<route>.json`, so two providers of one location never share a file and neither has
to win. Header:

| Field | Meaning |
| --- | --- |
| `schema` | `1` |
| `target`, `foundation`, `map`, `mode`, `location`, `title` | As in the target entry; `target` must equal the joined parts and the file's path under `registry/locations/`, with the route suffix removed |
| `route` | The one provider whose source this table was read from. Defaults to `stock`. It decides the file's name |
| `records` | The workspace documents every row cites (a per-map record, a source manifest); a row may only cite a listed record. Workspace-relative paths |
| `coordinate_note` | The convention: origins `(x, y, z)`, angles `(pitch, yaw, roll)`, source order and precision, no normalization |
| `source_notes` | Optional prose about what the source holds that is *not* a row: guards that return before spawning, literals used as lookup keys, box corners that are not sites |
| `shelf` | Optional display metadata cited to its own source: caption key, caption text, preview material, the engine's start-location token |
| `facts` | The six facts (`offline_verified`, `installed`, `launched`, `loaded_playable`, `captured`, `player_accepted`), all `false`. A table is source data and can never promote a rung |
| `placements` | The rows, at most 4096 |

Row:

| Field | Meaning |
| --- | --- |
| `kind` | `perk-machine`, `pack-a-punch`, `wall-buy`, `gobblegum`, `wunderfizz`, `mystery-box`, `rotation-slot`, `player-spawn`, `zone-fence`, `buildable-table`, `power-switch` |
| `id` | Stable within the table, prefixed by provider (`cr35-vending_jugg`, `bo2r-jugg`); lowercase, digits, `.`, `_`, `-` |
| `site` | The source's site name (`vending_jugg`, `pack_door`); `null` when the source has none |
| `occupant` | The identity the source put there (`specialty_armorvest`, `mp9_zm`); `null` for an empty slot or a machine with no fixed identity |
| `origin`, `angles` | Literal three-number lists exactly as written, or `null` |
| `expression` | When there is no literal: `{"origin": ..., "angles": ...}` naming the relation the source used (`GetEnt("vending_jugg","targetname").origin + (0,-20,0)`). `origin` is required; `angles` may be `null` when the source leaves them to the engine, as a stock route registration does |
| `source` | `{provider, record, citation, file, line, sha256, text}`: `provider` names the roster (`cr35-downloads`, `cr35-zip`, `t5-stock-script`, `bo2-reimagined`, `t6-qol`, `workspace-module`, `measured`); `record` is one of the header's `records`; `text` is the literal the row was read from |
| `confidence` | `high` (a same-map implementation states it), `medium` (community documentation, room-level), `unknown`. `high` requires a file and a line |
| `note` | Source caveats, at most 2000 characters. A note may not claim a T6 fact |

Rosters never mix: two sources that put one identity at two sites are two rows with two
providers, and a composition picks one provider per kind.

### What `pat target validate` checks

The workspace validator's rules, made public:

1. Shape: schema 1, every header field present, a non-empty `placements` list of objects.
2. The `target` string equals `<foundation>/<map>/<mode>[/<location>]` from its own fields, and
   equals the file's path under `registry/locations/` once the route suffix is removed; a table
   on a non-`stock` route is named `<location>.<route>.json`.
3. A `zsurvival` target names its location, and the table names one route.
4. All six facts are present and `false`.
5. Every row carries a literal `origin` or an `expression.origin`; angles never appear without
   an origin; `expression` values are strings or `null`; a `rotation-slot` has a literal or a
   symbolic transform.
6. Every vector is a list of exactly three numbers.
7. Row ids are unique in the table.
8. Every row's `source.record` is listed in the header's `records`; every `source` key is
   present; `line` is a positive integer or `null`; `sha256` is 64 hex characters or `null`.
9. `high` confidence has a `source.file` and a `source.line`.
10. A literal `origin` equals the cited `source.text` when that text is a parenthesized vector
    (a coordinate cited to an acceptance verdict is exempt).
11. No note claims a T6 fact ("verified on T6", "accepted on Beta 2", "playable").

And for the target file: every entry's parts agree with its key, its kind fits its key, the
route the id names is the route the entry declares, a location's parent is in the file (or is
absent only where the map has no classic target), no duplicate ids, no two entries for one
`(target, route)`, a fence that cites its route script, every `location_table` at the path its
id and route name and present on disk, every `placements` count equal to its table's rows, and
the file's own `targets` count equal to its distinct keys. Two entries for one target on
different routes are the expected pair and are reported under `route_choices`, not refused. A
table with no entry is listed under `unlisted_tables`, also not refused: the first proof table
came before the file.

What it does not check: that any coordinate is inside the map, that a machine fits, or anything
about T6. Those are play-mode facts and stay on the ladder.

## The routes

```sh
pat target list <workspace> --json
pat target inspect <workspace> dlc5-beta2/zm_factory/zclassic --json
pat target inspect <workspace> bo2-stock/zm_transit/zsurvival/diner --route t6-qol --json
pat target validate <workspace> --json
```

All three are inert: they read `foundations/*.json`, `registry/targets.json` (or
`--targets-file PATH`) and `registry/locations/**/*.json` under the workspace and nothing else.
`list` returns every target with its kind, parent, route, base token and whether a table exists,
plus `groups` and `counts`; target-file defects are `diagnostics` and do not fail the listing.
`inspect` returns the entry and, when a table exists, its hash, route, validation and summary
(rows by kind, literal against expression, confidence, providers). Its key may carry a route
(`<key>@<route>`) or name one with `--route`; a key more than one route provides and no route
given returns `outcome: route_choice` with the routes and no table. A key that is neither listed
nor tabled is `input_missing`, a malformed key is `invalid_arguments`. `validate` is exit 1 with
`input_invalid` and every diagnostic in `details.report` when anything is malformed.

## The placement contract: `placements` on `module.json`

A module that needs a place declares what it needs, never where:

```json
"placements": [
  {"needs": "perk-machine", "occupant": "specialty_armorvest", "count": 1, "fallback": "rotation-slot"},
  {"needs": "wall-buy", "occupant": "mp9_zm", "count": 1, "fallback": "refuse"},
  {"needs": "pack-a-punch", "count": 1, "fallback": "refuse"},
  {"needs": "gobblegum", "count": "any", "fallback": "spawn-room-default"}
]
```

| Key | Meaning |
| --- | --- |
| `needs` | A row kind from the table format |
| `occupant` | The identity the module provides; the resolver prefers a row whose `occupant` matches, then any free row of that kind. Optional |
| `count` | How many sites the module wants on each target: `1` (the default), an integer up to 256, or `"any"` (at least one) |
| `fallback` | What the plan does when the target's table has no matching row: `refuse` (the default: the plan fails), `rotation-slot` (hand the perk to the rotation service instead of a fixed machine), `wunderfizz` (join the Wunderfizz pool), `spawn-room-default` (an app policy site, marked as such), `omit` (the module loads without the site) |

`pat module inspect` validates the field when present and echoes it normalized (`occupant`
`null`, `count` `1`, `fallback` `refuse` when omitted). Absent is not an error and adds nothing.
The field says nothing about evidence and never widens `bases` or `maps`.

### The plan-time check

```sh
pat module plan <composition.json> --workspace <workspace> --target dlc5-beta2/zm_factory/zclassic --output <new dir> --json
```

For each `--target` (repeatable; its map must be the composition's map, and a location more than
one route provides must name one as `<key>@<route>` or the plan refuses with
`invalid_arguments`), `module plan` reads the target's location table as a hashed input and reports, under `placements` and as a
`placements:<target>` check, which declared needs the table can satisfy and which it cannot.
Rows are handed out in table order, an occupant match first, then any free row of the kind, each
row consumed once. Per need the outcome is `satisfied`, `fallback` (no row, a declared fallback
policy), `refused` (no row, fallback `refuse`) or `no_table`. The check is `passed` when every
need is satisfied or on fallback, `failed` when any need is refused (the plan then fails like any
failed offline check), and `not_counted` when no table exists for the target. Without
`--target`, a composition whose members declare placements lists the needs against its own map
as `not_counted`; a composition with no declared placements adds nothing. An invalid table is
`input_invalid` before anything is resolved.

This is a check. No location provider module is generated yet: the generated
declared-replacement module that owns the site registrations for one composition on one target
(roadmap Phase 3) will consume the same resolution and record the table's hash in its receipt.
Rows with an `expression` and no literal are counted as rows here; how they resolve (against the
target's vanilla profile at plan time, or by the provider script at runtime) is the provider's
statement, not this check's.

## Ledger scope per target

Every ledger row's scope is `{base, map, location}` with `location` `null` for classic
([evidence-ledger.md](evidence-ledger.md)). `pat module state --ledger` reports `scopes` (each
base, foundation, map and location the rows name) and `by_target` (each `{base, map, location}`
with foundations folded together), a location always its own row, never collapsed into its
parent map. `--target <key>` queries one target: the key's foundation, map and location at once.

```sh
pat module state --ledger modules/rw-icr --target bo2-stock/zm_transit/zsurvival/diner --json
```

## Rules the schema enforces

- A location is a target, never a module.
- One route per entry. A second provider for the same `(map, mode, location)` is a second entry
  and a second table, reported as a pair; choosing between them is refused at plan time, like
  two `replaceFunc` owners of one target function.
- `fence` and `route` cite source lines.
- Multiple locations on one map are distinct targets with distinct ledgers.
- A table's six facts are always `false`; nothing in a table or a target entry is evidence.

## What is not here yet

The generated location provider module per target, the target adapter that admits a survival
route provider's gamemode-table registration without refusing it as a base-entry replacement,
and the vanilla profile extractor. Each is recorded on the roadmap and arrives with its own
route, tests and receipt.
