"""Registered development (file-tool) routes.

These routes run on Windows and Linux: they drive pinned upstream backends as
ordinary subprocesses and touch no running game. ``status="available"`` means a
native receipt is linked in docs/SUPPORT.md. None of these routes is
platform-gated; a backend that is missing for the current OS reports
``backend_unavailable`` with how to supply it via ``pat dev setup`` or a
``PAT_BACKEND_<NAME>`` override. macOS is untested and not claimed.
"""
from ..core.discovery import Route, register

OWNER = "thread-1-development"

AVAILABLE = [
    Route("dev", "backends", "List pinned backend programs, licenses and whether each is installed", "inert", owner="core"),
    Route("dev", "setup", "Download pinned backends over HTTPS, verify SHA-256 and extract into the backends directory", "downloads-backends",
          owner="core",
          notes="Use --plan to list without downloading; --only to select IDs. Runs no vendor installer. "
                "Pinned downloads are per-platform; where a platform has no pin, supply the tool with PAT_BACKEND_<NAME>."),
    Route("workspace", "catalog", "Read source-labelled workspace build records, declared provides and optional icon bindings", "inert", status="implemented", owner=OWNER, notes="Reads workspace files only. No fact is inferred; no game actions."),
    Route("workspace", "init", "Create a modding workspace directory for the person and their agent: AGENTS.md, module, composition, job, receipt, registry and donor directories, an ignore file and a record", "writes-output",
          status="implemented", owner="core",
          notes="Arguments: <directory> [--name <id>]. Refuses a non-empty directory and any location inside the toolkit checkout. Copies nothing; the skills already point at the checkout."),
    Route("dev", "install-skills", "Copy the toolkit's skills into the skills directories of the coding-agent harnesses found on this machine, with a receipt", "writes-config",
          status="available", owner="core",
          notes="Arguments: [--plan] [--only claude codex gemini opencode cursor hermes agents]... [--home <dir>] [--source <checkout>]. "
                "Detects a harness by its home directory; launches nothing. Writes absent files and files it wrote before; refuses "
                "any other existing file, any link below the resolved home and any oversized file with output_exists after writing the rest. "
                "Record and receipts under <toolkit home>/skills/."),
]

