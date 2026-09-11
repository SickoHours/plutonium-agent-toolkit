# Plutonium Agent Toolkit: vocabulary

This project builds, controls and tests Plutonium T6 Zombies mods through a coding agent. The
words below are the ones every document, receipt, skill and prompt in this repository uses. Use
them exactly. When two words exist for one thing, the canonical word is in bold and the others
are listed under _Avoid_.

Format follows Matt Pocock's `CONTEXT.md` convention (see `vendor/matt-pocock/`): one term, one
or two sentences, what it is rather than what it does. No implementation detail lives here.

## Base and build layers

**Foundation**: An upstream release or the stock game, hash-verified and never edited.
_Avoid_: base game, vanilla, clean install

**Base**: The foundation a module is built and tested on, named in every receipt by id and hash.
_Avoid_: pack, template, current build

**Module**: One feature (a weapon family, perk, equipment, boss, companion) with its own source,
recipe, assets, tests, menu route and resource contract.
_Avoid_: mod, feature pack, addon

**Core module**: Shared runtime plumbing other modules depend on by id, such as an inventory
arbiter or an item registry.
_Avoid_: shared code, library, helpers

**Composition**: A named set of pinned module revisions on a named base, with a sealed recipe
and its own evidence record.
_Avoid_: mod pack, bundle, all-in-one

**Profile**: One installed folder under Plutonium's `mods`, named `<base>_<feature>_<stage>`.
Stages: `test` (one module alone), `pack` (a composition), `pub` (a release candidate).
_Avoid_: mod folder, build, install

**Global tooling**: Scripts Plutonium loads for every profile from its global scripts folder.
Released separately from any module.
_Avoid_: menu mod, global mod

## Producing files

**Recipe**: The declarative `project.json` that names a mod's scripts, assets and dependency
loads explicitly.
_Avoid_: config, build script, manifest

**Declaration**: The `module.json` beside a module's payload (a recipe or a seed) that states what
the module is and needs: id, version, category and kind, the bases and maps it was built for,
dependencies, conflicts, what it provides and its resource contract. Facts for composing, never
evidence (`docs/MODULES.md`).
_Avoid_: manifest, metadata, package file

**Seed**: A module payload that is an already-linked `mod.ff` with its soundbanks and a hashed
manifest (`seed.json`) listing what it embeds, references and provides. A pack links against it
and names its roots; `module declare` writes the manifest from the package.
_Avoid_: prebuilt, binary module, blob

**Base pack**: The composition everything else in a new pack attaches to, named with
`"role": "base"`. It is an ordinary member: its modules are staged first and it is the first
thing a person names when they say "add X to Y".
_Avoid_: parent, template, upstream pack

**Decision**: A collision two modules produce (the same file, the same weapon or string name)
that `module plan` lists and that the composition recipe records with an owner. Identical bytes
need none; `module build` refuses while one is undecided.
_Avoid_: conflict (that is a declared incompatibility), override, merge rule

**Composition recipe**: The `composition.json` that names a base, one map, the members (module
directories, other compositions, or pinned references), the recorded decisions and an optional
resource budget; `module plan` resolves it and `module build` produces one `mod.ff` from it.
_Avoid_: pack file, modpack config, bundle

**Plan**: A validated, hashed preview of a recipe that runs no backend. It proves the inputs,
not the build.
_Avoid_: dry run, preview build

**Job**: One toolkit invocation that runs backends and writes into one new output directory.
_Avoid_: run (reserved for tests), task, command

**Receipt**: The `receipt.json` a job writes: argv, input hashes, output hashes, backend pins,
logs and status. Failures keep their receipts.
_Avoid_: log, result file, manifest

**Readback**: Unlinking the produced fastfile and comparing the extracted `rawfile` entries
(compiled scripts and declared rawfiles) byte-for-byte with the inputs. Readback proves those
entries are in the package as built; other asset types are listed, not compared, and nothing
about play is proven.
_Avoid_: verification, validation

**Backend**: An upstream program the toolkit drives as a child process, pinned by version and
SHA-256 or supplied by override.
_Avoid_: tool, dependency, binary

**Pin**: The exact upstream release and hash a backend resolves to on one platform.
_Avoid_: version, download

