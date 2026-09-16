# The evidence ledger: `evidence.json` beside `module.json`

Provenance is a ledger, not a flag. A module's history is a list of typed, scoped rows: where its
bytes came from, which pack it was accepted in, which build of it alone passed readback, which run
loaded it, who accepted it and for what. Rows coexist and nothing collapses them. The six facts
the shelf shows (offline verified, installed, launched, loaded and playable, captured, player
accepted) are derived from rows for display, per scope, and a fact no row states stays unknown.
Nothing is inferred from a composition that used the module.

The format was designed from the rows the workspace already writes: registry `build_revisions`
with their receipt paths and four flags, `docs/ACCEPTED.json` verdict lists, `docs/LINEAGE.json`
parents, the `lineage` field in `module.json`, and the archived pack acceptance records. Every
row type below is one of those shapes made explicit, scoped and hashed.

`pat module inspect` validates the ledger when it is present beside a module declaration;
`pat module state --ledger` derives the facts from it; `pat module ledger-from-registry`
proposes one from a workspace's registry and docs without writing it.

## The file

```json
{
  "schema": 1,
  "subject": {"id": "rw_icr"},
  "rows": [ ... ]
}
```

`subject.id` is the `id` in the `module.json` beside it. `rows` is a list of at most 1024 rows in
the order they were recorded; order carries no meaning beyond reading. The file is at most 1 MiB.
The ledger is append-only by convention: a later fact is a new row, never an edit of an old one.
A row that turned out to be wrong is corrected by a row that says so (a `player-accepted` row
with `outcome: rejected`, a `built-alone` row with `offline_verified: false`), and the wrong row
stays.

Every string in a row is text that can be written: a value JSON accepts but UTF-8 cannot encode
(a lone surrogate, `"\ud800"`) is refused with the pointer of the field that holds it, rather
than validating and then failing in the encoder with the ledger already open for writing.

## Every row

Every row has a `type`. Every row except `lineage` has a `scope`, and may have:

| Field | Meaning |
| --- | --- |
| `scope` | Where the statement applies. See below. |
| `at` | When: `YYYY-MM-DD` or an ISO date-time. The shape and the calendar are both checked: `2026-99-99` has the shape of a date and is not a day, and a row dated one is refused. |
| `record` | The file that supports the row: `{"path", "sha256"?, "commit"?}`. The path is forward-slash, relative to the workspace root, and never climbs out of it. The hash is the file's SHA-256 when it was recorded, so drift is visible. |
| `package_sha256` | The `mod.ff` the row is about, when the row is about a build. Two rows about different packages never merge. |
| `note` | Free text, at most 2000 characters. Scope qualifications go here (what a verdict covered and did not). |

A **scope** names a base token and/or a foundation id, and a map set:

```json
{"base": "stock", "foundation": "bo2-stock", "maps": ["zm_transit"], "mode": "solo", "players": 1, "profile": "stock_rw_icr_test"}
```

`base` is the token a composition names (`stock`, `b1`, `b2`); `foundation` is the workspace's
foundation id (`bo2-stock`, `dlc5-beta1`, `dlc5-beta2`). Either or both; a row with neither has
no scope and is invalid. `maps` lists the map ids the statement covers, or `["*"]` for any map;
`map` with one id is accepted and normalized to `maps`. `mode`, `players` and `profile` narrow
the statement for the reader and never affect matching.

A scope may also name a **survival location**: a fenced area of a stock map with its own route,
such as Reimagined's or QoL's Crazy Place, Diner or Cell Block. `location` is one lowercase id and
requires exactly one map:

```json
{"base": "stock", "map": "zm_transit", "location": "diner"}
```

A location is part of the match in both directions. A row about the Diner is not a row about
Green Run: a query for `zm_transit` without a location sees only rows with no location, and a
query for `zm_transit` with `diner` sees only rows scoped to `diner`. The per-scope listing keys
each location separately, so location rows never collapse into their parent map. Ledger scope is
`{base, map, location}`: the report's `by_target` list gives each such triple its own six facts
with foundations folded together, and `--target <foundation>/<map>/<mode>[/<location>]`
([target-sets.md](target-sets.md)) queries one target, supplying foundation, map and location at
once. `pat target list` lists the locations beside the stock maps.