PLANNED = [
    Route("gsc", "compile", "Compile a GSC/CSC script with gsc-tool into a new output directory (--game t6|iw5; T6 runs the bytecode)", "writes-output",
          status="available", owner=OWNER),
    Route("gsc", "check", "Parse and compile a script with gsc-tool's dry run and write nothing; the syntax gate for IW5, whose client runs source", "writes-output",
          status="implemented", owner=OWNER,
          notes="Arguments: <script> [--game t6|iw5] [--includes <dir>]. Same diagnostics as compile; no output file."),
    Route("gsc", "decompile", "Decompile a compiled script with gsc-tool", "writes-output",
          status="available", owner=OWNER),
    Route("ff", "inspect", "List a fastfile's assets with OpenAssetTools Unlinker", "writes-output",
          status="available", owner=OWNER),
    Route("ff", "link", "Link a mod fastfile from a zone source with OpenAssetTools Linker", "writes-output",
          status="implemented", owner=OWNER),
    Route("ff", "extract", "Extract selected assets from a fastfile", "writes-output",
          status="available", owner=OWNER),
    Route("project", "init", "Create a minimal mod project and build recipe (--game t6 Zombies or iw5 multiplayer)", "writes-output",
          status="available", owner=OWNER),
    Route("project", "plan", "Validate a recipe and hash its declared inputs without running backends", "writes-output",
          status="available", owner=OWNER),
    Route("project", "build", "Compile, link, read back and compare a recipe into a new job directory", "writes-output",
          status="available", owner=OWNER),
    Route("project", "verify", "Re-hash a receipt's outputs and optionally its inputs", "writes-output",
          status="available", owner=OWNER),
    Route("model", "convert", "Convert a model/rig/animation through Blender and the Cast add-on", "writes-output",
          status="available", owner=OWNER),
    Route("model", "inspect", "Report bones, meshes, materials and animation ranges", "writes-output",
          status="available", owner=OWNER),
    Route("model", "transform", "Scale and rotate root objects, then export", "writes-output",
          status="available", owner=OWNER),
    Route("model", "rename-bones", "Rename bones from a JSON mapping without .001 collisions, then export", "writes-output",
          status="available", owner=OWNER),
    Route("model", "retime", "Rescale keyframes to a new FPS, then export", "writes-output",
          status="available", owner=OWNER),
    Route("model", "preview", "Render a 640px studio-lit PNG of the mesh", "writes-output",
          status="available", owner=OWNER),
    Route("audio", "inspect", "Probe format, streams and duration with ffprobe", "writes-output",
          status="available", owner=OWNER),
    Route("audio", "convert", "Convert and verify audio streams with FFmpeg", "writes-output",
          status="available", owner=OWNER),
    Route("image", "convert", "Convert DDS/IWI textures with OpenAssetTools ImageConverter", "writes-output",
          status="implemented", owner=OWNER),
    Route("lua", "decompile", "Decompile LUI bytecode with CoDLuaDecompiler", "writes-output",
          status="implemented", owner=OWNER),
    Route("weapon", "catalog", "Inventory a saved BO3 weapon asset library with provenance", "writes-output",
          status="implemented", owner=OWNER),
    Route("weapon", "plan", "Validate a normal/PAP weapon recipe against a catalog", "writes-output",
          status="implemented", owner=OWNER),
    Route("module", "inspect", "Validate one module or composition declaration without resolving payloads", "inert",
          status="implemented", owner=OWNER,
          notes="Argument: <module.json|composition.json> --json. Protocol pat.module-inspect/1; declaration-only, at most 256 KiB, no final-component symlinks, job, payload reads or network; symlinked ancestors allowed. Schema: schemas/module-inspect-v1.schema.json. A module's replacement declarations are validated here: replaces.functions is a list of script/path::function targets (at most 256; engine entry points are base-owned and refused), replaces.files is a list of relative zone paths the base or the map already carries, a script, a table, a visionset or a weapons/<name> file (at most 64), and entry.replace/entry.register each name the path::function a generated entry's main/init calls. An entry-managed module must not define main or init; metadata echoes replaces and entry when the declaration names them. A declaration may also name exclusive (role words from a fixed list this module owns outright), service (true when it exists to own shared things others depend on) and a dependencies entry as {id, kind, why} naming what the edge is for; replaces.files now accepts any relative base-owned zone path (a table, a visionset, a weapons/<name> file), not only a .gsc or .csc script, and metadata echoes exclusive, service and dependency_kinds when the declaration names them. A declaration may also name registration (self, entry or none: who prints the module's one console line <id> >> registered at init; entry needs an entry field, since the generated entry script prints the line after calling entry.register), echoed when the declaration names it. A declaration may also name system (the player-facing system a person finds it under, one word from a fixed list, a browse word the planner never reads) and port_status (finished, loads-but-wrong or not-ported: whether the port works yet, finished when absent), each echoed when the declaration names it. A declaration may also name reach (wall-or-box, machine, granted, drop, passive or menu: how a player gets to the feature on a map, with passive refused beside registration none and machine refused without a placements row naming the site kind) and hud (icon or none: whether a player can see they have it), each echoed when the declaration names it."),
    Route("module", "verify-declaration", "Read one module's own bytes back against its declaration: every promise beside what the recipe, the seed, the source and the base's listings say",
          "inert", status="implemented", owner=OWNER,
          notes="Arguments: <module dir> [--workspace <root>] [--base-listings <dir>]... [--target <foundation>/<map>] [--strict] [--propose] --json. "
                "Protocol pat.module-verify/1; schema: schemas/module-verify-v1.schema.json. Inert: no job directory outlives the call, no --output, "
                "no backend and no network. Every row carries field, declared, observed, how and an outcome (agrees, declared_not_observed, "
                "observed_not_declared, partial, not_counted), and the honest ceiling per promise is the table in docs/MODULES.md. provides.scripts, "
                "provides.rawfiles, provides.localize, replaces.functions and a call/name/service dependency kind are read in full; a project recipe's "
                "weapons, the models and effects, a perk or gum id as a literal, an exclusive role footprint and the resource_contract.hud floor are "
                "partial by method, never agrees; a runtime dependency, a menu_route, tags, placements, parameters, bases and maps are not_counted with "
                "the reason. replaces.files classifies every staged target against the base's own listings and the shipped per-map tables and reports "
                "stages.base_owned, stages.engine_tables and stages.new_in_base_namespace regardless; without either evidence each such path is "
                "not_counted and the row says which evidence would decide it. --strict exits 1 with input_invalid and the report under details.report "
                "when any row differs. --propose adds the declaration fields the observed side would fill; it never removes a declared name, and "
                "exclusive and service stay the author's decision. The /version row fingerprints the module's authored bytes "
                "(module.json, the payload, the sources a recipe names wherever they live inside the module, src/ and the test "
                "contract; the exclusions evidence.json, docs/, README*, prepared/, build-inputs.json and inputs.json apply to the "
                "src/ walk and the fixed names only, never to a path a recipe row names) against the same fingerprint at "
                "the commit that introduced the newest evidence row carrying a package_sha256, and reports declared_not_observed when "
                "the bytes moved and version did not, not_counted without a ledger, git or a repository, and a bumped patch component "
                "under --propose. The /reach row reads the byte footprint per word (an availability-table "
                "registration, a machine registration beside the declaration's own placements row, a give on player spawn "
                "or connect, a power-up registration, a replaceFunc, level variable or dvar set, or a menu_route naming the "
                "developer menu with no other footprint) and is partial at best, since a signature is a footprint and not "
                "proof the path runs; the /hud row reads an image or material asset row, a shader precache or a stock icon "
                "name, and is omitted entirely for a module whose reach is passive, since a rule with no pickup draws nothing "
                "for a player to see. --propose fills reach only when exactly one of wall-or-box, drop and passive is found, never machine, "
                "granted or menu, and fills hud: icon from the byte while never proposing hud: none. The /changelog row "
                "regenerates the page module changelog writes and compares it to the CHANGELOG.md on disk: agrees on the same "
                "bytes, observed_not_declared with the differing line count when the file was edited by hand or is stale, and "
                "not_counted when the module has no page at all. Writes nothing."),
    Route("module", "compose", "Write and plan a recipe from member IDs and a foundation, or publish a recipe after a successful build", "writes-output", status="implemented", owner=OWNER, notes="Use --name --base --map --foundation --member-root --module with a fresh --output. Publish with --composition --from-build --publish-to. No game actions."),
    Route("module", "plan", "Resolve a composition of declared modules (dependency order, conflicts, base and map fit, "
          "resource budget), list every collision as a decision, and hash every input without running a backend", "writes-output",
          status="available", owner=OWNER,
          notes="Use --allow-unqualified to report base/map mismatches without refusing. Formats: docs/MODULES.md. A module.json beside each recipe or seed; a composition.json naming base, map, members (modules, nested packs, pinned references), decisions and loads. Replacement declarations are resolved here: each literal replaceFunc(script::function) target in a module's available source must be declared under its replaces.functions, or the plan is refused (a dynamically assembled target is not scanned); each replaces.functions and replaces.files target must be owned by exactly one member (overlapping declared replacements are refused, never decided away); entry.replace/entry.register drive the generated entry's main/init. External-symbol checks resolve each script against its own VM (.gsc server, .csc client) using T6-only stock and witness data; a call needing an include is failed, and a call witnessed only on the other VM is not counted, never passed. A member that stages a path the base's own asset listings or the shipped per-map tables say the base or the map already carries, and does not declare it under replaces.files, is refused with kind ownership (naming the path, the owner, the evidence and the service module that owns the path when the shelf has one); two members that list the same exclusive role are refused with kind exclusive (naming the role and the two resolutions, replace or refuse).whose port_status is not finished is refused (kind port_status, with status) unless that member is written as an object listing its status under accept, so an unfinished port is composed knowingly or left out. A member pinned at a commit is read against the fetched directory's own git history, read-only and without fetching: a folder with commits after the pin gives the plan row a stale object (pinned, newest, commits_between) and one warning, an up-to-date pin gives stale null, and what git cannot answer gives a reason with no warning; it never refuses, and a local-path member carries no stale at all. Whether a player can reach each member is derived per composition and map: every plan row and summary row carries reachable (true, false or null) and a one-line reason read from the member's reach, the composition's own members and the placements outcome for the target, and every row that is not true adds a warning, as does a perks, gums, powerups or equipment member whose hud is none or absent -- warnings both, never refusals, because a person may want the module in the pack for a machine they will place later."),
    Route("module", "declare", "Read a prebuilt mod.ff back with OpenAssetTools and draft its seed manifest and module declaration", "writes-output",
          status="available", owner=OWNER,
          notes="Argument: <path to mod.ff> [--load base.ff]... [--id --title --category --base --map]. Writes seed.json and a draft module.json; the draft guesses id and category, never bases or maps."),
    Route("module", "fetch", "Download a published module or pack at its exact commit (owner/id@commit through a registry, or a GitHub URL) into a new directory with a receipt", "downloads-source",
          status="implemented", owner=OWNER,
          notes="Argument: <owner>/<id>@<40 hex> or https://github.com/<owner>/<repo>@<40 hex> [--path <dir>]. GitHub only, HTTPS tarball, no git, no token. The declaration must name the same repository and commit when it names any."),
    Route("dev", "builtin", "Fetch the built-in modules and packs the toolkit's own registry lists, at their pinned commits, into the toolkit home; a rerun verifies them", "downloads-source",
          status="available", owner="core",
          notes="Arguments: [--plan] [--only <owner/id>]... One HTTPS snapshot per repository and commit, hashed and extracted with the archive "
                "safety checks; the entry directories (and a pack's members and loads) are laid out under <toolkit home>/modules/builtin/<owner>/<repo>/<commit>/ "
                "with a receipt per entry. A changed tree is refused with artifact_changed, never overwritten. --plan touches no network. Nothing is installed into the game."),
    Route("registry", "add", "Record a registry file (local path or https URL): validated and copied under the toolkit home", "writes-config",
          status="implemented", owner=OWNER, notes="Argument: <path or https URL to registry.json>. Format: docs/REGISTRY.md."),
    Route("registry", "list", "List the registries on this machine: the built-in one that ships with the toolkit, then the ones you added", "inert", status="implemented", owner=OWNER),
    Route("registry", "search", "Search the built-in and recorded registries by words, category, kind, tag, base, map or origin", "inert",
          status="implemented", owner=OWNER, notes="Arguments: [words]... [--category --kind --tag --base --map --entry-kind --origin builtin|added]. Reads local copies only; a built-in hit carries builtin_dir once dev builtin fetched it."),
    Route("registry", "show", "Show every listing of one entry name with its fetch command", "inert",
          status="implemented", owner=OWNER, notes="Argument: <owner>/<id>."),
    Route("registry", "baseline", "Static, deterministic check of a module or composition directory before it is listed: "
          "executable headers, download-and-execute, links and path escapes, unpinned archives, declaration mismatches, "
          "and the capabilities a reviewer should know about", "writes-output",
          status="available", owner=OWNER,
          notes="Argument: <directory> [--repository <https url>] [--commit <40 hex>]. Reads every eligible file and nothing else "
                "(.git, links and unreadable entries are listed, not read): nothing in the tree is executed, no backend, no network, no model. Policy version 1, enforcement selective: native-plugin, "
                "download-and-execute and path-escape block; everything else is reported for review. Outcomes passed, "
                "review-required, needs-fixes, incomplete (unreadable files fail closed). Writes baseline.json. Not a security "
                "audit, certification, warranty or endorsement. Rules: docs/REGISTRY.md."),
    Route("module", "qualify", "Build one module alone on one target (declaration-blind, then qualified), verify both, and write its "
          "declaration widening, docs/TEST.md section, evidence.json built-alone row and workspace binding row from those receipts",
          "writes-output", status="implemented", owner=OWNER,
          notes="Arguments: <module dir> | --set <file>, --target <foundation>/<map>, --workspace <root>, [--member-root <dir>]..., "
                "[--accept loads-but-wrong|not-ported]..., --output <new dir>. "
                "One job directory; every step is a sub-receipt under it (composition, plan --allow-unqualified, build, project verify --inputs, "
                "then the qualified plan, build and verify). The declaration is widened in a staged copy of the module and its dependency closure, "
                "so a project-recipe module's two packages must be the same bytes; an adapter module gets the target's cut as recipe-<base>.json and a "
                "recipes entry instead. Nothing is written to the module until every step succeeded; on failure the job directory holds the refusal "
                "(details.refusals, kinds in dev/qualify.py REFUSAL_KINDS) and the module is untouched. A set runs in dependency order, continues past "
                "failures and writes results.json. --accept names the unfinished port statuses this build composes knowingly, from the "
                "member vocabulary: every member of the synthesized composition whose port_status is not finished is written as an object "
                "with that accept, and the accepted status is recorded in qualify.json, the results row, the built-alone note and this "
                "receipt. No declaration's port_status is changed by it. No parallelism inside the route; no game, network or install. "
                "Format: docs/MODULES.md."),
    Route("module", "accept", "Append one person's gameplay verdict to a module's evidence.json as a player-accepted row, "
          "scoped to the base, foundation and map it was given on and pinned to the package that was installed",
          "writes-output", status="implemented", owner=OWNER,
          notes="Arguments: <module dir> --outcome accepted|rejected --base <token> --foundation <id> --map <id> --package <sha256> "
                "--record <workspace-relative path> [--record-sha256 <hex>] [--reporter TEXT] [--quote TEXT] [--not-covered TEXT]... "
                "[--note TEXT] [--at ISO] [--workspace <root>] --output <new dir>. Records a verdict a person gave; it forms none and "
                "infers none. The row is validated through the same validator module state --ledger reads before the file is written, so "
                "a refusal leaves evidence.json byte for byte as it was; the ledger is append-only, and a second verdict is a second row. "
                "One member module per call: a verdict on a pack is written once per member. --workspace only reports whether the cited "
                "record resolves; a record it cannot find is reported, not refused. No game, network, install or build. "
                "Format: docs/evidence-ledger.md."),
    Route("module", "build", "Compile every module's scripts, stage every asset, link one mod.ff, read it back and compare every rawfile",
          "writes-output", status="available", owner=OWNER,
          notes="Use --allow-unqualified to report base/map mismatches without refusing. Same backends and readback as project build; the composition's fit and budget come from declarations, not from the game. The plan's refusals hold here too: a member staging a base-owned path it does not declare under replaces.files is refused with kind ownership, and two members listing the same exclusive role with kind exclusive.A member whose port_status is not finished refuses the build the same way the plan refuses it (kind port_status) unless the member lists its status under accept."),
    Route("knowledge", "builtin", "Does this call exist on a script VM, and with which argument counts: builtins derived from native call sites in the shipped Zombies zones, plus Plutonium and plugin extensions", "inert",
          status="implemented", owner=OWNER,
          notes="Argument: <name> [--vm server|client]. Data: src/plutonium_agent_toolkit/knowledge/builtins.json, generated by the maintainer; unknown means no shipped script calls it, not proof of absence."),
    Route("knowledge", "signature", "Match a console log slice against the recorded crash signatures: class, cause found and fix that worked, per line", "inert",
          status="implemented", owner=OWNER,
          notes="Arguments: --log <file> or --text <line>. Reads that file only; the log stays on this machine. Diagnosis reads, it does not fix."),
    Route("knowledge", "limits", "The observed engine limits and, per map, what the zones the engine loads already carry against each", "inert",
          status="implemented", owner=OWNER,
          notes="Argument: [--map <zm_map>]. Counts are zone contents from listings, decompiled text and WeaponDefs, never runtime pools; null means nothing on disk counts it."),
]

