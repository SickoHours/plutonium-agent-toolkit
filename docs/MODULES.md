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

Lives in the module's directory beside its payload. The payload is one of two things: a
`project.json` **recipe** the toolkit compiles and links (scripts and loose assets), or a
**seed**, an already-linked `mod.ff` with its soundbanks and a `seed.json` manifest that
`pat module declare` writes from the package. A declaration names exactly one of `recipe` or
`seed`.

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
| `recipe` | one of | Forward-slash relative path to the module's `project.json`, inside the module directory; no Windows drive prefix or rooted path, on any host |
| `seed` | one of | Forward-slash relative path to the module's `seed.json`, inside the module directory, with `mod.ff` and its soundbanks beside it; no Windows drive prefix or rooted path, on any host. Path checks also apply to private declarations whose manifest is absent |
| `bases` | yes | The base tokens the module has been built and tested on: `stock` for the unmodified game, or a base release's own short token (`b2` for Zombies Declassified Beta 2). A composition on a base not listed here is refused |
| `maps` | yes | Map ids the module is built for, or `["*"]` for any map. A composition on a map not listed is refused. Grow this list by testing on the map, never by editing |
| `dependencies` | no | Ids of modules that must be in the same composition and are built first. A cycle or a missing dependency is refused |
| `conflicts` | no | Ids of modules this one must never be composed with. Both present is refused |
| `provides` | no | What the module registers, by kind: `weapons`, `perks`, `gobblegums`, `powerups`, `equipment`, `localize`, `soundbanks`, `scripts`, `models`, `effects`, `rawfiles`, each a list of up to 4096 names. Two modules providing the same name is a decision (below); a `rawfiles` name is a file target and is listed once, as the file collision. A seed's manifest fills this in; for the kinds the manifest derives (`weapons`, `localize`, `soundbanks`, `rawfiles`, `models`, `effects`) a declaration may narrow the manifest's list and never add to it, even when the manifest lists none of that kind; the other kinds are the declaration's |
| `resource_contract` | no | Whole numbers the module adds to the engine's budgets: `threads`, `entities`, `hud`, `network_fields`. Missing fields count as 0. Summed across the composition and checked against the composition's `budget` |
| `menu_route` | no | How a person reaches the feature in game, at most 200 characters; carried into the plan for the handoff |
| `distribution` | no | `source` (buildable from the repository; the default for a recipe), `seed` (the package is committed beside the manifest; the default for a seed), or `private` (recipe source/assets or a seed package are not published; the payload type remains recipe or seed, and plan/build still require the local inputs) |
| `source` | no | Where the module comes from: an `https` `repository` URL and, ideally, the 40-hex `commit`. Carried into the plan so a pack can say what it was built from |
| `origin` | no | One lowercase word for the game or series the thing's identity comes from (`bo3`, `waw`, `saints-row`), or `unverified` when nobody has established it. It drives the title: an ICR-1 converted from a community pack is still "ICR-1 (Black Ops III)". Never defaulted to the donor. A browse word, never a resolution rule |
| `donor` | no | One line of credit, at most 400 characters, for where the bytes came from: a conversion pack and its author, a capture, a person. It drives the credit line, never the title. Preserved on every re-cut |

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
Localized strings cannot be copied out of a loaded fastfile, so `declare` extracts them to
`mod.str` and `module build` merges every seed's strings into the pack's own string table.

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
| `base_owned` | no | Up to 8 relative paths to plain asset listings of the base zones the composition loads (one `type, name` row per line, the shape an unlinker `--list` prints). A name collision whose asset the base already carries is classified `base-owned` and needs no decision: both seeds got their copy by linking against the base, and the base's copy is what loads. Names the listings do not carry stay decisions. A recorded decision for a base-owned name still wins |

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
- a seed file does not match its manifest hash, or a `private` module's package is absent;
- the summed resource contracts exceed the budget;
- a declaration, manifest or recipe is malformed, or a member directory is missing, absolute or a link.

Collisions are not refusals. Every place two modules would own the same thing is listed under
`decisions` (resolved) or `undecided`: the same file target (`kind: file`, resolved with no
decision when the bytes are identical), the same provided name such as a weapon or a localized
string (`kind: name`), or the same seed asset. Each undecided row names the modules and how to
record the owner. The agent is the runtime that resolves it; the planner is the linter that
lists it. The plan hash changes only when the recipe changes, so a recorded decision is part of
what was built.

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


## Workspace catalog records

`pat workspace catalog <workspace> --art-catalog <local-catalog.json> --json` joins
`modules/*/module.json` with optional `registry/module-recipes.json` build rows and
`registry/t6-modules.json` build revisions and weapon classes. It returns protocol
`pat.workspace-catalog/1`, declaration digests, declared provides, source paths and
record pointers. Missing flags remain null. Runtime verification is the record's
loaded/playable claim; no launch or capture fact is invented. Records from other maps
or foundations must stay separate. Top-level registry status and prose are not facts.

An optional local art catalog binds declaration IDs to artwork. Only explicit HUD or
reference-icon roles are portraits; texture samples are excluded. Icon IDs hash the
served file bytes, not a source filename. Foundation staging names its descriptor and
requires its per-map link-load files to exist. This is file presence, not gameplay.
The route reads files only and returns per-module diagnostics for invalid declarations.

Workspace catalog reads each module declaration once for both metadata and digest. It rejects
linked registry files with diagnostics, projects at most 256 builds per module and 256
foundation rows per workspace (64 maps per foundation), and caches shared icon hashes within
a 64 MiB aggregate image budget. Malformed nested JSON remains a structured failure.
Composition discovery has its own 64 MiB declaration budget; only the selected closure is
registered against the job's input cap. Publication validates all member, load and owned-list
paths before creating a saved recipe.

Directory enumeration itself is bounded (512 module-directory entries, 64 foundation-directory
entries), before sorting. Catalog output escapes lone surrogate code points so the JSON reply
remains UTF-8 encodable. Foundation identity fields must be strings; an explicitly empty
link-load list is staged, because it requires no additional files.