## Row types

The `lineage` field of `module.json` is the first row type, unchanged in shape.

**`lineage`**: a T4/T5 source relationship, exactly the entries the declaration's `lineage` field
holds. Fields: `game` (`t4`/`t5`), `map` (a `zm_` id), `source`, optional `note` (400
characters). No scope: the row is about the source game. Feeds no fact.

```json
{"type": "lineage", "game": "t5", "map": "zm_prototype", "source": "Chronicles Reawakened v3.5 ZIP", "note": "No T6 verification."}
```

**`authored`**: this module was written or derived here. Optional `by`, `changes` (a list of
sentences), and `parent` for an overlay or a revision of another module:
`{"id", "declaration_sha256"?, "package_sha256"?, "record"?}`. Feeds no fact.

```json
{"type": "authored", "scope": {"foundation": "dlc5-beta2", "map": "zm_sumpf"},
 "parent": {"id": "babygun", "declaration_sha256": "<64 hex>", "package_sha256": "<64 hex>", "record": {"path": "modules/babygun/module.json"}},
 "changes": ["Sumpf-only server/client entrypoints calling parent activate functions."]}
```

**`accepted-in-pack`**: a composition that contained this module was accepted by the player.
Required `pack` (the pack's name or directory) and `record` (the acceptance record). Optional
`verdict` (the quote), `reporter`, `not_covered`, `package_sha256` (the pack's `mod.ff`). This is
history: it feeds no fact for the module alone, because the pack's acceptance says nothing about
this module built by itself.

```json
{"type": "accepted-in-pack", "pack": "dlc5-addons", "scope": {"foundation": "dlc5-beta1", "map": "zm_factory"}, "at": "2026-09-06",
 "record": {"path": "archive/t6/dlc5-addons/docs/BATCH_STATUS.json", "sha256": "<64 hex>"}, "package_sha256": "<64 hex>",
 "verdict": "User accepted the complete repaired weapon pool on Der Riese"}
```

**`extracted-from-release`**: the bytes came from a named release with a known use. Required
`release` (the release's name), `use` (what the release did with them, in words). Optional
`commit`, `package_sha256` (the release's package), `record`. Feeds no fact.

```json
{"type": "extracted-from-release", "release": "archive/t6/dlc5-addons/.local/accepted-babygun/snapshot.json",
 "use": "Accepted 17-family Der Riese pool", "commit": "11ca21959a49d79d2075d8389357a596119403ec",
 "scope": {"base": "b1", "foundation": "dlc5-beta1", "maps": ["zm_factory"]}, "package_sha256": "<64 hex>"}
```

**`built-alone`**: this module, by itself, was built on a foundation. Required `receipt` (a
record pointer to the build receipt), `offline_verified` (`true` when the receipt succeeded with
readback, `false` when the build was attempted and failed), and a scope naming the `foundation`.
Optional `package_sha256`, `parent`. Feeds **offline_verified**.

```json
{"type": "built-alone", "scope": {"base": "b2", "foundation": "dlc5-beta2", "maps": ["zm_factory"]}, "at": "2026-09-13",
 "receipt": {"path": ".local/wave2-spike/babygun-build-03/build.json", "sha256": "<64 hex>"},
 "package_sha256": "<64 hex>", "offline_verified": true}
```

**`agent-reviewed`**: an agent read the module and recorded a finding. Required `outcome`
(`passed`, `failed`, `noted`). Optional `by`, `record` (the review). Feeds no fact.

**`game-tested`**: the module was put in front of the running game in a recorded run. Required
`run` (the run id), `result` (`passed`, `failed`, `inconclusive`). Optional `capture` (a record
pointer to the recording), and the four observed facts as booleans: `installed`, `launched`,
`loaded_and_playable`, `captured`. A fact the run did not observe is left out, never set false.
Feeds **installed**, **launched**, **loaded_and_playable**, **captured**, each only when present.

```json
{"type": "game-tested", "run": "e41427497d1d46c4abdd743204e2b997", "result": "passed",
 "scope": {"base": "stock", "foundation": "bo2-stock", "maps": ["zm_transit"], "mode": "solo", "players": 1},
 "package_sha256": "<64 hex>", "installed": true, "launched": true, "loaded_and_playable": true}
```

**`player-accepted`**: the player's verdict. Required `outcome` (`accepted`, `rejected`) and
`record` (the verdict record). Optional `reporter`, `quote`, `not_covered`, `supersedes` (the
package hash of the verdict it replaces), `package_sha256`. Feeds **player_accepted**: `true` on
`accepted`, `false` on `rejected`.

```json
{"type": "player-accepted", "outcome": "accepted", "reporter": "Halo", "at": "2026-09-12T02:55:00Z",
 "quote": "I just loaded in. Everything is good.",
 "scope": {"base": "stock", "foundation": "bo2-stock", "maps": ["zm_transit"], "mode": "solo", "players": 1, "profile": "stock_rw_icr_test"},
 "record": {"path": "modules/rw-icr/docs/ACCEPTED.json", "sha256": "<64 hex>"}, "package_sha256": "<64 hex>",
 "not_covered": ["co-op", "other maps", "actual PAP machine transaction", "measured performance"]}
```

## Deriving the six facts

The facts are a display over rows, computed per query, never stored:

| Fact | True when a matching row says | Which row types speak |
| --- | --- | --- |
| `offline_verified` | `offline_verified: true` | `built-alone` |
| `installed` | `installed: true` | `game-tested` |
| `launched` | `launched: true` | `game-tested` |
| `loaded_and_playable` | `loaded_and_playable: true` | `game-tested` |
| `captured` | `captured: true` | `game-tested` |
| `player_accepted` | `outcome: accepted` | `player-accepted` |

A query names any of `base`, `foundation`, `map`, `location`, `package`. A row matches when every
named key agrees with the row: the base and foundation equal the row's, the map is in the row's
`maps` or the row says `*`, the package equals the row's `package_sha256`, and the row's location
equals the query's (both absent, or both the same id). Among matching rows of the
speaking type, the fact is `true` if any row states true, `false` if rows state only false, and
`null` (unknown) if no row of that type matches. No fact is inferred from another fact, from a
declaration, from a composition build, or from an `accepted-in-pack` row. A `player-accepted`
row does not imply `installed`; a `game-tested` row does not imply `offline_verified`. The
report also lists every scope the rows name with its own six facts and the row numbers behind
each, and counts the rows that are history only.

```sh
pat module state --ledger modules/rw-icr --base stock --map zm_transit --json
pat module state --ledger modules/rw-icr --base stock --map zm_transit --location diner --json
pat module state --ledger modules/rw-icr --target bo2-stock/zm_transit/zsurvival/diner --json
```

```json
{"protocol": "pat.module-ledger/1", "validation": "valid", "subject": "rw_icr", "rows": 11,
 "query": {"base": "stock", "foundation": null, "map": "zm_transit", "location": null, "package": null},
 "facts": {"offline_verified": {"value": true, "rows": [8]}, "installed": {"value": true, "rows": [9]},
           "launched": {"value": null, "rows": []}, "loaded_and_playable": {"value": true, "rows": [9]},
           "captured": {"value": null, "rows": []}, "player_accepted": {"value": true, "rows": [7]}},
 "scopes": [{"scope": {"base": "stock", "foundation": "bo2-stock", "map": "zm_transit", "location": null}, "facts": {...}}],
 "by_target": [{"base": "stock", "map": "zm_transit", "location": null, "facts": {...}}],
 "history": {"lineage": 7, "authored": 0, "accepted-in-pack": 0, "extracted-from-release": 0, "agent-reviewed": 1},
 "diagnostics": [], "reasons": []}
```

A ledger with a malformed header derives nothing and says why in `reasons`. A malformed row is
one diagnostic with its JSON Pointer and is not counted; the other rows still derive, and
`reasons` says how many were dropped. `--ledger` and `--composition` are two subjects of one
route: the composition rungs (`composed` through `player_accepted`) are still derived by hash from
a plan and its receipts, and the ledger reports the module's own rows. Neither reads the other.

## Validation in `module inspect`

When `evidence.json` sits beside a `module.json`, `pat module inspect module.json --json` adds a
`ledger` object to its result: the file, its hash, `validation` (`valid`/`invalid`), the row
count, the row types present, and bounded diagnostics. A ledger whose `subject.id` differs from
the declaration's id is a diagnostic. The ledger's defects never change the declaration's own
`validation` or the exit status: an invalid ledger beside a valid declaration is `metadata-valid`
with exit 0 and a `ledger.validation` of `invalid`. Absence of the file is not an error and adds
no `ledger` key. Inspection reads the file only; it follows no record pointer and verifies no hash.

## Appending rows

```sh
pat module ledger-add <module directory | evidence.json> --row <row.json> [--row <row.json> ...] --json
```

appends rows to `evidence.json`. Every row the campaign records goes through this route; a row
typed into the file by hand is a row nothing validated. Each `--row` file holds one row object or
a list of row objects, and the files are appended in the order they are given.

- **Validated like every other row.** Each row is checked by the rules `pat module inspect`
  applies (`dev/ledger.validate`), in the context of the whole ledger: at most 1024 rows and at
  most 1 MiB, counted after the write, not before.
- **All-or-nothing.** One row that fails writes nothing. The refusal lists every diagnostic with
  its row index in the resulting file and its JSON Pointer, and names the `--row` file it came
  from. A ledger that already holds a row that does not validate is refused too: a new fact under
  a malformed one is a fact nothing can derive from. Fix the file first.
- **Append-only.** No existing row is edited, reordered or removed. A row whose normalized JSON
  the file already holds is refused with `row_duplicate` and its index, rather than written a
  second time, so a campaign that reruns its loop records each run once. A row that states a
  further fact (the same run, now with `loaded_and_playable`) is a new row and is appended. A row
  that turned out to be wrong is still corrected by a row that says so, never by an edit.
- **Created when absent**, as `{"schema": 1, "subject": {"id": <the module.json id>}, "rows": []}`.
  Only the `id` is read from the declaration. A ledger whose `subject.id` is another module's is
  refused.
- **One writer at a time.** The read, the validation and the write happen under an advisory
  lock on a sibling `.evidence.json.lock` file, so two campaign workers appending at once append
  both rows: the second waits for the first and then reads the row the first one wrote. Without
  it both would read the same book and the later write would drop the earlier row while both
  commands reported success.
- **Never a half-written ledger.** The new file is written to a sibling temporary file in the
  same directory, flushed, `fsync`ed and then renamed onto `evidence.json`. A full disk or an
  interrupt leaves the rows that were already there, and the temporary file is removed. An
  `evidence.json` that is not a regular file — a symlink, a FIFO, a directory — is refused with
  `input_invalid` before anything is opened: the route never writes through a link, and never
  blocks on an open that does not return.
- **The diff is the rows added.** The file keeps its own `ensure_ascii`: one that escapes
  non-ASCII keeps escaping and one that writes UTF-8 keeps writing it, so nothing re-escapes an
  accent in a row that did not change. Indent is two spaces, the shape every record here uses.

The result names the file, the row counts before and after, the appended indexes, `validation`,
and for each appended row the six facts the ledger now derives for the scope that row names, one
entry per map in it — the whole ledger's answer for that scope, not the row's own claim:

```json
{"protocol": "pat.module-ledger-add/1", "ledger": "modules/rw-icr/evidence.json", "created": false,
 "subject": "rw_icr", "sha256": "<64 hex>", "rows_before": 10, "rows_after": 11, "appended": [10],
 "validation": "valid", "diagnostics": [],
 "rows": [{"row": 10, "type": "game-tested", "source": "run-41.json",
           "scopes": [{"scope": {"base": "stock", "foundation": "bo2-stock", "map": "zm_transit", "location": null},
                       "facts": {"installed": {"value": true, "rows": [10]},
                                 "loaded_and_playable": {"value": null, "rows": []}, "...": {}}}]}]}
```

A `game-tested` row that states only `installed` and `launched` leaves `loaded_and_playable` and
`captured` `null` there, because a fact the run did not observe is left out of the row and no
fact is inferred from another. A row scoped to `maps: ["*"]` reports one entry, `map: "*"`,
answered by the rows that are themselves scoped to every map; the map-specific rows do not feed
it, because a module built alone on one map is not a module verified on all of them. The route reads and writes that one file: no game, no network, no
install, no receipt directory.

## Populating a ledger from a workspace

```sh
pat module ledger-from-registry <workspace> <module-directory-name> --dry-run --json
```

reads the workspace's `registry/t6-modules.json`, `foundations/*.json`, the module's
`module.json`, `docs/ACCEPTED.json`, `docs/LINEAGE.json`, `docs/TEST.md` and the archive records
the registry cites, and prints a proposed ledger with the same validation `module inspect` would
apply, the facts it would derive, the hashes of the files it read, and `notes` naming everything
the worker must fill or check before writing. It never writes: every invocation is a dry run and
`written` is always `false`. The rules it applies:

- The declaration's `lineage` entries become `lineage` rows verbatim.
- Each `verdicts[]` entry in `docs/ACCEPTED.json` becomes a `player-accepted` row with its scope
  (`base`, `map` and, when the verdict names one, `location`), time, reporter, quote, package
  hash and `not_covered`. A short hash in a verdict is noted and
  left out; only a full SHA-256 is a package hash.
- Each registry `build_revision` for the module alone becomes a `built-alone` row (receipt,
  foundation, map, package hash, `offline_verified`), a `game-tested` row when the revision says
  `installed` or `runtime_verified` (mapped to `installed` and `loaded_and_playable`; `launched`
  and `captured` are left unknown), and a `player-accepted` row when it says `player_accepted`
  and no verdict already covers that package. A revision whose `modules` lists more than one
  member, or that names a `composition`, is a pack build: it is noted and contributes nothing.
  A revision with no foundation or map takes the declaration's own base and maps and is noted so
  the worker narrows it. The foundation's `profile_prefix` supplies the base token.
- Archive JSON records the registry cites for an `accepted-*` status, whose contents say accepted,
  become `accepted-in-pack` rows pointing at the record with its current hash; a hash that differs
  from the one the registry recorded is noted. Prose records are noted for the worker to read.
- A `docs/LINEAGE.json` parent with a `source` becomes an `extracted-from-release` row with the
  parent's commit, package hash and evidence base; a parent with a `module_id` becomes an
  `authored` row citing the parent's declaration and package hashes.
- A registry `standalone_module_verified: true` with a `docs/TEST.md` becomes an `agent-reviewed`
  row with outcome `noted` pointing at the test record.
- A receipt path outside the workspace is kept verbatim so the worker sees it, and fails
  validation until relativized or replaced.

The worker reads the proposal and the notes, edits the rows, and writes
`modules/<id>/evidence.json`; then `pat module inspect modules/<id>/module.json --json` confirms
`ledger.validation` is `valid`.

## What the ledger is not

It is not a state file: `module state` on a composition derives its rungs from hashes and never
reads the ledger. It is not evidence by itself: a row is a pointer to a record and a hash, and the
record is the fact. It is not a gate: `module plan` and `module build` ignore it, as they ignore
`lineage`. It never widens a declaration's `bases` or `maps`.
