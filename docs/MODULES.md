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
  "donor": "Saints Row: The Third assets, converted for T6 by <who>, 2026"
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `schema` | yes | `1` |
| `id` | yes | The module's identity: lowercase letters, digits, underscore, at most 64. Other modules name it under `dependencies` and `conflicts`. Two modules in one composition cannot share an id |
| `version` | yes | A short version string. Recorded in the plan; the toolkit does not compare versions |
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
| `dependencies` | no | Ids of modules that must be in the same composition and are built first. A cycle or a missing dependency is refused |
| `conflicts` | no | Ids of modules this one must never be composed with. Both present is refused |
| `provides` | no | What the module registers, by kind: `weapons`, `perks`, `gobblegums`, `powerups`, `equipment`, `localize`, `soundbanks`, `scripts`, `models`, `effects`, `rawfiles`, `aliases` (the sound alias names a bank module owns), each a list of up to 4096 names. Two modules providing the same name is a decision (below); a `rawfiles` name is a file target and is listed once, as the file collision. A seed's manifest fills this in; for the kinds the manifest derives (`weapons`, `localize`, `soundbanks`, `rawfiles`, `models`, `effects`) a declaration may narrow the manifest's list and never add to it, even when the manifest lists none of that kind; the other kinds are the declaration's |
| `resource_contract` | no | Whole numbers the module adds to the engine's budgets: `threads`, `entities`, `hud`, `network_fields`. Missing fields count as 0. Summed across the composition and checked against the composition's `budget` |
| `menu_route` | no | How a person reaches the feature in game, at most 200 characters; carried into the plan for the handoff |
| `distribution` | no | `source` (buildable from the repository; the default for a recipe), `seed` (the package is committed beside the manifest; the default for a seed), or `private` (recipe source/assets or a seed package are not published; the payload type remains recipe or seed, and plan/build still require the local inputs) |
| `source` | no | Where the module comes from: an `https` `repository` URL and, ideally, the 40-hex `commit`. Carried into the plan so a pack can say what it was built from |
| `origin` | no | One lowercase word for the game or series the thing's identity comes from (`bo3`, `waw`, `saints-row`), or `unverified` when nobody has established it. It drives the title: an ICR-1 converted from a community pack is still "ICR-1 (Black Ops III)". Never defaulted to the donor. A browse word, never a resolution rule |
| `donor` | no | One line of credit, at most 400 characters, for where the bytes came from: a conversion pack and its author, a capture, a person. It drives the credit line, never the title. Preserved on every re-cut |
| `placements` | no | What the module needs placed on each target, never where: a list of `{needs, occupant?, count, fallback}` rows (`needs` a location-table row kind such as `perk-machine` or `wall-buy`; `count` `1`, an integer or `"any"`; `fallback` `refuse`, `rotation-slot`, `wunderfizz`, `spawn-room-default` or `omit`). `module plan --workspace W --target KEY` checks each need against the target's location table. Format: [target-sets.md](target-sets.md) |

Origin and donor are two facts, and a card shows both: "ICR-1 (Black Ops III)" with "from Chronicles
Reawakened v3.5 (Kosmoes), converted for T6" under it. A module whose origin is in doubt says
`unverified` rather than borrowing the donor's name, so the doubt is visible on the card.

A declaration says nothing about evidence. Whether the module is offline verified, installed,
playable or accepted on a base is a receipt's and a person's statement, not a field here; a
module that lists a base under `bases` has been built there by whoever wrote the declaration,
and the composition's own receipt is the only proof for the composed result.

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
| `modules` | yes | 1 to 128 members. A member is a relative path (forward slashes, from the composition's directory) to a directory holding `module.json`, **or** a directory holding another `composition.json` (its modules are flattened in; it must declare the same base and map; nesting is bounded), **or** an object: `{"path": …, "role": "base"}` marks the one member the others attach to; `{"name": "<github-owner>/<id>", "commit": "<40 hex>", "path": …}` records a published module pinned at a commit, with the local directory it was fetched into. Listing order does not matter; the plan orders by dependencies, base members first |
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
`service` (below) and `checks` (with `failed`, the ids of the failed check rows). A caller that
brings dependencies along reads every `missing_dependency` row at once instead of re-planning
per message.

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
the plan itself can decide — `map-scripts`, `dependency-unqualified`,
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
`extracted-from-release`, `built-alone`, `agent-reviewed`, `game-tested`, `player-accepted`) from
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

A recipe asset row may carry `"deliver": false` (rawfile rows only): the file is hashed as a
build input but never staged or rooted, for authoring inputs such as model exports and source
WAVs that another row already compiles. Withheld rows are listed under `withheld` in the plan. The build still stages a withheld file under `raw/` at its target path with no zone line, so the linker finds the export, WAV or accuracy graph the compiled asset names; two members withholding different bytes at one path are a file collision like any other (`decisions`), and the build reports `withheld_staged`.

`map-scripts:<script>` rows check every `#include` and qualified `path::call` into a stock
script namespace (`maps/`, `clientscripts/`, `common_scripts/`, `codescripts/`) against the
compiled scripts the target map's zones carry on that foundation (`knowledge/map-scripts.json`);
a path the map lacks fails, since it is an unresolved external at load that no compiler sees;
a path another member of the same pack provides (a staged script target, a seed or adapter
script root, a `provides.scripts` name) is carried by the pack and passes. Projectile FX union requires
weapon blobs and is not inferred from weapon count. Soundbank listing is only a floor.
Builds run a receipted `gsc check` dry run per script before linking. Compiler-reported unresolved
externals fail; successful compilation alone cannot prove runtime external resolution and that
symbol check remains `not_counted`. Plans themselves do not run the compiler.

Probe actions with an agent actor cause `test plan` and `module build` to include exactly one
local sibling module named `test_probe`, tagged `test-only`, on `_test`/`_probe` profiles.
The planner searches member siblings and the workspace's modules directory, refuses missing or
ambiguous candidates, and emits a buildable composition with the probe explicitly included.
The probe is first in dependency order. `_pack`/`_pub` compositions refuse every test-only member,
including through nested compositions. Probe-scoped contracts permit signed `round_set +N`;
this is a round-counter transition, not proof of N naturally completed gameplay rounds.

## Declared replacement

| Field | Contract |
| --- | --- |
| `replaces.functions` | Up to 256 lowercase, deduplicated `script/path::function` targets |
| `replaces.files` | Up to 64 lowercase, deduplicated relative GSC/CSC paths |
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
composition order.

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
