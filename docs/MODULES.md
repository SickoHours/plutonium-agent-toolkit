# Modules and compositions: the formats

Two small JSON files make a mod something an agent can compose with other mods: a **module
declaration** beside a mod's recipe, and a **composition recipe** that names a base, a map and
the modules to build together. `pat module plan` resolves a composition and `pat module build`
produces one `mod.ff` from it. Words are defined in [`../CONTEXT.md`](../CONTEXT.md): module,
core module, composition, profile, recipe, base.

The point of the formats is that the agent, not a package manager, resolves what a pack needs.
A declaration states facts the agent cannot infer from source (which bases and maps the module
was built for, what it depends on, what it must not be combined with, how much of the engine's
budgets it takes). Everything else stays in the module's own `project.json` recipe, which
`pat project build` already understands. A mod that has a `project.json` needs only a
`module.json` to become composable.

## Inspect metadata without resolving payloads

```sh
pat module inspect path/to/module.json --json
pat module inspect path/to/composition.json --json
```

`module inspect` is inert: it reads one regular declaration and refuses final-component
symlinks/reparse points and files over 256 KiB. Symlinked ancestor directories are allowed,
matching plan/build. The reader verifies stable regular-file identity and hashes the exact
bytes it parses. It creates no job or output directory, reads no configuration, discovers no
backends, and performs no network or game operation. `--output`
is not accepted. The normal invocation envelope retains `schema_version: 1` and a generated
`request_id`; its result protocol is `pat.module-inspect/1`, specified by
[the producer schema](../schemas/module-inspect-v1.schema.json).

`validation: metadata-valid` means `validation_scope: declaration-only`. Inspect and plan/build
share the metadata validators, including fields omitted from the inspection projection (source,
provides, resource contracts, loads, base-owned listings, zone headers and decisions). Existing
defaults and empty decision reasons are preserved. Module `payload` is the declared `recipe` or
`seed` discriminator; inspect does not open either file or derive provides from a seed manifest.
Composition members retain declaration order. A pinned reference without a declared local path
fails with `input_missing` at `/modules/<index>/path`; inspect never fetches it. A declared path
can name a missing payload/member/load/listing and still pass metadata checks.

Full resolution remains `module plan`/`build`: file existence and containment, seed contents and
provides consistency, nested composition cycles, resolved member identity and duplicate paths,
dependency order, base/map fit, collisions and actual resource totals require those routes.
Metadata validity establishes none of these facts or any installation or gameplay evidence.

Inspection failures retain the native `error_code`, `message` and optional `hint` within the
transport limits below, and put the inspection at `details.inspection`. Invalid metadata is null.
Diagnostics contain structural JSON Pointer
`field` values (including the offending unknown key), a code and message; `/` denotes a whole
file or JSON error. `sha256` is null unless all bounded input bytes were read, including on
unreadable, linked and oversized inputs. Invalid JSON that was read still has its actual digest.
The `file` field is the local producer path; consumers should project a suitable label for their
caller rather than expose that path in default model output.

Inspection diagnostic `field` and `message` are at most 2048 UTF-16 code units; `error_code` is
at most 200 UTF-16 code units. These match JavaScript string length: supplementary characters
count as two units and lone surrogates as one. The schema's `maxLength` remains a code-point
upper bound; the transport enforces the stricter UTF-16 bound for consumer compatibility.
Lone surrogates are JSON-escaped on stdout so decoded values survive UTF-8 output unchanged.
If an escaped JSON Pointer exceeds the limit, the field becomes `/` and the message
explicitly says the offending key exceeds the diagnostic limit. A pointer is never truncated
into a different key. Overlong messages and hints are replaced with a bounded notice that detail
was omitted due to the diagnostic limit. Envelope `message`, `hint` and `error_code` have the
same limits as diagnostics, with the same code and message in both places. An overlong error
code becomes `input_invalid` with an explicit omission notice. These bounds apply only when
inspect emits an error; the reusable validators and plan/build error details remain intact.
The inspection stays invalid with null metadata and retains its exact source digest when read.

Argument/usage failures, such as a missing path or supplying `--output`, exit 2 and emit the
normal toolkit `invalid_arguments` invocation envelope without `details.inspection`. They are
outside `pat.module-inspect/1` and its producer schema; callers must handle them as invocation
failures rather than inspection results.

## Module declaration: `module.json`

Lives in the module's directory beside its payload. The payload is one of three things: a
`project.json` **recipe** the toolkit compiles and links (scripts and loose assets); a
**seed**, an already-linked `mod.ff` with its soundbanks and a `seed.json` manifest that
`pat module declare` writes from the package; or an **adapter recipe**, a donor conversion a
workspace builder cuts (below). A declaration names exactly one of `recipe` or `seed`; an
adapter recipe is named under `recipe` and told apart by its own shape.

A recipe's script targets are not free. A T6 client loads a mod's scripts from `scripts/zm/` and
an IW5 client from the flat `scripts/` namespace (`dev/titles.py`, `loaded_script_roots`); a
compiled script packed anywhere else reaches the client only as a `rawfile` inside `mod.ff` that
the engine never registers as a script, so it can never run however the module is later composed.
`pat project plan` and `pat project build` refuse such a target where a module built alone is
judged, and `pat module plan`/`build` refuse it again for a pack, both with the retarget and the
caller rewrite in the `script-reach:<target>` row's detail. Put a module's own scripts under the
loaded root and keep `maps\mp\...` for the stock paths you *call into*, which is a different
question and the one `map-scripts` answers.