register(Route("module", "state", "Derive composition evidence state from exact artifact hashes, or report a module's six facts per scope from its evidence ledger", "inert", status="implemented", owner=OWNER,
               notes="--composition DIR [--plan --verify --test-plan --run --verdict] derives the composition rungs by hash. --ledger <module dir|evidence.json> [--base --foundation --map --location --package --target] reads evidence.json rows and reports each of the six facts per scope (a scope is base and/or foundation, a map set and optionally one survival location that never collapses into its map) and per {base, map, location} target; --target <foundation>/<map>/<mode>[/<location>] supplies foundation, map and location at once (docs/target-sets.md); a fact with no row of the matching type is null (unknown), and accepted-in-pack rows never feed a fact. A shipped row (the game ships this here, the provenance of distribution stock content) feeds none of them either and is reported separately as shipped, per scope and per target, where no row means false rather than unknown. known_issues lists the known-issue rows split into open and closed, a row being closed when its 40-hex closes_with commit is an ancestor of the module directory's current git head (read-only rev-parse and merge-base; a fix this checkout cannot place leaves the row open with ancestry unknown). Format: docs/evidence-ledger.md."))
register(Route("module", "changelog", "Generate one module's CHANGELOG.md from its own git history and its evidence ledger, grouped by the version each commit declared", "writes-record", status="implemented", owner=OWNER,
               notes="Arguments: <module dir> [--write | --check] --json. Protocol pat.module-changelog/1. **Only --write writes**: without it the route is inert and "
                     "prints the rendered page in the result, and --check writes nothing either. It takes no --output and creates no job directory or receipt; "
                     "--write replaces <module dir>/CHANGELOG.md through a sibling temporary file and one rename, refusing a path that is not a regular file. "
                     "Three read-only sources: git log over the module directory (bounded to 2000 commits, 20 s, never raising -- no git, no repository or no "
                     "readable history renders one paragraph saying so with the reason), the evidence.json beside the declaration (its known-issue, game-tested "
                     "and player-accepted rows; a module with no ledger simply has none), and the declaration's current version. A commit belongs to the version "
                     "its own declaration carried at that commit, read once per distinct declaration blob; a commit older than the declaration lands under "
                     "unversioned. Sections are newest version first with the declaration's current version leading even when no commit carries it yet, commits "
                     "newest first inside a section with a shared day broken by the sha, and each version's evidence rows are the ones whose at falls within its "
                     "commit dates (a row with no at, or one dated outside every span, goes under the current version rather than nowhere). Deterministic: the "
                     "same directory at the same commit renders the same bytes, and no timestamp of the run appears anywhere. --check compares byte for byte and "
                     "exits 1 with input_invalid, current false and diff_lines when the file differs or is missing. module verify-declaration reports the same "
                     "comparison as its /changelog row and never writes. Format: docs/MODULES.md."))
