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

## Module declaration: `module.json`

Lives in the module's directory beside `project.json`.

```json
{
  "schema": 1,
  "id": "round_announcer",
  "version": "0.1.0",
  "title": "hello-zm-two",
  "category": "scripts",
  "recipe": "project.json",
  "bases": ["stock"],
  "maps": ["*"],
  "dependencies": [],
  "conflicts": [],
  "resource_contract": {"threads": 1, "entities": 0, "hud": 0, "network_fields": 0},
  "menu_route": "none; prints the round number when a round starts",
  "source": {"repository": "https://github.com/<owner>/<repo>", "commit": "<40 hex>"}
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `schema` | yes | `1` |
| `id` | yes | The module's identity: lowercase letters, digits, underscore, at most 64. Other modules name it under `dependencies` and `conflicts`. Two modules in one composition cannot share an id |
| `version` | yes | A short version string. Recorded in the plan; the toolkit does not compare versions |
| `title` | no | A display name, at most 120 characters. Defaults to the id |
| `category` | no | A lowercase identifier such as `weapons`, `perks`, `gobblegums`, `bosses`, `core`, `scripts`. Defaults to `module`; used for browsing, not for resolution |
| `recipe` | yes | Relative path to the module's `project.json`, inside the module directory |
| `bases` | yes | The base tokens the module has been built and tested on: `stock` for the unmodified game, or a base release's own short token. A composition on a base not listed here is refused |
| `maps` | yes | Map ids the module is built for, or `["*"]` for any map. A composition on a map not listed is refused |
| `dependencies` | no | Ids of modules that must be in the same composition and are built first. A cycle or a missing dependency is refused |
| `conflicts` | no | Ids of modules this one must never be composed with. Both present is refused |
| `resource_contract` | no | Whole numbers the module adds to the engine's budgets: `threads`, `entities`, `hud`, `network_fields`. Missing fields count as 0. Summed across the composition and checked against the composition's `budget` |
| `menu_route` | no | How a person reaches the feature in game, at most 200 characters; carried into the plan for the handoff |
| `source` | no | Where the module comes from: an `https` `repository` URL and, ideally, the 40-hex `commit`. Carried into the plan so a pack can say what it was built from |

A declaration says nothing about evidence. Whether the module is offline verified, installed,
playable or accepted on a base is a receipt's and a person's statement, not a field here; a
module that lists a base under `bases` has been built there by whoever wrote the declaration,
and the composition's own receipt is the only proof for the composed result.

## Composition recipe: `composition.json`

```json
{
  "schema": 1,
  "name": "stock_hello_pack",
  "base": "stock",
  "map": "zm_transit",
  "modules": ["../hello-zm", "../hello-zm-two"],
  "loads": [],
  "budget": {"threads": 4, "entities": 0, "hud": 0, "network_fields": 0}
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `schema` | yes | `1` |
| `name` | yes | `<base>_<feature>_<stage>` with the composition's own `base` token and a stage of `test`, `pack` or `pub` (`docs/knowledge/foundations.md`). It is also the install folder name |
| `base` | yes | The base token every module must declare |
| `map` | yes | One concrete map id. A composition is planned for one map; plan another composition for another map |
| `modules` | yes | Relative paths (forward slashes, from the composition's directory) to 1 to 32 module directories, each holding `module.json`. Listing order does not matter; the plan orders by dependencies |
| `loads` | no | Relative paths to fastfiles the linker loads for asset lookup, as in `project.json` |
| `budget` | no | Whole-number ceilings for the summed resource contracts. Absent means the totals are reported and not enforced. A number here is a decision you made after measuring, not a guess |

## What `plan` proves and what it does not

`pat module plan <composition.json> --output <new dir> --json` reads every declaration and
recipe, hashes every declared input and writes `plan.json`. It refuses, before any backend
runs, when:

- a dependency is not in the composition, a conflict is, or the dependency graph has a cycle;
- a module does not declare the composition's base or map;
- two modules would produce the same file inside `mod.ff` (a script target or an asset target);
- the summed resource contracts exceed the budget;
- a declaration or recipe is malformed, or a module directory is missing, absolute or a link.

Proof of a successful plan: `ok: true`, `result.modules[]` in dependency order,
`result.resource_totals`, `result.backends_available`. `plan.json` carries each module's
declaration and recipe hashes, its source, its menu route and every script and asset the build
will stage. Nothing is compiled and nothing about play is proven.

## What `build` proves

`pat module build <composition.json> --output <new dir> --json` runs the plan, then compiles
every module's scripts in dependency order, stages every asset, links one `mod.ff` as zone
`mod`, reads it back and byte-compares every rawfile, exactly as `pat project build` does for
one recipe. Proof: `ok: true`, `result.mod_ff` is `packages/mod.ff`, `result.rawfiles_verified`
counts every script and rawfile, and `receipt.json` has `status: succeeded` with every
declaration, recipe and source file under `inputs`. The receipt is verified later with
`pat project verify <receipt> --inputs`.

A built composition is **offline verified**. Installed, launched, loaded, playable and accepted
are separate facts, each earned separately (`CONTEXT.md`, "Build evidence"). The fit and budget
checks come from declarations; the engine's real limits (`docs/knowledge/engine-limits.md`) are
measured only in game, and a composition's acceptance never transfers to another base or map.

## Publishing a module

A repository is a module when its root, or a directory in it, holds `project.json` and
`module.json` together. An agent given that repository clones it, reads the declaration, and can
plan it alone (`pat project build`) or with others (`pat module build`). Fill `source.repository`
and `source.commit` so a pack's plan says exactly what it was built from. Ship source, scripts
and the assets you have the right to publish; a declaration for a module whose assets stay
private still lets others plan around it, and the build fails honestly on the missing files.

## What is not in this version

- No registry, index or download of modules: paths in `modules` are local directories. An agent
  fetches repositories itself.
- No version constraints on dependencies: an id is either present or not.
- No detection of runtime conflicts that only the engine would show (two modules registering the
  same weapon name, competing hooks on the same level notify). Declare them under `conflicts`
  when you learn them, and record the crash signature per `docs/playbooks/diagnose-a-crash.md`.
- No composition of asset-rich modules that need map patches, client scripts or shared core
  services beyond what `project.json` can express today. Those extend the recipe first.