```json
{
  "schema": 1,
  "id": "penetrator",
  "version": "0.1.0",
  "title": "The Penetrator",
  "category": "weapons",
  "kind": "melee",
  "tags": ["saints-row", "bat"],
  "seed": "seed.json",
  "bases": ["b2"],
  "maps": ["zm_factory"],
  "dependencies": ["penetrator_registration"],
  "conflicts": [],
  "provides": {"weapons": ["halo_penetrator_zm"]},
  "resource_contract": {"threads": 0, "entities": 0, "hud": 0, "network_fields": 0},
  "menu_route": "Equipment & melee > Melee > The Penetrator",
  "distribution": "seed",
  "source": {"repository": "https://github.com/<owner>/<repo>", "commit": "<40 hex>"},
  "origin": "saints-row",
  "donor": "Saints Row: The Third assets, converted for T6 by <who>, 2026",
  "parameters": [
    {"name": "box", "type": "bool", "default": true,
     "meaning": "Whether the weapon registers in the mystery box pool."}
  ]
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `schema` | yes | `1` |
| `id` | yes | The module's identity: lowercase letters, digits, underscore, at most 64. Other modules name it under `dependencies` and `conflicts`. Two modules in one composition cannot share an id |
| `version` | yes | A short version string. Recorded in the plan; no two modules' versions are ever compared, but `module verify-declaration` compares this module's against the version at its newest evidence row's commit and asks for a bump when the bytes moved and this did not |
| `game` | no | The title the module targets: `t6` (default) or `iw5`. Every member of a composition targets the same game, and the recipe's `game` must match. Selects the browse taxonomy `kind` is checked against |
| `title` | no | A display name, at most 120 characters. Defaults to the id |
| `category` | no | The shelf a person browses. For `t6`: `weapons`, `perks`, `gobblegums`, `powerups`, `equipment`, `bosses`, `companions`, `maps`, `ui`, `core`, `scripts`, `audio`, `tooling`, `pack`. For `iw5`: `weapons`, `attachments`, `killstreaks`, `gametypes`, `perks`, `maps`, `ui`, `core`, `scripts`, `tooling`, `pack` (no `audio`: the toolkit cannot build IW5 sounds). Defaults to `module`. Used for browsing, never for resolution |
| `kind` | no | Narrows the category from a fixed list per category and per game (t6 `weapons`: `wonder`, `firearm`, `melee`, `launcher`, `special`; iw5 `weapons`: `primary`, `secondary`, `launcher`, `melee`, `special`; and so on, defined in `dev/titles.py`). A kind outside its game's list is refused so packs and catalogs group the same way |
| `tags` | no | Up to 16 lowercase words: a source game (`saints-row`, `bo3`), a series, a theme. Free, never validated against a list |
| `recipe` | one of | Forward-slash relative path to the module's `project.json`, inside the module directory; no Windows drive prefix or rooted path, on any host. For an adapter payload it is the default cut, the one used when `recipes` names none for the composition's target |
| `recipes` | no | Adapter payloads only: up to 32 `"<foundation>/<map>"` targets, each to the relative path of the adapter recipe cut for that target (`{"dlc5-beta2/zm_factory": "recipe-b2.json"}`). The foundation is the id `foundations/<id>.json` carries, never the base token. Every named file must exist, parse as an adapter recipe and declare that same `foundation` and `map`; a key on a `project.json` recipe or a `seed` is refused. Plan and build use the entry for the composition's target and fall back to `recipe` |
| `seed` | one of | Forward-slash relative path to the module's `seed.json`, inside the module directory, with `mod.ff` and its soundbanks beside it; no Windows drive prefix or rooted path, on any host. Path checks also apply to private declarations whose manifest is absent |
| `bases` | yes | The base tokens the module has been built and tested on: `stock` for the unmodified game, or a base release's own short token (`b2` for Zombies Declassified Beta 2). A composition on a base not listed here is refused |
| `maps` | yes | Map ids the module is built for, or `["*"]` for any map. A composition on a map not listed is refused. Grow this list by testing on the map, never by editing |
| `dependencies` | no | Ids of modules that must be in the same composition and are built first. A cycle or a missing dependency is refused. An entry may be an object `{id, kind, why?}` saying what the dependency is for (`call`, `name`, `service`, `runtime`; below, "What a module promises") |
| `conflicts` | no | Ids of modules this one must never be composed with. Both present is refused |
| `exclusive` | no | Role words from a fixed list (`hud`, `box`, `loadscreen`, `boss`, `perk-machines`, `perk-art`) this module owns outright; two members owning one role is a refusal of kind `exclusive` (below) |
| `service` | no | `true` when the module exists to own shared things (a map table, a sound bank, a role) so others depend on it and ship no copy; the planner names it in `ownership`, `replacement` and `service` refusals. Must provide something shareable and no weapon |
| `registration` | no | Who prints the module's one console line `<id> >> registered` at init: `self` (its own script), `entry` (the generated entry script, for an entry-managed module), or `none`. The plan derives `expected_lines` from it and `test plan` checks each line in the load phase ("The registration line", below) |
| `system` | no | The player-facing system a person finds the module under, one of `pack-a-punch`, `perks`, `hud`, `weapons`, `powerups`, `box`, `core-rules`, `gums`, `bosses`, `equipment`, `audio`, `map`; a browse word, never a resolution rule ("Where a person finds it", below) |
| `port_status` | no | `finished` (default), `loads-but-wrong` or `not-ported`; a member that is not `finished` is refused (kind `port_status`) unless the composition's member object names it under `accept` |
| `provides` | no | What the module registers, by kind: `weapons`, `perks`, `gobblegums`, `powerups`, `equipment`, `localize`, `soundbanks`, `scripts`, `models`, `effects`, `rawfiles`, `aliases` (the sound alias names a bank module owns), each a list of up to 4096 names. Two modules providing the same name is a decision (below); a `rawfiles` name is a file target and is listed once, as the file collision. A seed's manifest fills this in; for the kinds the manifest derives (`weapons`, `localize`, `soundbanks`, `rawfiles`, `models`, `effects`) a declaration may narrow the manifest's list and never add to it, even when the manifest lists none of that kind; the other kinds are the declaration's |
| `resource_contract` | no | Whole numbers the module adds to the engine's budgets: `threads`, `entities`, `hud`, `network_fields`. Missing fields count as 0. Summed across the composition and checked against the composition's `budget` |
| `menu_route` | no | How a person reaches the feature in game, at most 200 characters; carried into the plan for the handoff |
| `distribution` | no | `source` (buildable from the repository; the default for a recipe), `seed` (the package is committed beside the manifest; the default for a seed), `private` (recipe source/assets or a seed package are not published; the payload type remains recipe or seed, and plan/build still require the local inputs), or `stock` (the content ships with the game: no `recipe`, no `seed`, no `recipes`, `origin` must be `vanilla`, and `payload` inspects as `stock`; "Stock content", below) |
| `source` | no | Where the module comes from: an `https` `repository` URL and, ideally, the 40-hex `commit`. Carried into the plan so a pack can say what it was built from |
| `origin` | no | One lowercase word for the game or series the thing's identity comes from (`bo3`, `waw`, `saints-row`), or `unverified` when nobody has established it. It drives the title: an ICR-1 converted from a community pack is still "ICR-1 (Black Ops III)". Never defaulted to the donor. A browse word, never a resolution rule |
| `donor` | no | One line of credit, at most 400 characters, for where the bytes came from: a conversion pack and its author, a capture, a person. It drives the credit line, never the title. Preserved on every re-cut |
| `placements` | no | What the module needs placed on each target, never where: a list of `{needs, occupant?, count, fallback}` rows (`needs` a location-table row kind such as `perk-machine` or `wall-buy`; `count` `1`, an integer or `"any"`; `fallback` `refuse`, `rotation-slot`, `wunderfizz`, `spawn-room-default` or `omit`). `module plan --workspace W --target KEY` checks each need against the target's location table. Format: [target-sets.md](target-sets.md) |
| `parameters` | no | What a composition may configure on this module, so the choice is declared data rather than a literal in GSC: up to 32 objects `{name, type, default, meaning, values?, range?}`. `name` is lowercase letters, digits and underscore, at most 32, and unique in the module; `type` is `bool`, `int` or `string`; `values` (1 to 32 allowed values of that type) or `range` (`[min, max]`, integers, `int` only) narrows it, and a declaration names at most one of the two; `default` satisfies whatever it declares; `meaning` says what the parameter does in at most 400 characters. A string value is at most 120 characters. A seed payload may declare them too. A composition sets them per member, and the plan and build receipt record the effective map (below) |

Origin and donor are two facts, and a card shows both: "ICR-1 (Black Ops III)" with "from Chronicles
Reawakened v3.5 (Kosmoes), converted for T6" under it. A module whose origin is in doubt says
`unverified` rather than borrowing the donor's name, so the doubt is visible on the card.

A declaration says nothing about evidence. Whether the module is offline verified, installed,
playable or accepted on a base is a receipt's and a person's statement, not a field here; a
module that lists a base under `bases` has been built there by whoever wrote the declaration,
and the composition's own receipt is the only proof for the composed result.

### Stock content: `distribution: stock`

A stock declaration is a shelf entry for something the game already ships -- Pack-a-Punch, a perk
machine, later a weapon or a power-up. It has **no payload**: no `recipe`, no `seed`, no `recipes`,
nothing to fetch, compile or link, because its bytes are the base's. It exists so a map's baseline
stands on the shelf beside what can be added to it, and so a pack can say what it is adding *to*.

```json
{
  "schema": 1, "id": "vanilla_perks_juggernog", "version": "0.1.0", "title": "Juggernog (vanilla)",
  "category": "perks", "kind": "machine", "tags": ["vanilla"],
  "bases": ["b2"], "maps": ["zm_factory", "zm_sumpf"],
  "distribution": "stock", "origin": "vanilla",
  "provides": {"perks": ["specialty_armorvest"], "models": ["zombie_vending_jugg", "zombie_vending_jugg_on"]},
  "vanilla": {"zm_factory": {"cost": {"value": 2500, "file": "maps/mp/zombies/_zm_perks.gsc", "line": 1698}}}
}
```

- **`distribution` is read before the payload rule**, so a declaration that names neither a recipe
  nor a seed is admitted only here. Any other distribution still names exactly one payload.
- **`origin` must be `vanilla`.** Stock content's identity comes from the game it shipped in;
  any other origin (including `unverified`) is refused at `/origin`. `donor` stays optional --
  a credit line for the game's authors is a credit line like any other.
- **`provides` may be empty or absent.** What a stock item registers is a reading of the game's
  own scripts, and a declaration that has not made that reading yet claims nothing.
- **`vanilla`** is an optional object, accepted only on a stock declaration and refused at
  `/vanilla` on any other. It holds what the stock scripts show per map -- costs, tiers, camo
  index, entity targetnames, behaviour notes and the citations behind them -- keyed however the
  reader keys it. At most 32 KiB of JSON; every key is one lowercase word (a map id, or the name
  of one fact about it) and every value a JSON scalar, list or object. The toolkit bounds it and
  interprets none of it: a claim about the game belongs to whoever read the scripts and cited
  them, not to the toolkit.
- **`bases` and `maps` are judged like any other member's.** A stock item exists on the maps it
  exists on; a composition on a map the declaration does not list is `unqualified_map`, exactly as
  for a module with bytes.

In a composition a stock member is **never built, staged or counted**. It contributes no script,
no rawfile, no asset, no seed, no sound bank, no image and no resource contract; it can collide
with nothing and replaces nothing, so the file, replacement, ownership and service rules skip it,
and no pool counts it (counting it would charge the pack for the base it is measured against).
The plan lists it under a `stock` summary list with its `id`, `version` and `provides`, and its
plan row reports `payload: "stock"` with no payload hash.

What it **provides** is still read, because that is what the map already has: a client script that
registers `m1911_zm` in the mystery box passes the box-registration check when a stock member
provides that weapon, instead of failing for a weapon nobody ships.

The provenance half is the ledger's `shipped` row ([evidence-ledger.md](evidence-ledger.md)). It
says the game ships this on these maps, names the listing or decompile it was read from and, in its
optional `citations`, the lines inside one that say so. It feeds none of the six facts: shipping
with the game is not offline verification, an install, a run or a verdict.

## Seed manifest: `seed.json`

Written by `pat module declare <mod.ff> --output <new dir>`, which reads the package back with
OpenAssetTools and drafts a `module.json` beside it. Copy both next to the package (and any
`mod.str` it wrote) in the module directory.

```json
{
  "schema": 1,
  "package": "mod.ff",
  "files": {"mod.ff": "<sha256>", "halo_penetrator.all.sabl": "<sha256>"},
  "roots": ["weapon,halo_penetrator_zm", "soundbank,halo_penetrator.all", "xmodel,halo_penetrator_view"],
  "embedded": ["weapon,halo_penetrator_zm", "image,*halo_pen_color", "fx,impacts/fx_flesh_hit_splat"],
  "referenced": ["techniqueset,mc_lit_sm_r0c0_77e21qq8", "image,$identitynormalmap"],
  "provides": {"weapons": ["halo_penetrator_zm"], "localize": ["HALO_PENETRATOR"]},
  "strings": "mod.str"
}
```

`files` hashes the package and its soundbanks; a changed byte is `input_changed` at plan time.
`embedded` is everything the package carries, `referenced` what it expects the base to load,
`roots` the subset the pack's zone names so the linker copies them out of the seed (weapons and
soundbanks first, then models, animations, materials and effects; images, technique sets and
strings are never roots because the linker resolves them through the assets that use them).
T6 compiled script assets (`script,<path>`) are roots: a seed that embeds native helper scripts
would otherwise lose them silently while every root check still passed.
Localized strings cannot be copied out of a loaded fastfile, so `declare` extracts them to
`mod.str` and `module build` merges every seed's strings into the pack's own string table.

## Adapter recipe: the third payload

A donor-converted module (a Black Ops III GobbleGum, a World at War wonder weapon) is not
compiled by the toolkit: a workspace builder converts pinned donor inputs and links the package.
Its `recipe.json` names the foundation and map it was cut for and what the build delivers, and
the declaration points `recipe` at it. The planner tells an adapter recipe from a project recipe
by shape: `schema: 1` with `foundation`, `map` and `module` (or `adapter`), and no
`game`/`name` pair.

```json
{
  "schema": 1, "module": "gum_kill_joy", "foundation": "bo2-stock", "map": "zm_transit",
  "weapons": ["halo_gum_kill_joy_eat_zm", "halo_gum_kill_joy_activate_zm"],
  "loose_script": {"source": "src/gum_kill_joy.gsc", "target": "scripts/zm/halo_gum_kill_joy.gsc", "instance": "server"},
  "soundbank": {"name": "halo_gum_kill_joy.all", "aliases": "soundbank/new.aliases.csv"},
  "localize": {"HALO_GUM_KILL_JOY": "Kill Joy"},
  "rawfiles": [], "assets": {"xmodel": ["..."], "materials": ["..."], "images": ["..."]},
  "prepared": "<a private directory of converted inputs>"
}
```

`plan` reads the declared outputs as seed-like roots: the weapons, the one bank (and, when the
prepared inputs are on this machine, its alias table and the weapons' clips), the localized
strings, the loose scripts (`loose_script`, `loose_scripts` or `scripts`), rooted `rawfiles`,
`native_scripts`, `extra_effects` and the `assets` lists. Those roots count against the pools,
collide like a seed's, and fill `provides` the way a manifest does: a declaration may narrow
them, never add a name the recipe does not deliver. The member's `payload` is `adapter`.

`soundbank.exclude_aliases` is how a member that shares only part of its bank answers the
`service` refusal below (one alias, one bank): 1 to 256 alias names this cut hands to the bank
module that owns them, subtracted from the aliases the member is credited with (so the shared
rows are one bank's, not a collision) and recorded as `excluded_aliases` on the plan row and on
the `adapters[]` entry. The names are checked against the alias table wherever the prepared
inputs are on this machine — a name the table does not carry is a stale list and is refused —
and the workspace builder that cuts the bank must drop the same rows, with the readback of what
it produced (`soundbanks` in the build receipt's `adapters[]`, read back from the package rather
than taken from the builder's word) as the proof that it did.

#### Where `prepared` points

`prepared` is the directory of converted inputs the builder consumes, and the planner reads two
things out of it: the soundbank's alias table and the weapons' clips from `prepared.json`. An
**absolute** path is used exactly as the recipe gives it. A **relative** path is resolved against
the module directory first — the recipe's own directory is the only base that travels with the
module — and then against the workspace root when `--workspace` names one, which is what a shelf
whose builder was run by hand from that root means. The first candidate that is a directory wins.
When neither is a directory the inputs are absent, the plan drops the alias table and the clip list
as before, and the row says which paths were tried; the resolved copy below still states the
module-directory reading, so a builder that runs anyway fails naming the path the recipe meant
rather than one inside the job directory.

The plan row records the reading: `adapter.prepared_resolved` (the absolute path used),
`adapter.prepared_source` (`recipe` for an absolute path, `module-dir` or `workspace` for a relative
one) and `adapter.prepared_candidates`. **The builder is given the same reading.** Because it reads
the recipe from disk by path, `build` writes a resolved copy beside the builder's output directory,
at `<job>/adapters/<id>.recipe.resolved.json`, and passes *that* path: the same document with
`prepared` and every loose-script `source` absolute. A copy outside the module directory has to
state those paths in full, and a builder that resolves them as `recipe.parent / source` is
unaffected, because joining an absolute path returns it unchanged. The copy is a sibling of the
output directory, never inside it — the builder owns that directory and creates it itself. The
build report and the plan row name it as `recipe_resolved` (`null` on a plan, which writes none),
and the report's `recipe` still names the cut the copy was made from. Before this the two halves
disagreed: the planner tested a relative `prepared` against the caller's working directory while
the builder ran with the job's output directory as its own, so the same recipe planned as "prepared
absent" and then failed the build, and which it did depended on where `pat` was run from.

### One cut per target: `recipes`

An adapter recipe is a cut, not a source tree: it names one `foundation` and one `map`, and the
builder cuts exactly that. Composing the module on another target therefore means building it
there, and a module that has already been cut for a second target should say so rather than have
the pack retarget the first cut every time. `recipes` maps `"<foundation>/<map>"` to the recipe
for that target; `recipe` stays the default.

```json
{
  "schema": 1, "id": "gum_kill_joy", "version": "0.2.0",
  "recipe": "recipe.json",
  "recipes": {"dlc5-beta2/zm_factory": "recipe-b2.json"},
  "bases": ["stock", "b2"], "maps": ["zm_transit", "zm_factory"]
}
```

The foundation is the id `foundations/<id>.json` carries (`dlc5-beta2`), never the base token a
composition names (`b2`); the toolkit resolves the pack's base to a foundation the same way the
occupancy checks do. `plan` and `build` look up `<foundation>/<map>` for the composition's target
and fall back to `recipe`, so the plan row, the footprint and the link all read the cut the pack
will get; the row's `adapter.recipe_key` says which entry was chosen and `recipes` lists the keys
the declaration carries. Because the chosen recipe already names the pack's target, no
`--foundation`/`--map` override is passed to the builder: the retargeting above applies when the
declaration has only the default cut.

Every entry is validated wherever the pack is aimed, not only the one chosen: the file must exist,
parse as an adapter recipe, and declare the `foundation` and `map` of its own key. A `recipes`
entry on a `project.json` recipe or on a `seed` payload is refused — the toolkit compiles a
project recipe against whatever the composition targets, and a seed is one package.

`recipes` widens nothing on its own. `bases` and `maps` still grow only by a receipt on that
target: the per-target recipe is what makes the receipt possible, not a substitute for it.

`build` runs the workspace's builder as a backend: `PAT_BACKEND_ADAPTER_BUILDER` names it, or
`--workspace <dir>` names a workspace whose `toolchain/pat-adapter-build` (or `.py`) is it. The
contract is `<builder> <recipe.json> --output <new dir> [--foundation <id>] [--map <map>]`,
exit 0, `<dir>/build.json` with `status: succeeded`, `<dir>/stage/mod.ff` beside its soundbanks
and loose scripts under `<dir>/stage/scripts/`. The two target flags are passed only when the
composition's foundation (the workspace's id for its base token) or map differs from the
recipe's own: the member is cut alone on the pack's target, and the receipt under
`adapters[]` says so (`recipe_target`, `built_target`, `retargeted`). A builder that predates
the flags keeps working for a pack on the recipe's own target. The produced package is read back with the unlinker, its listing is the
manifest, and the pack links against it exactly as against a seed; the builder's own record is
kept in the receipt (`adapters[]`) and never trusted for what the package carries. Without a
builder the plan lists `adapter_builder` as unavailable and the build refuses before linking.

## Composition recipe: `composition.json`

```json
{
  "schema": 1,
  "name": "b2_my_base_penetrator_pack",
  "title": "My base pack plus The Penetrator",
  "tags": ["saints-row"],
  "base": "b2",
  "map": "zm_factory",
  "modules": [
    {"path": "../my_base_pack", "role": "base"},
    "../penetrator",
    "../penetrator_registration",
    {"name": "someone/round_announcer", "commit": "<40 hex>", "path": "../fetched/round_announcer"}
  ],
  "loads": ["../base/common_zm.ff", "../base/zm_factory-inspect.ff"],
  "zone_header": [">level.ipak_read,common_zm", ">level.ipak_read,zm_factory"],
  "budget": {"threads": 4, "entities": 0, "hud": 0, "network_fields": 0},
  "decisions": [{"collision": "scripts/zm/hud.gsc", "owner": "my_base_pack", "reason": "the pack's HUD wins"}],
  "base_owned": ["../base/common_zm-list.txt", "../base/zm_factory-list.txt"]
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `schema` | yes | `1` |
| `name` | yes | `<base>_<feature>_<stage>` with the composition's own `base` token and a stage of `test`, `probe`, `pack` or `pub` (`docs/knowledge/foundations.md`). It is also the install folder name |
| `game` | no | `t6` (default) or `iw5`. Every member must target the same game; a nested composition must match. Sets the zone header (`> game,T6` or `> game,IW5`) and mode the build stamps |
| `title`, `tags` | no | A display name and browse words for the pack itself |
| `origin`, `donor` | no | The same two facts as on a module, for a pack that is one thing ("Ghosts weapons on TranZit" has origin `ghosts`); a pack of mixed origins leaves them out and the plan carries each member's own |
| `base` | yes | The base token every module must declare |
| `map` | yes | One concrete map id. A composition is planned for one map; plan another composition for another map |
| `modules` | yes | 1 to 128 members. A member is a relative path (forward slashes, from the composition's directory) to a directory holding `module.json`, **or** a directory holding another `composition.json` (its modules are flattened in; it must declare the same base and map; nesting is bounded), **or** an object: `{"path": …, "role": "base"}` marks the one member the others attach to; `{"name": "<github-owner>/<id>", "commit": "<40 hex>", "path": …}` records a published module pinned at a commit, with the local directory it was fetched into; `{"path": …, "parameters": {"cadence": "timer"}}` sets that member's declared parameters (below), and a member that is a nested composition takes none; `{"path": …, "accept": ["loads-but-wrong"]}` composes a member whose `port_status` is not `finished` knowingly ("Where a person finds it", below). Listing order does not matter; the plan orders by dependencies, base members first |
| `loads` | no | Relative paths to fastfiles the linker loads for asset lookup: the base's zones. They may live beside the pack |
| `zone_header` | no | Linker metadata lines the base needs at the top of the zone (Zombies Declassified Beta 2 needs its `>level.ipak_read` rows); at most 32 |
| `budget` | no | Whole-number ceilings for the summed resource contracts. Absent means the totals are reported and not enforced. A number here is a decision you made after measuring, not a guess |
| `decisions` | no | One recorded owner per collision the plan listed (below). A decision naming a module that is not party to the collision is refused |
| `base_owned` | no | Up to 8 relative paths to plain asset listings of the base zones the composition loads (one `type, name` row per line, the shape an unlinker `--list` prints). A name collision whose asset the base already carries is classified `base-owned` and needs no decision: both seeds got their copy by linking against the base, and the base's copy is what loads. Names the listings do not carry stay decisions. A recorded decision for a base-owned name still wins. The same listings drive the exclusion below, so `--base-listings` usually replaces this field |

Member, load and base-listing paths cannot begin with `/`, including on Windows where
that spelling is rooted on the current drive rather than relative to the composition.

## What `plan` proves and what it does not

`pat module plan <composition.json> --output <new dir> --json` reads every declaration, recipe
and seed manifest, hashes every declared input and writes `plan.json`. It refuses, before any
backend runs, when:

- a dependency is not in the composition, a conflict is, or the dependency graph has a cycle;
- a module does not declare the composition's base or map;
- two members declare the same id, two members name the base role, or a nested composition is
  for another base or map;
- a seed file does not match its manifest hash, or a `private` module's package or recipe inputs
  are absent;
- the summed resource contracts exceed the budget;
- a declaration, manifest or recipe is malformed, or a member directory is missing, absolute or a link.

**Refusals are data.** Every refusal the composition has is collected in one run and reported
under `details.refusals[]`, each with `kind`, `modules`, `message`, `hint` and, when it names a
declaration field, `field`; the envelope's own `error_code`, `message` and `hint` are the first
row's, and a message with more rows says how many follow. Kinds: `probe`, `test_only`,
`duplicate_id`, `missing_dependency` (with `dependency` and `by`), `conflict`,
`unqualified_base` and `unqualified_map` (with `declared` and `wanted`), `private_payload`,
`cycle`, `budget` (with `resource`, `total`, `bound`), `replacement` (with `collisions`),
`parameters` (below, with `parameter`), `service` (below), `ownership` (with `path`, `owner`,
`evidence` and `service`), `exclusive` (with `role` and `resolutions`) and `port_status` (with `status`), all specified under
"What a module promises", and `checks` (with `failed`, the ids
of the failed check rows). A caller that brings dependencies along reads every
`missing_dependency` row at once instead of re-planning per message.

**Some collisions are a missing service, not a decision.** Two members that each ship their own
copy of a map-owned table (`animstatedefs/`, `animtrees/`, `aitype/`), two banks that carry the
same sound alias, or a member that registers a WeaponDef the map already carries (the shipped
`knowledge/native-weapons.json` table for the target map and foundation, plus any `base_owned`
listing) are refused with kind `service`: the row names the members, the thing
(`collision`, `what`) and, with `--workspace`, the shelf module whose `provides` owns it
(`service`), read from `modules/*/module.json` (`rawfiles` or `scripts` for a table, `aliases`
for an alias). The fix is a dependency edit, never an owner decision: the members depend on the
service and ship no copy. A file two members would both replace is owned by a service module,
never by either member.

Collisions are not refusals. Every place two modules would own the same thing is listed under
`decisions` (resolved) or `undecided`: the same file target (`kind: file`, resolved with no
decision when the bytes are identical), the same provided name such as a weapon or a localized
string (`kind: name`), or the same seed asset. Each undecided row names the modules and how to
record the owner. The agent is the runtime that resolves it; the planner is the linter that
lists it. The plan hash changes only when the recipe changes, so a recorded decision is part of
what was built.

With `--workspace <workspace> --target <foundation>/<map>/<mode>[/<location>]` (repeatable), the
plan also reads each target's location table as a hashed input and reports under `placements`,
per target, which members' declared `placements` needs the table satisfies, which fall back and
which are refused; a refused need fails the plan as a `placements:<target>` check. No provider
module is generated. Format and rules: [target-sets.md](target-sets.md).

### Declared parameters: what a composition configures, and the `parameters` refusal

A module declares the parameters a composition may set; a composition sets them per member; the
plan resolves the two into one effective map. Nothing else: the declaration is the whole
contract, and a parameter is a fact about the composition, never evidence about the game.

In `module.json`, what may be set:

```json
"parameters": [
  {"name": "cadence", "type": "string", "values": ["round", "timer"], "default": "round",
   "meaning": "round: reassign when a round ends. timer: wait between cycles."},
  {"name": "min_wait", "type": "int", "range": [5, 600], "default": 90,
   "meaning": "Timer cadence lower bound in seconds; ignored under the round cadence."}
]
```

In `composition.json`, what one member sets:

```json
"modules": [{"path": "../rotation", "parameters": {"cadence": "timer", "min_wait": 30}}]
```

Every plan row in `plan.json`, every `result.modules[]` row and every build receipt's
`modules[]` row carries `parameters`: the **effective map**, every declared default with what
the member set over it. A member that sets nothing is planned with the defaults; a module that
declares none carries an empty map. A build therefore records which configuration it is, and two
builds of one composition that differ only in a parameter are told apart by their receipts.

A name the member's module does not declare, or a value that does not satisfy that name's
declared type, `values` or `range`, is a refusal of kind `parameters`. The row names the member,
the parameter and the rule (`modules`, `parameter`, `field`, `message`), and every broken
setting in the composition is reported in one run, like every other refusal. The map's own shape
(names, at most 32 entries, scalar values) is checked in the composition before any module is
read. A malformed declaration — a default outside its own `range`, `values` on a `bool`, two
rows for one name, a 33rd parameter — is a declaration error, refused by `pat module inspect`
and by plan and build through the same path as any other declaration defect.

The package bytes do not change. No consumer reads a parameter yet: this is the contract and its
checks, so that a module whose behaviour a pack chooses has somewhere to declare the choice and
a plan can refuse a wrong one. A module that acts on a parameter still reads it from its own
source; the route that hands the effective map to a generated script is not in this version.

Proof of a successful plan: `ok: true`, `result.modules[]` in dependency order with each
member's `payload` (`recipe` or `seed`) and `role`, `result.base_member`, `result.decisions`,
`result.undecided`, `result.resource_totals`, `result.backends_available`. `plan.json` carries
each module's declaration, recipe or seed hashes, its provides, source, menu route, every seed's
roots and every script and asset the build will stage. Nothing is compiled and nothing about
play is proven.

## What `build` proves

`pat module build <composition.json> --output <new dir> --json` runs the plan and refuses while
any collision is undecided. Then it compiles every recipe module's scripts in dependency order
(only the recorded owner's copy of a collided file is staged), writes the merged string table,
writes the zone with the base's header lines and every seed's roots, links one `mod.ff` as zone
`mod` against every seed package and every load, copies the seeds' soundbanks beside it, reads
the package back, byte-compares every rawfile and checks that every seed root is in the
package. Proof: `ok: true`, `result.mod_ff` is `packages/mod.ff`, `result.rawfiles_verified`
counts every script and rawfile, `result.seed_roots_verified` counts every root, and
`receipt.json` has `status: succeeded` with every declaration, recipe, manifest, package and
source file under `inputs`. The receipt is verified later with `pat project verify <receipt>
--inputs`. Install the package and the soundbanks from `packages/` together.

A built composition is **offline verified**. Installed, launched, loaded, playable and accepted
are separate facts, each earned separately (`CONTEXT.md`, "Build evidence"). The fit and budget
checks come from declarations; the engine's real limits (`docs/knowledge/engine-limits.md`) are
measured only in game, and a composition's acceptance never transfers to another base or map.

## Bases, packs and attaching

The engine loads one `mod.ff`. "Add the Penetrator to my pack" is therefore never a runtime
stack: it is a new composition whose base member is the existing pack, plus the module, built
into a new profile, while the original pack stays untouched. A pack that ships its
`composition.json` is transparent, and the planner sees every module in it; a pack that is only
a `mod.ff` is a seed, declared from the package with `module declare`, and the planner sees what
the package provides. Either way the base pack is an ordinary member. To test a module on a base
or map it does not yet declare, build it alone there first (`port-a-feature.md`,
`package-and-install.md`), earn the verdict, then extend `bases` or `maps`.

A private recipe declaration can be inspected without opening its recipe or inputs, just
like a source recipe declaration. Inspection proves metadata only. Plan/build still validate
the recipe and require every local input; `private` does not bypass path or payload checks,
authorize publication, or make a foreign recipe format buildable. Private seed behavior is
unchanged: a missing package is reported when planning/building requires it.

## Qualifying a module for a target: `module qualify`

Extending `bases` or `maps` by hand is four commands and four edited files per module, and the
edits are only honest if they quote the build that earned them. `pat module qualify` is that loop
as one job:

```
pat module qualify <module dir> --target <foundation>/<map> --workspace <root> --output <new dir> --json
pat module qualify --set <file of module dirs> --target <foundation>/<map> --workspace <root> --output <new dir> --json
pat module qualify <module dir> --target <foundation>/<map> --workspace <root> --output <new dir> --accept loads-but-wrong --json
```

`--target` is `<foundation>/<map>`: the foundation id as the workspace's `foundations/<id>.json`
names it, never the base token. The base token is derived from that foundation's
`profile_prefix`, and a target whose foundation the workspace does not stage, or a map that
foundation does not stage, is refused before anything is staged or built.

Per module, in one job directory, each step leaving its own receipt:

| Step | Directory | What it is |
| --- | --- | --- |
| a | `<id>/shelf/`, `<id>/pack/` | the module and its declared dependency closure staged from the member roots, and a one-member composition `<base>_<id>_test` for the target with the foundation's `link_loads` and `mod_zone_header` |
| b | `<id>/plan-unqualified/` | `module plan --allow-unqualified` |
| c | `<id>/build-unqualified/` | `module build --allow-unqualified` |
| d | `<id>/verify-unqualified/` | `project verify --inputs` |
| e | `<id>/plan-qualified/`, `<id>/build-qualified/`, `<id>/verify-qualified/` | the same three after the **staged** declaration is widened |
| f | the module directory | the records, written together or not at all |

The synthesized composition is planned with the base's asset listings, which the workspace already
knows the location of: the directories the foundation record names under `base_listings`, and the
directory the link loads themselves sit in when it holds `<zone>-list.txt` files beside them. They
are passed exactly as `--base-listings <dir>` would, and `qualify.json` and the results table record
which directories were used under `base_listings`. Without them a module whose recipe loads a donor
zone refuses `donor-shadowing` before anything is built, for want of a listing the workspace had all
along; when no listing exists anywhere the refusal stands, because nothing then says which names the
base owns. One check is recorded rather than refused on: `loose-overrides` counts files in this
machine's global `storage/t6/images`, which no package contains and no build can change, so a module
built alone keeps its `failed` rows under `warnings` in `qualify.json` and the results table, adds
them to the built-alone note, and still qualifies. `module plan` and `module build` invoked directly
are unchanged and still refuse on that check: there the question is whether to ship a pack on this
machine, not whether this module builds on this target.

**An unfinished port: `--accept`.** A member whose `port_status` is not `finished` is refused by
the planner unless the composition names that status under the member's `accept` ("Where a person
finds it", below), and this is the one route that writes the composition for the caller. `--accept
loads-but-wrong` (or `--accept not-ported`; repeatable, 1 to 2 distinct values, the same vocabulary
and validation a member's own `accept` takes, an unknown word refused at the argument) is how the
caller says it. Every member of the synthesized composition whose declaration is not `finished` —
the module and its dependency closure alike — is then written as `{"path": …, "accept":
["loads-but-wrong"]}`; a finished member stays the plain path. The declaration's own `port_status`
is **not** changed by qualification. The acceptance is recorded where the build is claimed:
`qualify.json`, the results row, this route's receipt, the `docs/TEST.md` section, and the
`built-alone` note, which reads "port_status loads-but-wrong accepted for this build; the row says
the package builds, not that the port is finished." Without `--accept` nothing changes: the plan
refuses at step (b) and the results row carries it as `plan-refused` with the planner's
`port_status` row inside.

The declaration is widened in the staged copy, so both builds read the same paths and the two
packages are comparable. For a project recipe they must be the same bytes: a declaration is
metadata the package does not contain, and a difference means an input moved between the builds,
which is `package-mismatch` and writes nothing. An adapter recipe is a cut for one target
(above), so widening alone cannot qualify one: the route writes the target's cut as
`recipe-<base>.json` from the declared recipe with only `foundation`, `map`, `profile` and
`revision` changed, builds *that*, and records it under `recipes`. Its two packages carry
different profile names and are not compared. An existing cut already named under `recipes` is
reused; a `recipe-<base>.json` on disk that `recipes` does not name is refused, never
overwritten.

Only after the second verify are four records written, each citing the qualified receipts by
path (relative to the workspace when the job directory is inside it) and sha256:

1. `module.json` with `bases` and `maps` grown by exactly this target, plus the `recipes` entry
   for an adapter. Nothing else in the declaration moves, and the file keeps its own JSON
   serialisation so the diff is an addition and not a reformat.
2. a `docs/TEST.md` section quoting every receipt of this job and keeping the six facts apart.
3. an `evidence.json` `built-alone` row, written through the same validator `module state
   --ledger` reads (`docs/evidence-ledger.md`); the ledger is created when the module has none.
4. a build row on the module's entry in the workspace's `registry/module-recipes.json`, when the
   workspace keeps one and it has an entry for this module.

If any step fails, the job directory holds the refusal and **the module is untouched**: the
declaration, the test record, the ledger and the registry are byte for byte what they were.
Refusals are data under `details.refusals`, each with a `kind`: `dependency-unqualified`,
`adapter-recipe-single-target-without-recipes`, `missing-dependency`, `probe`, `map-scripts` (a
function this module replaces lives in a script the target map does not carry), `missing-fx` (the
linker could not resolve an effect root from the target's zones), `plan-refused`, `build-failed`,
`verify-failed`, `package-mismatch`, `records-refused`.

`--set` takes a file of module directories, one per line, `#` comments allowed. They run in
dependency order, one job directory each, continuing past failures, and `results.json` holds the
table: id, outcome, receipts, records, refusal. A module qualified earlier in the run is a
declared dependency for the ones after it. There is no parallelism inside the route; run several
jobs if you want it, each with its own `--output`.

A qualified module is **offline verified** on that target and nothing else. Installed, launched,
loaded, playable and accepted stay unknown, and the route never touches a game.

### The work orders a plan already knows: `adapt`

`module plan` reports `result.adapt`, one row per member that is not declared for the
composition's target: `{module, directory, target, pattern, detail, declared_bases,
declared_maps, work_order}`, where `work_order` is the `pat module qualify` command that would
earn the widening. The same list travels under `details.adapt` when the plan refuses for
`unqualified_base`/`unqualified_map`, so a caller reads work orders either way. `pattern` is what
the plan itself can decide — `map-scripts`, `map-guard` (the member's entry guard names another
map, so it is a port and no widening makes it run), `dependency-unqualified`,
`adapter-recipe-single-target-without-recipes` — and `unknown` for everything only a build can
find. Nothing is widened, built or written by `adapt`.

## Publishing a module

A repository is a module when its root, or a directory in it, holds `module.json` beside its
payload. An agent given that repository clones it, reads the declaration, and can plan it alone
or with others (`pat module build`). Fill `source.repository` and `source.commit` so a pack's
plan says exactly what it was built from. Ship source, scripts and the assets you have the
right to publish; a seed whose package cannot be published is listed as `distribution:
private`, which still lets others plan around it and makes the build fail honestly on the
missing package. A published composition is a list of pinned references, never a copy of
anyone's bytes.

## What is not in this version

- No catalog beyond a registry's generated listing: `docs/REGISTRY.md` has the registry file,
  `pat registry add|list|search|show`, `pat module fetch` and the official registry repository
  with its issue form.
- No version constraints on dependencies: an id is either present or not.
- Seed manifests carry no per-asset digest, so two seeds naming the same asset can only be told
  apart by a base listing (`base_owned`) or a recorded decision; the planner never compares the
  seeds' bytes for a name row.
- No detection of runtime conflicts that only the engine would show (competing hooks on the
  same level notify, pool exhaustion). Declare them under `conflicts` when you learn them, and
  record the crash signature per `docs/playbooks/diagnose-a-crash.md`.
- No map patches, client-script injection or shared core services beyond what a recipe or a
  seed already carries.
- No consumer for declared `parameters`: the effective map is checked and recorded in the plan
  and the build receipt, and no packaged byte depends on it.

### Unqualified targets

`module plan` and `module build` accept `--allow-unqualified`. A module whose declared base or map does not cover the target is listed in `unqualified` in the plan, result and build receipt instead of refusing. Dependency, conflict, game, input and budget checks still apply. Without the flag, base/map mismatches still refuse. This is a stated compatibility risk, never new build or gameplay evidence, and declarations are unchanged.

### Compose and publish

`pat module compose --name b2_example_pack --base b2 --map zm_factory --foundation foundation.json --member-root seeds --member-root modules --module example --output new-job --json` resolves module IDs in root order, includes matching `_registration` declarations and their dependency closure, and writes a recipe and nested plan. The recipe's `game` is the one title every member declares; members of two titles refuse, and `--game t6|iw5` states the title explicitly. A foundation's `link_loads` maps map IDs to file paths; optional `private_descriptor` points to a local expanded descriptor. `mod_zone_header` is copied with its map ipak line adjusted for the target. Available embedded foundation asset listings become base-ownership inputs. Unknown IDs or unstaged maps refuse; target mismatch warnings remain separate from evidence.

The result carries `composition`, `plan`, `plan_receipt`, `undecided` and `unqualified`. Nothing is installed. Build the returned composition with `module build --allow-unqualified` and a fresh output. To save the successfully built recipe as a template, use `module compose --composition <recipe> --from-build <receipt.json> --publish-to <templates/name> --output <new-job>`. Publication checks the exact recipe and package against the successful build receipt, rebases references for the destination and refuses an existing destination. Source declarations and prior recipes remain unchanged.

`game install-mod` accepts `--with-soundbanks` to copy sibling `.sabl`/`.sabs` files and `--profile-foundation foundation.json` to create the descriptor's `mod_load.ff`/`mod_load.ipak` links. Native symlink permissions are required for profile links; a failure restores the previous installation. The receipt lists copied soundbanks and link targets/hashes separately; none of these file operations launches the game.

### Source-map lineage metadata

Optional `lineage` records a T4/T5 source relationship: `[{"game":"t5","map":"zm_factory","source":"Example source variant","note":"Same-map witness; no T6 verification"}]`. One object is accepted for compatibility and normalized to an array by inspection. Arrays contain 1–18 entries, preserving multiple source maps or variants without claiming exclusive authorship. Notes are at most 400 characters. Only `t4`/`t5` and `zm_` map IDs are accepted. Lineage is descriptive metadata; plan/build ignore it and it never widens declared bases/maps or changes any evidence fact.

`lineage` is also the first row type of the evidence ledger: an optional `evidence.json` beside
`module.json` holds typed, scoped rows (`lineage`, `authored`, `accepted-in-pack`,
`extracted-from-release`, `built-alone`, `agent-reviewed`, `game-tested`, `player-accepted`,
`known-issue`) from
which the six facts are derived per scope, unknown kept unknown. `module inspect` validates it
when present; `module state --ledger` reports it. Format: [evidence-ledger.md](evidence-ledger.md).


## Workspace catalog records

`pat workspace catalog <workspace> --art-catalog <local-catalog.json> --json` joins
`modules/*/module.json` with optional `registry/module-recipes.json` build rows and
`registry/t6-modules.json` build revisions and weapon classes. It returns protocol
`pat.workspace-catalog/1`, declaration digests, declared provides, source paths and
record pointers. Missing flags remain null. Runtime verification is the record's
loaded/playable claim; no launch or capture fact is invented. Records from other maps
or foundations must stay separate. Top-level registry status and prose are not facts.

An optional local art catalog binds declaration IDs to artwork. Explicit HUD, reference-icon, `per-item wallbuy`, and `per-item menu art` roles
are eligible portraits; texture samples are excluded. An explicit binding records the
item identity and provenance decision; the role alone does not establish either. Icon IDs hash the
served file bytes, not a source filename. Foundation staging names its descriptor and
requires its per-map link-load files to exist. This is file presence, not gameplay.
The route reads files only and returns per-module diagnostics for invalid declarations.

Workspace catalog reads each module declaration once for both metadata and digest. It rejects
linked registry files with diagnostics, projects at most 256 builds per module and 256
foundation rows per workspace (64 maps per foundation), and caches shared icon hashes within
a 64 MiB aggregate image budget; once that budget is spent, later rows keep their place in
the catalog with a null `icon_binding` and a diagnostic naming the row. Malformed nested JSON
remains a structured failure.
Composition discovery has its own 64 MiB declaration budget; only the selected closure is
registered against the job's input cap. Publication validates all member, load and owned-list
paths before creating a saved recipe.

Directory enumeration itself is bounded (2048 module-directory entries, 64 foundation-directory
entries), before sorting. Catalog output escapes lone surrogate code points so the JSON reply
remains UTF-8 encodable. Foundation identity fields must be strings; an explicitly empty
link-load list is staged, because it requires no additional files.
Record-pointer labels are bounded before interpolation, so large registry identifiers cannot
amplify into hundreds of large retained strings. Non-string binding IDs use the module's
directory label. Output strings are bounded before UTF-8 escaping as well as afterward.
Catalog declarations use the same 256 KiB byte limit as declaration inspection. Each module's
`provides` projection is capped at 64 KiB, and one row is capped at 512 KiB serialized
(`--max-row-bytes`); a larger row becomes a diagnostic for that row only, sets `truncated`, and
never yields partial provides claims. Retained rows share one 16 MiB reply budget
(`--max-output-bytes`), sized for well over 1,000 rows of today's average size. Diagnostics are
separately bounded.

The reply always carries `total` (module rows that projected cleanly, whether or not this reply
holds them), `page`, `page_size` and `next_page`. Without flags the reply is page 1 holding
every row. `--page <n> --page-size <k>` (both together, 1-based) return one window of the sorted
module rows, and `next_page` is null on the last page; foundations and diagnostics are never
paged. If the reply budget fills inside a page, the first omitted row is named in a diagnostic,
the count of the rest follows, and `truncated` is set, so nothing is silently dropped: walk with a
smaller `--page-size`, or raise `--max-output-bytes`. TEST.md reads use a 512 KiB limit on the opened stream,
and at most 16 load paths per map are inspected, matching composition authoring.

## Test contract

A module may name a sibling contract with `"tests": "test-contract.json"`. `module inspect`
validates the named file and reports its exact-byte SHA-256, step and human-verifier counts,
and maps. A missing named file is `input_missing` at `/tests`. Modules without `tests` retain
metadata-only inspection. Contract fields are closed; unknown fields name their JSON Pointer.

| Field | Meaning |
| --- | --- |
| `schema`, `module` | Version 1 and the declaration's exact id |
| `maps` | Concrete declared map ids (any concrete id when the declaration uses `["*"]`), each with at most 16 ordered preconditions |
| `steps` | At most 64 unique ids, each with actor and verifier (`agent` or `human`) |
| `soak.rounds` | Whole number 0–10 |
| `human_only` | Every human-verifier step id exactly once |
| `not_covered` | Explicit coverage exclusions |

Actions use only `weapon_give`, `weapon_equip`, `weapon_upgrade`, `weapon_remove`, `gum`,
`gobblegum`, `recipe`, `mark`, `wait_s`, `fast_restart`, `check_load`, or probe verbs
`power_on`, `doors_open`, `points_set`, `round_set`, `perk_give`, `god`. Probe verbs require
a human actor and prompt in standalone contract validation. `module inspect` validates a
module alone and reports agent probe actions as `requires_probe` instead of refusing them.
Composition planning does not enforce that requirement in this release. Preconditions default
to an agent actor. Arguments contain at most 64 letters, digits, underscores, dots, slashes
or hyphens. No arbitrary console strings are admitted.

An agent verifier requires a check: `log` (present/absent regex, at most 200 characters),
`harness` (dotted key with equals/min/max), `dvar` (name and equals), or `screenshot`
(record only, no automatic visual assertion). Human actors/verifiers require a prompt.
Evidence may request a screenshot and clip-before/after seconds. `wait_s` is bounded to
300 seconds and each clip window to 60 seconds. Validation proves structure, not gameplay.
Excessively nested contract structures return an `input_invalid` diagnostic at `/` when
validation cannot copy them safely.

## Stitched test plan

`pat test plan --composition DIR --mode human --output NEW --json` reads the composition's
member contracts and writes protocol `pat.test-plan/1` with exact contract hashes. Member
steps follow dependency order; ids are prefixed by member. Preconditions deduplicate by verb
and argument, preserving the first position; conflicting actors refuse. Shared weapon, perk,
powerup or gobblegum providers get explicit pairwise setup/check actions in both directions.

Conflicting harness equality checks in one phase refuse with `test:<key>` until a composition
decision names an owner and reason. The losing steps are excluded and named in `excluded_steps`
and `not_covered`; the planner never silently turns a failed assertion into a passed one.
The four phases are load, members, interactions and soak. Human-only verification remains in
`human_steps`. Until a probe exists, nonzero soak is a human round-advance step, and background
plans refuse human preconditions/soak. A plan is preparation, not evidence that actions ran.

## Derived evidence state

`pat module state --composition DIR --plan PLAN --verify RECEIPT --test-plan TEST_PLAN
--run RUN --verdict ACCEPTED --json` computes composed, offline_verified,
ready_for_game_testing, game_tested, then player_accepted. Optional evidence paths stop at
whichever rung remains proven. Package bytes, the built plan when present in receipt outputs,
all receipt input hashes, exact member contracts, admitted run-plan digest and latest scoped
verdict must match in order. Without a built plan in the receipt, the plan's member declaration
hashes must be bound in the receipt's inputs instead. Changes revoke later claims and appear in
`reasons`; no state file is stored or updated.
A plan whose current member declaration hashes no longer match claims no state at all; with
unchanged declarations, a stale build input, a mismatched built plan or a package that no longer
matches revokes the claim to composed with the mismatch reason, never offline verified.
A plan that is not a well-formed composition plan (wrong schema, missing name/base/map, empty or
malformed module rows, duplicate ids, or undecided collisions) claims no state at all.

`pat module state --ledger <module dir|evidence.json> [--base --foundation --map --location --package --target] --json`
is the other subject of the route: it reads a module's evidence ledger and reports each of the
six facts per scope from the rows, `null` where no row of the matching type exists, with the
row numbers behind each value, and per `{base, map, location}` target under `by_target`;
`--target <foundation>/<map>/<mode>[/<location>]` queries one target ([target-sets.md](target-sets.md)). It never reads a plan or receipt and the composition form never
reads a ledger. [evidence-ledger.md](evidence-ledger.md) specifies the rows and the derivation.

## Checks

Composition plans contain `checks` with `passed`, `failed` or `not_counted`. Pool checks
use shipped map occupancy plus declared contributions; a floor above the observed bound
fails before linking, while incomplete counts remain uncounted. The composition's `base`
token is mapped to the occupancy foundation (`stock`, `b1` to `dlc5-beta1`, `b2` to
`dlc5-beta2`, or the workspace's `foundations/*.json` `profile_prefix` when `--workspace` is
given); a token with no known foundation leaves every pool `not_counted`.

Counted pools: `pool:rawfile-assets` (bound 1,024; every recipe script, every delivered
`rawfile` asset row and every seed `rawfile,` root, on top of the map's rawfiles),
`pool:image-bank-slots` (bound 16; every distinct `>level.ipak_read` header line beyond the
client's startup set, on top of the twelve it holds open, except that when the map's occupancy row
carries the optional `banks_present` inventory, a read naming a bank that folder lacks is skipped
by the engine, costs no slot, and becomes its own `not_counted` row instead of counting), `pool:sound-assets` (bound 32; the
listing shows one row per `.all` bank and the engine opens a localized companion beside each,
so every base bank and every member bank counts twice; a failed row lists the `banks`) and the
actor client field bits. A failed pool row carries
`contribution`, `base` and `contributors` (the members or bank names that add most), and the
plan's `footprint` lists every member's rawfiles, scripts and soundbanks so a caller can show
a meter before the engine does.

### Images have pixels somewhere, or the pack renders blank

A material names its images. **A fastfile carries an image's header and never its pixels** — a
`mod.ff` with fifteen freshly rooted 1024x1024 textures is sixty-four bytes larger than the same
zone without them. That is true whether the linker read the image from a disk `.iwi` the pack's own
zone declares (an `image` asset row) or resolved it from a zone the composition loads. The client
finds the pixels in exactly two places: an image bank (`.ipak`) named by a `>level.ipak_read`
header line, or Plutonium's global loose texture path `storage/t6/images`.

A mod folder's own `images/` is **not** one of them. Measured on Plutonium on 2026-09-15: a pack
that staged 25 `.iwi` files beside its `mod.ff` produced zero console mentions of any of them, and
the profiles that did render such images had the same files in `storage/t6/images` as well. The
build still writes `packages/images/` — those are the exact bytes the headers describe, and the
only thing that can be moved into either working route — but it is an artifact, not a delivery.
Copying into `storage/t6/images` is global to every mod on the machine and is the user's decision;
no route here writes it.

`image-sources` is that check. One row per image the plan can name, plus a summary row:

- an `image` asset row whose file is on this machine is `not_counted`: the zone gets a real header
  and the file is staged under `packages/images/`, but whether a bank or `storage/t6/images`
  carries the pixels is not readable from a plan, so this is never a `passed`;
- a declared row whose file is missing or empty is `failed`: the zone gets a header and nothing else;
- an image a member's zone listing only references (a seed's or an adapter's `image,<name>` root)
  is `not_counted` with that reason. Bank contents cannot be read without the banks, so the plan
  never calls such an image `passed` on its own.

`--image-report PATH` supplies the missing evidence: a readback of the built package taken with
the client's banks beside it. Every image it reports without pixels becomes a `failed` row naming
the image, the member that brought it in when one declares it, and the report's `located` hint;
a failed row refuses the plan like any other check. The report is one JSON object, hashed as a
build input:

```json
{"pack": "<composition name>",
 "images": [{"name": "t5_weapon_thundergun_n", "pixels": "missing", "located": "the module's prepared images/"},
            {"name": "camo_code_nml", "pixels": "present"}]}
```

A tool that lists only what it could not resolve is read too (`images_without_pixels` or `rows`,
as names or as objects with `image` and an optional `located`); in that shape every image the same
readback did resolve is absent from the list by construction, so an unlisted image is `passed`. In
the documented shape an image the report does not name at all stays `not_counted`. A report whose
`pack` is a different composition decides nothing and says so. Only names and hints are read,
never paths.

### A donor zone never answers a name the base already carries

A composition that ports content from another game loads that game's zones beside the target's own.
The linker follows every member's material closure and, for each image and material name it
reaches, copies whichever loaded zone answers first. It has no idea that some of those names belong
to the base. Because a fastfile carries a header and not pixels, a donor's copy of a base-owned name
puts a foreign header in front of the base's pixels, and the shared camo and Pack-a-Punch textures
render wrong on **every** weapon — including stock ones the pack never touched — while it is
selected. Measured on one three-weapon pack: 254 image headers, 135 with stock names, 91 of them
copied out of a donor zone, plus 30 materials.

`--base-listings <dir>` is how the composer is told which names are the base's. It takes a
directory of asset listings (`<zone>-list.txt`, the shape an unlinker `--list` prints) and is
repeatable. Every load with a listing there is one of the base's zones; every load without one is a
donor. Nothing else has to be declared — the classification comes from the composition's own
`loads`. A workspace can instead put the directory in `foundations/<id>.json` under `base_listings`
and pass `--workspace`; the explicit `base_owned` field still works and merges with both.

A load is also the base's when the foundation says so: with `--workspace`, a zone named in
`foundations/<id>.json`'s `maps.<map>.link_loads` is a base zone even with no listing staged on this
machine. A build against the foundation's own zones and nothing else therefore has no donor at all
and needs no listing — which is how `module qualify` links one module alone.

The build then excludes every base-owned `image` and `material` name from the pack's zone. The
mechanism is OpenAssetTools' own: an `ignore,<project>` row in the zone reads
`zone_source/assetlist/<project>.csv` off the source search path, and the asset creation context
answers an ignored name with a reference (`,<name>`) rather than a copy, so the name resolves at
runtime from the zone the client already has open. There is no per-name exclusion keyword and no
load-order knob — the first creator that answers wins, regardless of `-l` order — so this is the
only lever, not a preference among several. A name the pack itself roots with an explicit `image,`
or `material,` row is left out of the exclusion: that is a member's declared asset, and the
composition's collision decisions already own it.

`donor-shadowing` is the check. It refuses a composition that loads a zone outside its base with no
base listing at all, naming how many such zones are loaded; it refuses a member package that
already embeds a base-owned name; and at build time it re-reads the link log's
`Loaded <type> "<name>" (src: <zone>)` rows and refuses if any base-owned name was rooted from a
donor, with the count and the first ten names. The build reports `base_owned_excluded` and
`donor_shadowing`.

**Measure every asset type a donor answers; never assume which ones shadow.** The exclusion covers
`image` and `material` because those are the two types whose donor copy was measured to repaint the
base, and a linker's `ignore` list is per `type,name`: nothing about the mechanism stops at two
types. On the pack above, the rebuild that took base-named image copies from 166 to 0 and material
copies from 67 to 0 left 8 `techniqueset`, 4 `xmodel` and 7 `fx` copies of base-owned names in the
zone, because the type list had been chosen by reasoning about which types carry pixels rather than
by reading what the linker had actually rooted. Seven of those techniquesets turned out to be
byte-identical to the base's copy and harmless; one of the xmodels was not. **Every one of them was
a guess either way until it was read.** So after a build, read the link log yourself: group its
`Loaded <type> "<name>" (src: <zone>)` rows by type, keep the rows whose `src` is a donor zone and
whose name the base's listing also carries, and for each such type either exclude it or write down
why its donor copy is harmless. `donor-shadowing` only judges the two types it can exclude; the
other types are still in the log, and a type nobody looked at is not a type nobody shipped.

**A rendering fault is not evidence about a pack until the bare foundation has been loaded as a
control.** A wrong texture writes nothing to the console — no `Could not load image`, no unmatched
signature, no fatal line — so there is no log slice that clears the base and no readback that can.
A diagnosis proven by readback alone has only shown that the zone changed, not that the rendering
did. Load the base with no mod selected, on the same map, and look at the same weapon first. If it
renders wrong there, the pack is not the suspect and no composer change can be the fix; the cause is
in the base or on the machine (below). Only once the bare foundation renders correctly is a pack the
thing to change, and only then is a readback difference worth writing a composer change against.

A recipe asset row may carry `"deliver": false` (rawfile rows only): the file is hashed as a
build input but never staged or rooted, for authoring inputs such as model exports and source
WAVs that another row already compiles. Withheld rows are listed under `withheld` in the plan. The build still stages a withheld file under `raw/` at its target path with no zone line, so the linker finds the export, WAV or accuracy graph the compiled asset names; two members withholding different bytes at one path are a file collision like any other (`decisions`), and the build reports `withheld_staged`.

`externals:<script>` rows resolve a script's bare calls against `knowledge/stock-exports.json`,
which holds the export lists and declared parameter counts of the stock utility scripts per script
VM. The script's `#include` list is the scope: a call to a stock export the script neither includes
nor qualifies fails naming the owner, and a call carrying more arguments than any owner in scope
declares fails naming the counts and the include that would supply a declaration taking it. Fewer
arguments than declared is not a fault; GSC binds undefined to the rest. A qualified
`owner::name(...)` call is judged against that owner's arities alone, and naming a function the
owner does not export fails too, pointing at the row that does export it — the linker refuses a
qualified miss exactly as it refuses a bare one. Only a row flagged `complete` in the table can be
read that way; the client rows carry only proven names, so an absence there says nothing. Bare names no row owns and no
builtin witness covers are listed separately as `externals-unknown:<script>`, `not_counted` — they
cannot refuse a build, but they are where an unresolved external hides and they no longer share a
row with the verdict.

`clientfield-symmetry` is one pack-level check, read once per composition after every compiled
script has been named rather than per script. It groups every clientfield the pack's own staged
`.gsc` and `.csc` scripts register — a direct `registerclientfield("<set>", "<name>", ...)` or a helper
that registers one, such as `maps\mp\zombies\_zm_powerups::add_zombie_powerup("<id>", ...)`,
which registers `powerup_<id>` in set `toplayer` on whichever VM calls it — by `(set, name)`. A
name registered on exactly one VM is `failed`, naming the field, the set, the VM, the script and
the module, because the engine compares the server's registration list with the client's and
refuses the map with `EXE_CLIENT_FIELD_MISMATCH` at load, before a script runs: no compile, link
or readback can see it (crash signature `clientfield-registrations-mismatch`). The remedy in the
row is to ship the other half as a loose `scripts/zm` script — a `.csc` for a server registration,
a `.gsc` for a client one — that registers the same name with the same width and version,
unconditionally. A name registered on both VMs is `passed`; a pack that registers nothing on
either VM is `not_counted`. Registrations the stock map already makes on both VMs are outside the
pack and are never read here, and a call whose set or name is not a string literal is not read at
all. Only the scripts the build actually stages are read: where two members collide on one script
target the decided owner's copy is the package's, and the loser's bytes answer for nothing — a
discarded `.csc` cannot supply a client half the package will not carry. The pack's generated
entry script is a compiled row like any other and is read on the same terms. The whole check is T6's:
an `iw5` composition is one `not_counted` row, because clientfield registrations are a T6 two-VM
property and IW5 runs one script VM. A registration inside a conditional still counts as a
registration, and where the condition is not a plain `isdefined`/`level` guard — including an
outer `if` reached through nested brace-less statements — a second
`clientfield-symmetry:<name>:conditional` row fails as well: the other VM cannot read that fact, so guarding one half on state only one VM holds
inverts the mismatch instead of curing it. `CLIENTFIELD_HELPERS` in `dev/checks.py` is the helper
table; the next helper is one row.

`map-scripts:<script>` rows check every `#include` and qualified `path::call` into a stock
script namespace (`maps/`, `clientscripts/`, `common_scripts/`, `codescripts/`) against the
compiled scripts the target map's zones carry on that foundation (`knowledge/map-scripts.json`);
a path the map lacks fails, since it is an unresolved external at load that no compiler sees;
a path another member of the same pack provides is carried by the pack and passes — but only when
the pack ships it in a form this client opens: a target under a loaded root, or a `script,` zone row
a seed or adapter roots, which is a real scriptparsetree asset. A path the pack carries *only* as a
rawfile the engine never registers does not make the caller's call resolve; the row fails, names the
path, and points at its `script-reach` row. (Counting those was a false pass: the pack vouched for a
script nothing opens, and the caller got a green row before an `SV_Shutdown`.)

`script-reach:<target>` rows judge whether the client can open a compiled script at all, from the
root it is packed under. Every compiled script the toolkit links becomes a `rawfile,<target>` zone
row, and a T6 client registers a mod's rawfiles as scripts only under `scripts/zm/` (IW5: the flat
`scripts/` namespace): a load prints one `Overridden rawfile: scripts/zm/<name> from zone mod` per
script it accepts out of the zone and none at all for a rawfile rooted elsewhere, which is carried
into the zone and never opened. The failure surfaces only at the first qualified call into such a
path, as `Could not load scriptparsetree "<path>"` followed by unresolved externals and
`SV_Shutdown` — after a green compile and a byte-perfect readback, neither of which can see it.
A target outside the root fails with the retarget and the caller rewrite in its detail; a target
under it passes. One exception is `not_counted`: a stock script path the shipped map tables carry
is an *override* of a script the map's own zones already load, a case no receipt here settles, and
retargeting it would stop it being an override at all — replace such a function from a script under
the loaded root instead. The same root rule decides which compiled scripts travel loose beside the
package, so a script that passes the check is the script that is delivered.

A recipe's own `rawfile` asset row whose target is a `.gsc` or `.csc` is judged on the same root:
the pack roots that path itself, and the loose delivery copies it only from a loaded root, so
outside them it is neither registered nor delivered. It fails like a compiled target, where the
recipe naming it can be changed. A `rawfile` row already inside a *member's own package* — a seed's
`mod.ff`, an adapter's `rawfiles`, its embedded loose scripts — is `not_counted` instead: this pack
roots no target for it, so there is nothing here to retarget. The row exists so the drop is named
rather than silent, because nothing else names it — the build receipt's `loose_scripts` only omits
the path, and `map-scripts` judges the stock namespaces alone. If the pack needs that script, add
it under the loaded root in a module of the pack.

`map-guard:<script>` rows read the other half of "this script is on the wrong map", the half no
zone table can see. A module ported from another map often keeps its donor's entry guard: an
`if ( getdvar( "mapname" ) != "zm_transit" ) return;` as the first statement of `main()` or `init()`,
the `level.script` form of the same test, or the `==` form whose `else` returns. That script
compiles, links and loads on any map, and on a map the guard does not name its entry point returns
and the member does nothing — with no compiler diagnostic, no unresolved external and no load-time
line to read. One condition may name several maps (`!= "a" && != "b"`, or the `==`/`||` dual); that
is one guard over that set, and the row fails only when the target is in none of them, listing every
map the guard names. A guard naming the composition's own map passes; a source that never asks is
`not_counted`, because a script that never asks runs everywhere.

Because a failed row refuses the plan, the guard is read narrowly. It counts only as the entry
point's first real statement — prints, waits and assignments may precede it, since none of them
decides anything, but a `thread`, a call to another function or a block of any kind means the entry
point has begun its work — and only when its branch returns unconditionally: a bare `return;`, or a
block whose own statements are returns, prints and assignments. A map conditional further down, or
one whose branch holds a nested `if (...) return;`, is program logic and stays `not_counted`, which
means unread and never clean.

`csc-main-body:<target>` rows refuse a T6 client script that does its work in `main()`. The client
VM runs every loose `.csc`'s `main()` in one early pass and every `init()` in a second pass, so a
`main()` body runs before the client's own `_zm` rows exist and before any script's `init()`; the
client-script pass dies there with zero `CSC Executed` lines and no script error
(`knowledge/crashes.md`, `client-script-pass-died`). An empty or absent `main()` passes — the engine
links a no-op stub for an absent root — and a `.gsc` is `not_counted`, because a server `main()`
runs after the server's own rows and threading from it is the normal shape. `project plan` raises
the same rows for a recipe's own scripts. Projectile FX union requires
weapon blobs and is not inferred from weapon count. Soundbank listing is only a floor.
Builds run a receipted `gsc check` dry run per script before linking. Compiler-reported unresolved
externals fail; successful compilation alone cannot prove runtime external resolution and that
symbol check remains `not_counted`. Plans themselves do not run the compiler.

Probe actions with an agent actor cause `test plan` to include exactly one local sibling module
named `test_probe`, tagged `test-only`, on `_test`/`_probe` profiles; on a `_pack`/`_pub` profile
`test plan` refuses, because asking for the plan is asking for the probe. The planner searches
member siblings and the workspace's modules directory, refuses missing or ambiguous candidates,
and emits a buildable composition with the probe explicitly included. The probe is first in
dependency order.

**A probe verb in a member's contract does not follow the member into a release pack.** `module
plan` and `module build` read and validate every member's `tests` contract, but needing a probe is
a fact about running that member's test plan, not about composing a pack that contains it: a
`_pack`/`_pub` composition plans and builds unchanged with members whose contracts declare agent
probe verbs, and pulls no probe in. Only a `_test`/`_probe` composition carries the probe into the
package. What a release profile still refuses is a test-only member itself — declared or brought
along through a nested composition — with the typed `test_only` refusal. Probe-scoped contracts
permit signed `round_set +N`; this is a round-counter transition, not proof of N naturally
completed gameplay rounds.

### A loose global texture wins over every bank, and over the bare game

The second place pixels come from is not in any fastfile. Plutonium reads loose textures from the
global path `storage/t6/images`, and a file there wins: it applies to every mod folder on the
machine and to the bare game with no mod selected. A loose `<name>.iwi` whose name one of the base's
own zones carries therefore repaints that name everywhere — the Pack-a-Punch and camo textures a
stock weapon binds render from the loose file, on a pack that never touched them and on the
untouched base alike. It is machine state. No composition causes it, no composition can cure it, and
a readback of a package cannot see it, which is exactly why it survives a donor-shadowing fix and
still looks like the pack's fault.

`loose-overrides` is the check. It reads the loose path derived from the T6 storage folder the user
configured (`pat configure --plutonium-storage-t6 <path>`; the loose path is that folder's
`images/`), lists every `.iwi` there whose name appears in the base's own image listing, and refuses:
one `failed` row per file, `loose-overrides:<image name>`, plus a `loose-overrides` summary with
`count`, the first ten `names`, `path` and `loose_images` (how many loose textures it read). It is
refusal-grade for the same reason `donor-shadowing` is — the rendering is wrong and the pack is not
the cause — and refusing at plan time is what stops a machine-state fault from being shipped and then
diagnosed as a package.

Three answers are possible and the summary always says which:

- `passed` — the loose path was read and carries none of the base's image names (`counted: true`);
- `failed` — it was read and some of them are there (`counted: true`), with a row naming each file;
- `not_counted` — nothing was compared. Either no base listing says which names the base owns, or no
  T6 storage folder is configured, or the configured folder has no `images/` on this machine
  (`counted: false`, with a `hint` naming `pat configure` in the unconfigured case). An absent loose
  path is the ordinary case and is not a failure — but it is not a pass either, and the check says
  `not counted` rather than pretending it looked.

Nothing here writes or deletes a loose file: the folder is global to every mod on the machine and is
the user's to change. The fix is to move the file out and load the bare foundation again.

## What a module promises: ownership, roles, services and dependency kinds

A declaration already says what a module *registers* (`provides`), what it *needs* (`dependencies`)
and what it *must not meet* (`conflicts`). Measured on a private bank of several hundred
declarations, those name-level promises were honest wherever a byte could check them: every
`replaces.functions` target matched a `replaceFunc` in source in both directions, no module called
another module's script namespace without declaring the dependency, and no two modules provided the
same weapon or string. The file-level promises were empty: `replaces.files` was used by no module
while dozens of them staged copies of files the base or the map already carries, and nothing in
the format could say "only one of these can be in a pack", "this module exists to own a shared
file" or "this dependency is a sound bank, not a call". This section adds the four small pieces
that were missing, and a route that reads a module's own bytes back against its declaration so a
library can admit anyone's module on evidence rather than on trust.

Every field below is optional; a declaration written before this section is unchanged and valid.
Every new refusal is a typed row under `details.refusals[]` with the same shape as the rest
(`kind`, `modules`, `message`, `hint`, `field`, plus the fields named per kind), so a caller that
draws refusals as data draws these without new code. Nothing here reads a game, widens a base or a
map, or moves a byte in a package.

### The vocabulary, in one table

| Field | Type | What it promises | What a checker can verify from bytes |
| --- | --- | --- | --- |
| `replaces.files` | list of relative zone paths | "I overwrite this file the base or the map already carries" | Fully: the staged targets classified against the base's own listings and the shipped per-map tables |
| `exclusive` | list of role words | "Only one member of a pack can own this role, and I do" | Partially: a footprint per role (the calls, hooks or assets that role always touches); never that the module is the *right* owner |
| `service` | `true` | "I exist to own shared things; depend on me and ship no copy" | Partially: the module provides at least one shareable thing and registers no weapon of its own |
| `dependencies[]` entry as an object | `{id, kind, why?}` | "I need this module *because* I call it / name it / use what it owns / the engine needs it" | `call`, `name` and `service` fully; `runtime` is declaration-only and must say why |
| `registration` | `self`, `entry` or `none` | "My registration prints `<id> >> registered` to the console" (or the pack's entry prints it for me, or I print nothing) | The literal in source for `self`; the build's own output for `entry`; whether the line reached the console is the load's evidence, never the checker's |
| `system` | one of twelve system words | "A player looks for me under this system" | Nothing; a browse word, `not_counted` |
| `port_status` | `finished`, `loads-but-wrong`, `not-ported` | "I work as intended here" or "I load and misbehave" or "I am not ported yet" | Nothing from bytes; a person's verdict, read by the planner |

Seven fields, one of them a widening of an existing one. Nothing else was needed for the behaviours
the audit measured, and nothing else is designed here: placement, parameter consumers, versioning
and runtime conflict detection stay where `docs/MODULES.md` already puts them.

### File ownership: `replaces.files` is required for a base-owned path

A module that stages a file under a path the base or the target map already carries is
overwriting the base, whether or not any other member does the same. That is a promise about the
game, and it must be declared: **when a member stages a base-owned path and does not list it under
`replaces.files`, the plan refuses with kind `ownership`**. The row names the member, the path and
what owns it (`base` or `map`), and its hint gives the two honest fixes: declare the path, or
depend on the service module that owns it and ship no copy. One member is enough; the refusal does
not wait for a second one, because the overwrite does not.

Which paths are base-owned is read from evidence, never from a prefix list:

1. the base's own asset listings (`--base-listings`, a foundation's `base_listings`, or the
   composition's `base_owned`): every `rawfile,<path>` and `script,<path>` row is a file the base
   carries, so a member staging that path overwrites it. This is the same source the donor-shadowing
   check already reads, and it covers the map's animation tables (`animtrees/`, `animstatedefs/`),
   its AI type scripts (`aitype/`), the stock weapon scripts under `maps/` and `clientscripts/`, the
   visionsets and every other rawfile the zones carry;
2. the shipped per-map tables, read whether or not a listing is on the machine: `knowledge/map-scripts.json`
   for the compiled scripts the target map's zones carry on that foundation, and
   `knowledge/native-weapons.json` for the WeaponDefs (a member staging `weapons/<name>` for a
   native name is the same overwrite; the native-WeaponDef service refusal keeps firing for a
   *declared* native weapon under `provides.weapons`, and `ownership` covers the staged file);
3. `MAP_OWNED_PREFIXES` (`animstatedefs/`, `animtrees/`, `aitype/`) remains what it is today: the
   last resort for the two-member `service` refusal when neither a listing nor a table covers the
   target. It grows by nothing and it never refuses a single member on its own: a prefix is a guess
   about ownership (a module's *new* animation tree under `animtrees/` matches it and overwrites
   nothing), the two sources above are facts, and only a fact refuses one member.

Two consequences follow from reading ownership this way. First, `replaces.files` is widened from
"GSC or CSC scripts only" to any relative zone path (a table, a visionset, a `weapons/<name>` file
or a script), lowercase, forward slashes, at most 64. Second, **accuracy tables are not
base-owned by any evidence the toolkit holds**: no base zone listing carries a single
`accuracy/` row, because the engine reads those graphs from its own search path when a WeaponDef
is compiled, not from a fastfile. A member that delivers one as a rawfile is spending a rawfile
slot on a file that overrides nothing the pack can see, and two members delivering different bytes
at one `accuracy/` path stay what they are today, an ordinary file collision with a recorded
owner. `verify-declaration` lists such paths under `stages.engine_tables` with that explanation
so an author can decide to withhold them (`"deliver": false`), and the planner does not pretend to
know who owns them.

A declared overwrite of a path a second member also declares is the existing `replacement` hard
refusal (`file:<path>`), which no owner decision can clear. That row now also carries `service`:
the shelf module (with `--workspace`) whose `provides` owns the path, so the refusal says which
module both members should depend on instead of each shipping a copy. When neither member
declares the path, `ownership` fires for both and says the same thing. When one member is the
service itself (it declares `service: true` and provides the path), the other member's undeclared
copy is an `ownership` refusal naming that service, and its declared copy is a `replacement`
refusal naming it too: a file two members would both overwrite is owned by the service, never by
either member.

### Exclusive roles: `exclusive`

Some things in a Zombies pack have room for exactly one owner, and the format had no word for
them: the audit found seventeen modules drawing on the HUD with no notion that a full HUD
replacement excludes another, two dozen touching the mystery box with no declared conflict even
where one of them removes the box, and five hand-written `conflicts` pairs standing in for three
unnamed roles. `conflicts` cannot express a role: it names one other module, so a role with four
occupants needs six pairs kept in sync by hand, and a fifth occupant from someone else's repository
knows none of them.

`exclusive` is a list of role words from a fixed vocabulary. A module lists a role when it owns
that thing outright, not when it merely touches it.

| Role | Owned by a module that | Not owned by |
| --- | --- | --- |
| `hud` | replaces the HUD layout as a whole (a new HUD, a total restyle) | a widget that adds a counter, a timer, a compass; those coexist and declare only `resource_contract.hud` |
| `box` | decides whether the mystery box exists or how it chooses (removes it, re-weights it, replaces its selection) | a weapon that registers itself in the box; a module that adds names to the pool |
| `loadscreen` | stages the map's load screen material or image | anything else |
| `boss` | owns the special round (which boss comes, when, how many) | a boss whose module is only its assets and AI, brought by an owner |
| `perk-machines` | decides how perks reach the player as a system (rotation, Wunderfizz-only, fixed machines) | one perk, one machine at one site |
| `perk-art` | owns the perk presentation table (icons, shaders, names as a set) | a module that adds art for its own perk |

Six words. Core rules are deliberately **not** a role: a rule module declares the functions it
replaces under `replaces.functions`, that field is already exclusive per function, and the audit
showed eight working modules that replace different functions of one script; a "one script, one
owner" role would break every one of them for nothing. A module that needs a seventh word says so
in an issue with the pack that needed it; the list grows by a measured collision, not by
anticipation.

**The planner refusal.** Two members that list the same role refuse with kind `exclusive`:

```json
{"kind": "exclusive", "role": "hud", "modules": ["classic_hud", "modern_hud"],
 "message": "two members own hud: classic_hud, modern_hud",
 "hint": "A pack has one owner per role. Keep one, or drop the other from the composition.",
 "resolutions": [{"kind": "replace", "keep": "modern_hud", "drop": ["classic_hud"]},
                 {"kind": "refuse"}],
 "field": "/modules/3/exclusive"}
```

`modules` is in composition order, so the last one is the most recently added. `resolutions` is
what a review screen needs to draw the two honest outcomes: **replace** (the newest member wins
visibly, the others are dimmed, and undoing is one click because the composition is simply the
member list with one entry removed; the plan records nothing, since the fix *is* the member list)
or **refuse** (both stay, the pack does not build). There is no third kind and no owner decision:
a role is not a file, and "both, with one first" is exactly the ambiguity the role exists to
remove. A `conflicts` pair between two owners of the same role keeps working and is redundant; the
verify route says so.

**What a checker can see.** A role has a footprint in bytes: `hud` owners create HUD elements
(`newclienthudelem`, `createfontstring` and kin) or stage a menu; `box` owners replace a
`_zm_magicbox` function, set the box weight hook or call the chest functions; `loadscreen` owners
stage a `loadscreen` material or image; `boss` owners replace or hook the special-round functions
or stage an `aitype`; `perk-machines` owners replace `_zm_perks` functions or provide the rotation
or Wunderfizz scripts; `perk-art` owners define the perk shader or icon table. `verify-declaration`
reports, per declared role, whether that footprint is present (`agrees`) or absent
(`declared_not_observed`), and reports a role footprint the module has and does not declare as
`observed_not_declared` with the evidence, so an author sees "this looks like a box owner". It
cannot prove that a module with the footprint should own the role; that stays the author's
promise, and the row says `partial`.

### Services: `service`

A dozen modules in the audited bank are depended on by more than three others and nothing marks
them; the resolver's only way to name "the module you should depend on instead" was a free tag
that the documentation never mentioned. `service: true` is that mark as a typed field. It says:
this module exists to own things other members would otherwise each carry, so depend on it and
ship no copy. The planner prefers a `service: true` module over any other candidate when a
`replacement`, `ownership` or `service` refusal names the module to depend on, and reads the old
`shared-service` tag as the same mark for one release with a plan warning asking for the field.

A service must provide at least one shareable thing (a `rawfiles`, `scripts`, `soundbanks` or
`aliases` name, or an `exclusive` role) and must register no weapon of its own; a `service: true`
declaration that fails either rule is a declaration error at inspect time, because a weapon module
that also ships a shared table is the problem the service exists to solve, not its solution. That
is also what the checker verifies: the provides, and the absence of a weapon.

"Brought in by" needs no new field. A member that a plan pulled in through a dependency edge is
already reported as such by the caller that read the `missing_dependency` rows and added it; the
`by` field on those rows is the name to show. `service` adds the second half: when the plan
*refuses* because two members overwrite one file, the row now names the service to bring in, so
the same caller can offer the fix instead of only the diagnosis.

### Dependency kinds: what a dependency is *for*

`dependencies` stays a list of ids, and an id alone keeps meaning what it meant. An entry may
instead be an object that says why the dependency exists:

```json
"dependencies": [
  "powerup_runtime",
  {"id": "gum_audio_bank", "kind": "service", "why": "my activation sound is in the shared bank"},
  {"id": "powerup_insta_kill", "kind": "name"},
  {"id": "round_pacing", "kind": "runtime", "why": "reads level.round_pacing set by that module's init"}
]
```

| `kind` | Meaning | Verified by |
| --- | --- | --- |
| `call` | this module calls a script the dependency provides | a `<stem>::` or `<path>::` call in this module's source into a script the dependency provides |
| `name` | this module names a thing the dependency registers (a power-up, perk, gum, weapon or string id) | that name as a literal in this module's source or recipe |
| `service` | the dependency owns a file, table or bank this module uses, and this module ships no copy | none of the dependency's provided `rawfiles`, `scripts`, `soundbanks` or `aliases` appear among this module's own staged targets or bank rows |
| `runtime` | a relationship only the engine shows (a level variable, a notify, an order of init) | nothing; `why` is required and the row is declaration-only |

An entry with no `kind` is checked against all three observable kinds and the verify route
reports which one it found, or `none`. This is what turns the audit's largest unexplained number
(almost half the bank's dependency edges had no call in source) into three honest bins: an edge a
call justifies, an edge a name or a bank justifies, and an edge nothing justifies. In the audited
bank the second bin was mostly one sound bank depended on by every GobbleGum, which is a `service`
edge and always was; only the third bin is a question for the author. The planner treats every
kind alike for ordering and presence; the kind changes what can be checked, never what is built.

### Where a person finds it, and whether it works yet: `system` and `port_status`

Two more one-word fields, both with a closed list, both optional, both filled from evidence later
and never required of an existing declaration.

**`system`** is the player-facing system of T6 Zombies the module belongs to: the shelf a person
would look under, not the file type it is built from. `category` and `kind` are the toolkit's
build taxonomy and stay; a bank organised by them puts ninety-odd modules under `scripts`, which
is a junk drawer by a player's standard. One value per module, from:

`pack-a-punch`, `perks`, `hud`, `weapons`, `powerups`, `box`, `core-rules`, `gums`, `bosses`,
`equipment`, `audio`, `map`.

A module that spans two picks the one a player would look under (a perk that also changes the
box is `perks`). `system` is orthogonal to `exclusive`: a role is what a module owns outright and
refuses a second owner; a system is where a person finds it and refuses nothing. A library, a
shelf and a contribution form group by `system`; the planner ignores it. The checker cannot see
it in bytes and says so (`not_counted`).

**`port_status`** says whether a ported module does what it is meant to do on its target:

| Value | Meaning |
| --- | --- |
| `finished` | the module behaves as intended on the targets it declares; the default when absent, so nothing already declared changes |
| `loads-but-wrong` | the package builds and loads, and the behaviour is known to be wrong (a weapon that fires but has no sound, an effect that plays at the wrong place); the module stays in the bank so the work is visible |
| `not-ported` | the declaration exists and the port has not been made; nothing here is expected to load |

**The planner refusal.** A member whose `port_status` is not `finished` is refused with kind
`port_status` unless the composition names it explicitly: the member is written as an object
with `accept` listing the statuses the composition takes knowingly:

```json
"modules": [{"path": "../mark3", "accept": ["loads-but-wrong"]}]
```

```json
{"kind": "port_status", "modules": ["mark3"], "status": "loads-but-wrong",
 "message": "mark3 is loads-but-wrong and this composition does not accept it",
 "hint": "Write the member as {\"path\": ..., \"accept\": [\"loads-but-wrong\"]} to compose it knowingly, or leave it out.",
 "field": "/modules/2"}
```

One row per such member, collected with the other refusals in one run. A campaign or a shelf
reads the same field to skip such members by default; a member brought in as a dependency is
refused the same way, since the composition did not name it and its status has not changed.
`accept` on a member whose status is `finished` is harmless and recorded. `accept` takes values
from the list minus `finished`; a nested composition's members carry their own `accept`.

Both fields are echoed by `module inspect` when named, recorded on every plan row, and travel on
`expected_lines`' sibling rows nowhere else. Neither widens `bases` or `maps` or moves a byte in
a package.

### The registration line: one console line per module

A load is the last honest test and the console is its record. Today the only line a script is
guaranteed to leave is the engine's `GSC Executed "<path>::main()"`, and for a member whose
entry lives in the pack's generated entry script even that line names the pack, not the member.
Measured on one load campaign: two groups of twelve and eleven modules printed nothing at init, so
every game-tested row for them rests on "the entry script ran and no error named the module". A
script that returned early behind a map guard, or never reached its registration, reads the same
as one that worked.

The fix is one line per module in a shape nothing has to be hand-written to match:

```
<id> >> registered
```

The id is the declaration's own `id`, lowercase with underscores, followed by a single space,
`>>`, a space and the word `registered`. Anything after that on the same line is the module's
own (a version, a mode, a count); a match is by prefix, and ids contain no spaces, so a prefix
match is unambiguous across a pack. It is emitted with `println`, which T6 writes to the Zombies
console log unchanged, and it is emitted once, from the function that performs the module's
registration, after that registration has run: the line means "my registration ran", not "my
file loaded".

**The declaration says who emits it.** `registration` is optional and takes one of three words:

| `registration` | Meaning | Who writes the line |
| --- | --- | --- |
| `self` | the module's own server script prints the line from its registration path | the module's source |
| `entry` | the module is entry-managed (it declares `entry`) and the pack's generated entry script prints the line on its behalf, right after calling the module's `entry.register` function | `module build`, in the generated entry; no source edit |
| `none` | the module has no server script that runs at init (an asset-only service, a bank, a client-only script) and emits nothing; the pack must witness it another way | nobody |

`entry` on a module without `entry` is a declaration error at inspect time. Absent means the
declaration does not say, which is what every existing declaration means today, and changes
nothing about how the module builds or plans.

**What the plan derives.** `plan.json` carries `expected_lines`: one row per member,
`{id, registration, line}`, with `line` the exact prefix above for `self` and `entry` and `null`
for `none` or absent. The row is derived from the declaration and nothing else, so a load check,
a test plan and a campaign tool all read one list and none of them keeps its own. `pat test plan`
adds one step per `self` or `entry` member to the load phase, an agent-verified log check
`present: "^<id> >> registered"` (the id's underscores are literal; nothing in an id is a regex
metacharacter), beside the existing error-absence check. A member declared `none` or absent gets
no step and is listed under `not_covered` as "prints no registration line", so the plan says
where its coverage is thin instead of pretending.

**What the build emits.** For every `entry` member the generated entry script's `init()` calls
the member's register function and then `println("<id> >> registered");`. The order is the
composition's dependency order, as the calls already are. A `self` member's line is in its own
source and the build changes nothing about it.

**What a checker can see.** `verify-declaration` scans the module's server scripts, comments and
strings masked as for `replaceFunc`, for a `println` whose literal begins with the exact prefix:

| Declared | Found in source | Row |
| --- | --- | --- |
| `self` | yes | `agrees` (with `partial`: presence proves the literal exists, not that the path that prints it runs; the console proves that) |
| `self` | no | `declared_not_observed`; the fix is a source edit, and the row says so |
| `entry` | either | `agrees` when the declaration has `entry`; the line is the build's, so source is not consulted |
| `none` | yes | `observed_not_declared`: the module prints the line and says it does not |
| `none` | no | `agrees` |
| absent | yes | `observed_not_declared`; `--propose` fills `registration: "self"` |
| absent | no | `not_counted`, reason "the declaration does not say and the script prints no registration line"; `--propose` fills `"entry"` when the module declares `entry`, and otherwise names `self` as the edit an author would make |

A line whose token is the module's id in another spelling (upper case, hyphens, a prefix word)
is reported under `observed` so an author sees what is there, and does not match: the shape is
fixed so that a matcher never guesses.

**What this is not.** It is not a test contract step an author writes per module (the contract's
`log` checks stay for the module's own behaviour), not a claim that the module works (it says the
registration function ran, nothing after it), and not a replacement for the error scan (a line
followed by a script error is still a failure). It adds one rawfile to nothing: the line lives in
scripts that already exist.

### What a checker can verify, kind by kind

`pat module verify-declaration <module dir> [--workspace <root>] [--base-listings <dir>]
[--target <foundation>/<map>] [--strict] --json` reads one module's declaration, recipe, source
tree, seed manifest or adapter recipe, and reports every promise beside what the bytes say. It
creates no job, runs no backend and writes nothing; `--strict` exits 1 when any row differs, which
is what a library gate wants. The result protocol is `pat.module-verify/1`.

Every row has `field` (a JSON Pointer into the declaration), `declared`, `observed`, `how` (the
method, in words) and an `outcome`: `agrees`, `declared_not_observed`, `observed_not_declared`,
`partial` (the method sees only part of the truth, and the row says which part) or `not_counted`
(with the reason). The honest ceiling per kind:

| Promise | Method | Ceiling |
| --- | --- | --- |
| `provides.scripts` | recipe script and loose-script targets, seed or adapter script roots | full |
| `provides.rawfiles` | delivered rawfile targets, seed `rawfile,` roots | full |
| `provides.weapons` | recipe weapon rows, adapter `weapons`, seed `weapon,` roots, and registration literals in source (`include_zombie_weapon`, `add_zombie_weapon`, `register_tactical_grenade_for_level`) | full for a seed or adapter; `partial` for a project recipe whose weapon is registered through a computed name |
| `provides.localize` | the `REFERENCE` lines of every `.str` the recipe names, the adapter's `localize` map, `&"NAME"` in source | full |
| `provides.soundbanks`, `provides.aliases` | recipe soundbank rows and their alias CSV, adapter bank, seed bank files | full for banks; aliases full only when the CSV is on the machine |
| `provides.models`, `provides.effects` | recipe asset rows of the type, seed manifest | full for a seed; `partial` for a recipe whose models are pulled in by a WeaponDef rather than rooted |
| `provides.perks`, `provides.gobblegums`, `provides.powerups`, `provides.equipment` | the id as a string literal in this module's own source | `partial`: presence of the id, not proof it was registered (registration goes through another module's function with the id as one argument; a regex must not claim more) |
| `replaces.functions` | `replaceFunc(path::fn` in comment- and string-masked source, both directions | full for literal targets; a computed target is invisible, as today |
| `replaces.files` | every staged target classified base-owned by listing or table, both directions | full when a listing or table covers the target; `not_counted` per path otherwise, with `stages.base_owned`, `stages.engine_tables` and `stages.new_in_base_namespace` listed regardless |
| `dependencies` | per kind, as in the table above | `call`, `name`, `service` full; `runtime` declaration-only |
| `exclusive` | the role footprint | `partial` |
| `service` | shareable provides present, no weapon provided | full for the rule; the *intent* is declaration-only |
| `registration` | a `println` literal beginning `<id> >> registered` in a server script (`self`); the `entry` field (`entry`) | `partial` for `self` (the literal, not the path); full for `entry` and `none` |
| `version` | the folder's fingerprint against the commit that introduced the newest `evidence.json` row carrying a `package_sha256` (`built-alone`, `game-tested` or `player-accepted`) | full for the bytes it covers: `declared_not_observed` when they moved and `version` did not, `agrees` when they did not move or the version did, `not_counted` without a ledger, without git or outside a repository |
| `system`, `port_status` | nothing in bytes | `not_counted`: a browse word and a person's verdict |
| `resource_contract.hud` | count of HUD-element constructors in source, as a floor | `partial`: a floor, never the total |
| `conflicts` | both ends declaring the same `exclusive` role | reported as `redundant` when a role already covers the pair; otherwise `not_counted` |
| `menu_route`, `tags`, `placements`, `parameters`, `bases`, `maps` | nothing in this route | `not_counted`, with the reason (a menu tree, a location table, a receipt) |

`--propose` adds `proposal`: the declaration fields the observed side would fill (`replaces.files`
from `stages.base_owned`, dependency kinds from the evidence found, the provides rows that were
observed and not declared), written nowhere. A workspace fills its bank from that, one module at a
time, and the author decides what the route could not (a `runtime` dependency, a role, a service).
A proposal is an observation, not a verdict: it never removes a declared name, and a name it did
not observe is reported, not deleted.

Two limits are stated rather than hidden. The route reads a module alone, so a dependency's
provides come from the dependency's own declaration under `--workspace` (or are `not_counted`),
and whether a *base* owns a path needs the base's listing or the shipped table for the target;
without either, `replaces.files` rows are `not_counted` per path and the route says which
evidence would decide them. And a project recipe's `provides.weapons` is checked against the
recipe rows and the source literals the toolkit knows how to read; a module that registers a
weapon by building its name at run time is reported `partial`, never `agrees`.

**How to run it.** The route reads one module directory and needs nothing else to start:

```
pat module verify-declaration modules/my_module --json
pat module verify-declaration modules/my_module --workspace . --base-listings foundations/stock/listings \
    --target stock/zm_transit --strict --json
```

Each flag adds a source of fact, and the rows say what is missing without it: `--workspace` reads
each dependency's own declaration from `<root>/modules/*/module.json` (without it every
`dependencies` row is `not_counted`), `--base-listings` and `--target` are the two ways a path is
shown to be base-owned (without either, each staged path in a base namespace is `not_counted` and
the row names the evidence that would decide it), `--strict` is the library gate (exit 1, with the
whole report under `details.report`), and `--propose` prints the fields the observed side would
fill. There is no `--output`: the route writes nothing.

The `version` row needs no flag and reads the module's own history. It fingerprints the folder --
`module.json`, the payload the declaration names, the sources a recipe names, wherever they live
inside the module, everything under `src/`, and the test contract -- and compares that against the
same fingerprint at the commit that introduced the newest `evidence.json` row carrying a
`package_sha256`. A `.gdt`, an `.atr`, a `.str` or an accuracy graph a recipe row names is an
authored byte the builder hashes, so changing one owes a bump exactly as a script edit does; the
exclusions (`evidence.json`, `docs/`, `README*`, `prepared/`, `build-inputs.json`, `inputs.json`)
apply to the `src/` walk and the fixed names and never to a path a recipe row names, so `prepared/`
and `docs/` never count and a rebuild or an edited note never reads as a source change. Bytes that moved while `version` stayed where that commit left it
are `declared_not_observed` with one line saying to bump it; `--propose` moves the patch component
of a `MAJOR.MINOR.PATCH` version, and for anything else it says in `proposal_notes` that the bump is
the author's to make. A module with no ledger, a machine with no git, and a directory outside a
repository are each `not_counted` with the reason: the route never guesses a reference point.

### Refusal kinds added by this section

| Kind | Fires when | Row carries |
| --- | --- | --- |
| `ownership` | a member stages a path a base listing or a shipped per-map table says the base or the map carries, and does not declare it under `replaces.files` | `path`, `owner` (`base` or `map`), `evidence` (`listing` or `table`), `service` (the shelf module that provides the path, with `--workspace`, or null) |
| `exclusive` | two or more members list the same role | `role`, `modules` in composition order, `resolutions` |
| `port_status` | a member's `port_status` is not `finished` and the composition's member object does not list it under `accept` | `status` |

`replacement` rows gain `service`; `service` rows are unchanged. `REFUSAL_KINDS` lists both new
kinds, and a caller that folds kinds it does not know into "other" keeps working: the message
and hint are complete sentences on their own.

## Declared replacement

| Field | Contract |
| --- | --- |
| `replaces.functions` | Up to 256 lowercase, deduplicated `script/path::function` targets |
| `replaces.files` | Up to 64 lowercase, deduplicated relative zone paths the base or the map already carries (a script, a table, a visionset, a `weapons/<name>` file); required for every base-owned path a recipe stages ("What a module promises", `ownership`) |
| `entry.replace`, `entry.register` | Optional paired function references for generated entry ownership |

Engine callbacks, map/gametype main and gamemode_callback_setup are base-owned and refused.
These fields declare intent; source consistency, collisions and entry generation are checked
by composition planning/building as described below.

Overlapping declared functions (`function:<target>`) or replaced files (`file:<path>`) are
hard refusals. Owner decisions do not resolve them: the engine has one effective replacement.
Ordinary asset/file collision decisions retain their existing behavior.

Literal `replaceFunc(script::function, ...)` targets in recipe source must be declared or planning
fails with `declaration_mismatch` and the target in the hint. Backslashes and case normalize.
Comments and quoted literals are masked before the scan, so prose that names `replaceFunc` and a
`main`/`init` written in a comment are not read as code; a name boundary keeps a helper such as
`my_replaceFunc` from reading as the engine call, and `main`/`init` counts only with a function
body after its signature. Declared targets not found in available
source are warnings, preserving seed workflows.
This regex scan does not prove dynamically computed replacements or runtime detour behavior.

## Entry script

An entry-managed module exposes its declared replace/register functions and defines neither
`main()` nor `init()` (a definition inside a comment or a string does not count). The generated
script is `zz_<composition>_entry` under `titles.script_target` for the composition's game:
`scripts/zm/zz_<composition>_entry.gsc` on T6, and the flat `scripts/zz_<composition>_entry.gsc`
namespace on IW5. Its `main` calls replacements and its `init` calls registrations, both in
composition order; after each registration whose module declares `registration: "entry"` it prints
that module's `<id> >> registered` line ("The registration line", above).

The target is reserved case-insensitively against every recipe script, loose asset target and seed
rawfile before anything is staged, so a source that already maps that path refuses instead of
silently outliving the entry. The generated script is part of the plan's `scripts`, the script
limit and the per-script offline checks. An entry is generated as a server script, so its
reference must name a server `.gsc` recipe target: a client `.csc` target is refused, a same-stem
server/client pair resolves to the server target, and a reference that names no such target
refuses. The reference is normalized to lowercase; it is matched to that target case-insensitively
and the emitted `#include` and call use the canonical target path, so a mixed-case target resolves
on a case-sensitive host. It compiles against an include root holding each entry
member's recipe source at its canonical target path and its admitted source tree at the
source-relative path, so sibling and transitive `#include` directives resolve; two sources that map
one path with different bytes refuse. It uses the existing compiler, zone rawfile list and
byte-for-byte readback. Root scripts are normally each engine entry points; one generated owner is
needed for deterministic order. Other modules keep their existing roots.