register(Route("module", "ledger-add", "Append validated rows to a module's evidence ledger: every row through the same validator module inspect applies, append-only and all-or-nothing", "writes-record", status="implemented", owner=OWNER,
               notes="Arguments: <module dir|evidence.json> --row <row.json> [--row ...] --json. Each row file holds one row object or a list of them, appended in the order given. "
                     "evidence.json is created with the module.json id as its subject when absent, and a ledger whose subject is a different id is refused. Every row is validated in the "
                     "context of the whole ledger (at most 1024 rows and 1 MiB after the write); one bad row writes nothing and reports every diagnostic with its row index and JSON Pointer. "
                     "Append-only: no existing row is edited or removed, and a row whose normal form the file already holds is refused with row_duplicate. The file's ensure_ascii and indent are "
                     "kept, so the diff is the rows added. Reports the appended indexes and, per appended row, the six facts the ledger now derives for that row's scope. No job directory, no "
                     "receipt, no game, no network. Format: docs/evidence-ledger.md."))
register(Route("module", "ledger-from-registry", "Propose evidence.json rows for one workspace module from the registry's build_revisions and the module's docs; prints the proposal and writes nothing", "inert", status="implemented", owner=OWNER,
               notes="Arguments: <workspace> <module-id> [--dry-run] --json. Reads registry/t6-modules.json, foundations/*.json, modules/<id>/module.json, docs/ACCEPTED.json, docs/LINEAGE.json, docs/TEST.md and the archive records the registry cites. Every proposal is a dry run: the worker reviews the rows and notes, then writes modules/<id>/evidence.json itself. Format: docs/evidence-ledger.md."))