**Override**: A `PAT_BACKEND_<NAME>` path that replaces a pin with a tool already on the machine.
_Avoid_: custom path, local tool

**Fastfile**: A linked `.ff` package the engine loads. A mod's package is `mod.ff`, a fixed name.
_Avoid_: archive, bundle, zone (a zone is the source list, not the output)

**Rawfile**: A script or text asset carried inside a fastfile.
_Avoid_: file, script asset

**Instance**: Which script virtual machine a script runs in: `server` (`.gsc`) or `client`
(`.csc`). Each has its own builtin list.
_Avoid_: side, mode, context

## Sources of assets

**Donor**: A game or capture that supplies models, animations, audio or scripts for a port.
_Avoid_: source game, reference

**Sealed donor**: A donor whose files are inventoried and hashed into a catalog receipt so later
plans can prove they used the same bytes.
_Avoid_: snapshot, archive

**Registry**: A `registry.json` anyone can host, listing module and composition repositories at
exact commits; it holds metadata and points at repositories, never bytes (`docs/REGISTRY.md`).
_Avoid_: marketplace, store, index

**Entry**: One listing in a registry: `<github-owner>/<module id>`, the repository, the path, the
listed commit, and a summary of the declaration at that commit.
_Avoid_: package, listing (say entry), record

**Reference**: A composition member that names an entry and a commit beside the directory it was
fetched into, so a pack records exactly what it was built from.
_Avoid_: dependency (that is a declaration field), link, import

**Catalog**: The generated, browseable projection of one or more registries. Read-only; produced
from registries and declarations, never edited by hand.
_Avoid_: registry (the source), marketplace, index

**Built-in**: A module or pack the toolkit's own registry lists at the commit the release pins,
fetched onto the machine by `pat dev builtin` under the toolkit home. Built-in, fetched (a
`module fetch` job directory) and installed (a profile under `mods`) are three different places.
_Avoid_: bundled, preinstalled, default pack, shipped mod

**Baseline**: The deterministic, static check of a module or composition directory that a
registry runs before listing it and a submitter runs first; it reads files, executes nothing,
and is not a security audit, certification, warranty or endorsement (`docs/REGISTRY.md`).
_Avoid_: scan (say baseline), audit, security check, approval

**Port**: A module whose assets or behaviour come from a donor and are adapted to T6.
_Avoid_: conversion, import, remake

**Prior art**: An existing port, extraction or implementation of the wanted feature, in this game
or any other, found before anything is designed.
_Avoid_: reference, inspiration, example

**Lead**: A page or listing claiming that an asset or port exists. It becomes a donor only after
the bytes are acquired, hashed and inspected.
_Avoid_: source, download, find

**Normal** and **PAP**: The two forms of a weapon: the ordinary definition and its Pack-a-Punch
upgrade. Each is its own WeaponDef with its own acceptance.
_Avoid_: base gun, upgraded gun, variant (say which form)

**Assembly**: The complete set of models the engine composes at runtime for one view: character
hands, weapon and every attachment. Bone limits apply to the assembly, not to one model.
_Avoid_: model, rig (a rig is one skeleton)

## Running the game

**Load ID**: The identifier a load, reload or restart returns, bound to the running process
identity and pre-load log offsets.
_Avoid_: load receipt, session id

**Check-load**: One receipt-bound query after a load that reports at most `no_failure_observed`.
A playable spawn is inspected separately.
_Avoid_: load verification, health check

**Delivery uncertain**: A game command whose acknowledgement was lost. Terminal for that command:
inspect fresh state, never replay.
_Avoid_: timeout, retry needed, flaky

**Live lock**: The one lock every `pat game` command that talks to the running client holds, so
live operations never interleave. `game install-mod` is a file copy and takes no lock: run it
when no live command is in flight, and never while a `select-mod` or `reload-mod` of the same
folder is running.
_Avoid_: mutex, session lock

**Test owner**: The single agent or human who currently controls the running game.
_Avoid_: driver, operator, controller

**Agent host**: A running T3 Code server that `pat agent` can hand a prompt to as a new thread,
with the caller's model and reasoning choice. Identified by its origin and orchestration protocol.
_Avoid_: orchestrator, backend, IDE