for route in AVAILABLE + PLANNED:
    register(route)
register(Route("target", "list", "List a workspace's targets: stock and DLC5 maps from foundations/*.json plus the survival locations its registry/targets.json names, grouped by parent map, each with its route and whether a location table exists", "inert", status="implemented", owner=OWNER,
               notes="Arguments: <workspace> [--targets-file PATH] --json. A target is <foundation>/<map>/<mode>[/<location>]; one entry is one target on one route, and an entry on a route other than stock carries it as <key>@<route>. A location two providers ship is two entries listed under route_choices, never merged. Reads workspace files only; no game, network or build. Format: docs/target-sets.md."))
register(Route("target", "inspect", "One target's entry and its location table summary (rows by kind, literal versus expression, confidence, providers)", "inert", status="implemented", owner=OWNER,
               notes="Arguments: <workspace> <target-key>[@<route>] [--route R] [--targets-file PATH] --json. The table is registry/locations/<target-key>[.<route>].json; a missing table is reported, not refused, when the target is listed, and a key more than one route provides returns outcome route_choice with the routes instead of picking one. Format: docs/target-sets.md."))
register(Route("target", "validate", "Validate every location table under registry/locations and the target file: shape, target string and route-suffixed path, six facts false, literal or expression per row, vector arity, unique ids, cited record listed, high confidence with file and line, no T6 claims in notes, plus the entry rules", "inert", status="implemented", owner=OWNER,
               notes="Arguments: <workspace> [--targets-file PATH] --json. Entry rules: the id's route equals the entry's, the kind fits the key, a location's parent is listed, no two entries for one (target, route), a fence cites its route script, each location_table is at the path its id and route name and exists, each placements count equals its table's rows, and the file's targets count equals its distinct keys. Exit 1 with input_invalid and the diagnostics when any table or entry is malformed. Checks nothing about a map's geometry or T6; a table is source data and can never promote a rung. Format: docs/target-sets.md."))