**Dispatch**: Creating a thread on an agent host and starting its first turn. Accepted commands
carry sequence numbers; what the thread then did is read from its status and the receipts it wrote.
_Avoid_: launch (reserved for the game), send (a follow-up turn), trigger

**Control plane**: The local page `pat plane serve` puts over the routes: every control is one
registered route with typed parameters, run as a `pat` child with its own receipt; it holds no logic
and picks no model.
_Avoid_: dashboard, GUI runtime, launcher

**Run**: One admitted test with explicit owner, plan, display mode, bounded events and receipts.
_Avoid_: session, job, test case

**Display mode**: Who owns the screen during a run: `away` (agent may show the game),
`background` (agent preserves the desktop), `human` (agent prepares, the human plays).
_Avoid_: headless, focus mode

**Typed test route**: A registered, argument-checked action a feature exposes to the test runner
beside its human menu route. There is no arbitrary console or function route.
_Avoid_: hook, API, debug command

**Fixture**: State a run sets up and owns (ammo, placement, points) and restores on cleanup.
_Avoid_: setup, scenario state

## Evidence

Two ladders exist. Do not mix them.

**Route status**: What `pat manifest` reports for a route: `available`, `implemented`,
`planned`, `deferred`, `unsupported`. This is implementation state.
_Avoid_: supported, working, ready

**Route evidence level**: How far a route has been proven, defined in `docs/SUPPORT.md`:
`contract`, `deferred`, `offline`, `native`, `game`, `accepted`. Applies only to the exact
scope in the receipt.
_Avoid_: tested, verified (say which level)

**Packaged route**: A `pat` command with a registered contract, a receipt shape and a row in
`docs/SUPPORT.md`. The qualification matrix grades packaged routes only.
_Avoid_: supported feature, capability, "the toolkit can"

**Track record**: The generated record (`docs/TRACK-RECORD.md`) of what agents have produced
with this environment, including workflows that had no packaged route. Descriptive and scoped
per verdict; never a promise about another base, map or machine.
_Avoid_: portfolio, proof of support, benchmark

**Build evidence**: The separate facts stated about one mod build, in order: offline verified,
installed, launched, loaded, playable, captured, accepted. Each is its own sentence; say the
highest reached and the first not reached.
_Avoid_: works, done, ready, passing

**Offline verified**: The build compiled, linked and passed readback with recorded hashes.
Nothing about the running game.
_Avoid_: tested, validated

**Launched**: The Plutonium client process is running and its window exists. Proved by a
`game launch` or `game status` result naming the window.
_Avoid_: started, open, up

**Loaded**: The running engine reports the expected mod and map for a load ID. Proved by
`check-load` with `verified: true` and `state_matches: true`. Loaded is not playable.
_Avoid_: in the map, running the mod

**Playable**: A fresh, inspected frame shows a spawned character on the intended map with the
menu responding. A loading screen or an accepted launch command is not playable.
_Avoid_: running, in game, working

**Accepted**: A human played the exact build on the named map and form and recorded a scoped
verdict. Acceptance never transfers to another base, map, form or composition.
_Avoid_: owner-accepted, player-accepted, approved, confirmed working

**Candidate**: An exact package, named by hash, prepared for a test that has not yet earned a
verdict.
_Avoid_: build, latest, version

**Checkpoint**: A dated record binding an exact candidate, map, form and scenario to what was
observed. Preserved even when superseded.
_Avoid_: milestone, save point

**Verdict**: The outcome of a run: `automated-passed`, `observed-failed`, `blocked`,
`inconclusive`, `cancelled`. A human's scoped acceptance is recorded separately.
_Avoid_: result, status, pass/fail

**Handoff**: The record that carries exact candidate, dependencies, checks done, pending gates
and observed checkpoint to the next owner. A folder name or a moving `latest` pointer is not one.
_Avoid_: summary, notes, status update

**Gate**: A check that must pass before the next stage, named with what it proves and what it
does not.
_Avoid_: step, requirement, rule

**Preflight**: The gates for one class of change (weapon rig, HUD text, scripts, audio memory)
run before the first install. Each gate came from a real failure.
_Avoid_: checklist, lint, sanity check

**Red loop**: The smallest command that reproduces one exact failure and can go green when it
is fixed. Diagnosis starts by building one.
_Avoid_: repro, test case, feedback loop
