# For agents: operating and adapting this toolkit

You are an agent, and this toolkit was built for you to operate and change. This page is the deep
version of `AGENTS.md`: how to fit the toolkit to whatever machine and harness the person is on,
how to debug it there, how to extend it, and the modding behaviours worth knowing before you build
a T6 mod. The human you are helping will not read this. You will.

## The core idea

A person who mods Plutonium with an agent should be able to point that agent at this repository and
get a working setup on their own machine, whatever their machine looks like. The toolkit does not
assume a fixed install, a particular Python location, a specific Plutonium path, or that its
backend tools live in one place. It assumes **you** will read the state of their machine and adapt.

So when you set it up for someone, your job is not "run the documented commands and stop if one
does not fit". It is "make this work here". That is expected, and the toolkit is shaped for it.

That includes driving tools that have no packaged route. `docs/TRACK-RECORD.md` lists the modules
this way of working has produced and the workflows that went beyond the routes; treat it as the
demonstration, and `docs/SUPPORT.md` as the strict grade of the routes themselves.

## Adapt to the machine, in this order

1. **Configuration.** `pat configure --plutonium-storage-t6 <path> [--plutonium-launcher <path>]
   [--backends-dir <path>] [--evidence-dir <path>]`. Find the real paths on their machine; do not
   assume the defaults. Everything is stored under `PAT_HOME` (by default
   `%LOCALAPPDATA%\PlutoniumAgentToolkit` on Windows and `~/.local/state/plutonium-agent-toolkit`
   on Linux), which you can relocate by setting `PAT_HOME`
   if their profile is unusual or they want the toolkit somewhere specific.
2. **Backend overrides.** If a tool they already have should be used, or a pinned download will not
   run on their system, set `PAT_BACKEND_<NAME>` to an absolute path (a `.py` override runs through
   the interpreter, for tests). Backends are otherwise downloaded and hash-verified by
   `pat dev setup`.
   Then `pat dev install-skills` puts the skills under `skills/` where the harnesses on the machine
   read them (`~/.claude/skills`, `~/.codex/skills`, `~/.gemini/skills`, `~/.config/opencode/skills`,
   `~/.cursor/skills`, `~/.hermes/skills`, `~/.agents/skills`; detected by the home directory, never
   by running the harness), stamped with the checkout path, refusing any file it did not write.
3. **Edit the adapter.** If a real tool behaves differently on their build than the adapter
   expects, the adapter is wrong for them, so change it. The adapters in `src/plutonium_agent_toolkit/`
   are small and single-purpose. Read `docs/contributors/ARCHITECTURE.md`, make the change, add a
   test to `tests/` (a fake backend under `tests/fakes/` if needed), run the suite, and tell the
   user what you changed. If the change would help everyone, offer to open a pull request.
4. **Add a route.** If they need a capability that is not here, add it. The guides
   `docs/contributors/ADDING-A-ROUTE.md` and `docs/contributors/ADDING-A-BACKEND.md` are step by
   step. Register it with an honest `status`, and do not build an arbitrary-console escape hatch to
   shortcut it.

Prefer the earliest step that solves the problem. Reach for editing the code as readily as editing
config; both are normal here. What you should not do is silently work around a failure (focusing
the game, deleting an output to retry, guessing a console string). Fix the cause or report it.

## Debug on their machine

Every command gives you what you need to diagnose it without asking the user. The stdout JSON is
one document either way, with `schema_version`, `toolkit_version`, `command`, `request_id` and `at`:

- **On success**, `ok` is `true` and the payload is under `result`. There is no `error_code` on a
  success; do not treat its absence as a problem.
- **On failure**, `ok` is `false` with a stable `error_code` and a `message`, and usually a `hint`
  and sometimes `details`. The `hint` typically names the fix (`config_missing` names the
  `configure` to run; `backend_unavailable` names the `dev setup`; `not_implemented` names the
  route's status). A failing job also sets `receipt` to its receipt path.
- Every job writes `receipt.json` into its output directory, listing argv, input and output
  hashes, and the `log` file for each backend step. Read the step log for the real backend error.
- `pat doctor --json` reports the platform, whether it is native Windows (not Wine), the
  configuration, and which backends are present. On macOS, which is untested and not claimed, it
  carries a `note` saying so; that is a fact to relay, not a gate to work around.
- Which program each route runs, with its command line, license and pinned platforms, is in
  `docs/BACKENDS.md`. It is generated from `dev/backends.json` and `dev/backend_usage.py`; when
  you change an adapter's argv, update the usage table and run `python tools/backends_doc.py
  --write`, or the test fails.
- Troubleshooting tables: `docs/GAME-CONTROL.md`, `docs/WINDOWS-QUALIFICATION.md`,
  `docs/GETTING-STARTED.md`. They map a symptom to a cause and the file to change.

## What "verified" means, and honesty about it

Two vocabularies, do not mix them:

- **Route status**, from `pat manifest`: `available`, `implemented`, `planned`, `deferred`,
  `unsupported`. This is the implementation state. `available` means a native receipt is linked in
  `docs/SUPPORT.md`; `implemented` means the code runs but has no receipt yet; `planned` means a
  registered contract not built for this release; `deferred` means out of scope and it answers
  `not_implemented`.
- **Evidence level**, defined canonically in `docs/SUPPORT.md`: `contract`, `offline`, `native`,
  `game`, `accepted`. This is how far a route has actually been proven. Read the definitions there;
  do not restate them from memory, so this page cannot drift from the matrix.

When `docs/SUPPORT.md` has a receipt for a development route from the other OS and none from
the user's, the honest statement is "receipt from Linux, none from Windows yet" (or the reverse),
and the expectation is that it works here: one code path, the same upstream programs, and Linux
is the harder host because those programs are built for Windows first. So run it. If it works,
carry on; `docs/playbooks/qualify-on-this-host.md` runs the tiers, keeps the redaction gate and
ends in a pull request when the matrix should say so. If the real program differs from the fake
on this host, that is step 3 above: fix the adapter, add the test, tell the user. The matrix is
meant to be extended by whoever is on the machine, which is you.
On macOS the matrix's answer stands (untested, unclaimed, no qualification host); game and
capture routes off Windows are unsupported by transport, not unmeasured.

Respect both in what you tell the user, and keep offline verified, installed, launched, playable,
captured and player-accepted as separate statements. A mod that compiles and links is not a mod
that plays. Say which one you have.

## Knowledge and playbooks

`docs/knowledge/` holds the T6 and Plutonium facts an agent otherwise rediscovers by trial: the
client's storage layout and console, fastfiles and zones, the two script VMs and their traps,
the engine contracts a Zombies feature must meet (bone cap, font scale, field budgets, sound
reservation, normal plus PAP), foundations, crash classes, engine limits and other titles. The
project's vocabulary, including both evidence ladders, is defined once in the root
`CONTEXT.md`. Read `docs/knowledge/README.md` once per session.

`docs/playbooks/` turns those facts into finite recipes with the same five sections each:
preconditions, numbered steps with the receipt field that proves each, the commands that are
wasted, stop conditions, and the separate facts to report. The four preflight playbooks (scripts,
weapon rig, HUD text, audio memory) exist because every failure of that class reached a player
after a clean conversion and a passing suite; run them before the first package, not after the
first crash.

`CONTEXT.md` at the repository root defines the words those pages, the receipts and the skills
use, one definition each with the synonyms to avoid. `skills/` holds one skill per flow:
`pat-help` routes, and `pat-grill`, `pat-build`, `pat-port`, `pat-diagnose` and `pat-review` do
the work. Three of them adapt Matt Pocock's skills (MIT); the unmodified originals are under
`vendor/matt-pocock/`.

## Modding behaviours worth carrying

These are how mods built with this toolkit stay maintainable. They are conventions, not enforced
by code, and you should apply them when helping someone build.

### Build modular mods on a clean base, one module at a time

Do not build a new feature on top of an existing large composition. Start from a clean base mod and
add one module. Build and test that module by itself, so a verdict on it is a verdict on that
module and not on everything it happened to sit next to. Name a test build after its base and
feature, for example `<base>_<feature>_test`, so its scope is legible from its name. When several
modules are known good, compose them deliberately, keeping each module's own receipt.

`pat project init` scaffolds one such module (`examples/hello-zm` is the smallest). Keep each mod's
source, its recipe and its receipts together; a moving "latest" folder or a shared last-result file
cannot tell you which bytes are which later.

### Look for prior art before building from nothing

When the user names a feature and hands over no files, the first job is a search, not a design.
Popular things have been done: for this game by the T6 community, for other games by their
modders, and by extractors written for the origin title. A port found for another engine ships
the extracted models, textures and sounds in a readable container, which is most of a donor. The
authoring workspace's first accepted melee port from a non-CoD title came from two community
Left 4 Dead 2 ports found on the Steam Workshop and fetched from the public CDN; nothing was
modelled from scratch. `docs/playbooks/find-prior-art.md` is the search, in tiers, with the
acquisition rules (public bytes only, hash everything, inspect before trusting, decline hateful
or unlicensed content), and `docs/knowledge/prior-art.md` says where ports usually live. Run it in
every harness that can fetch a page; where yours cannot, hand the user the brief instead of
inventing a result.

### Organize a mod so an agent can reason about it

- One recipe (`project.json`) per mod, naming its scripts, assets and dependency loads explicitly.
- One declaration (`module.json`) beside it, naming the bases and maps the mod was built for, its
  dependencies, conflicts and resource contract, so an agent can compose it with others
  (`docs/MODULES.md`, `pat module plan|build|declare`, playbooks `compose-a-pack.md` and
  `attach-to-a-pack.md`). A pack someone else built is a base member of the next pack; a pack that
  is only a fastfile is declared as a seed first. Collisions the planner lists are yours to decide
  and record, not to skip.
- Keep build outputs in fresh directories, never overwriting; the receipt ties source to package.
- When the person wants a page instead of a terminal, `pat plane serve` gives them one whose every
  control is one of these routes with its own receipt (`docs/CONTROL-PLANE.md`); the judgement calls
  on that page (collisions, ports, diagnosis, loading on Linux) are dispatched to an agent thread.
- Record a mod's normal and Pack-a-Punch identity, its maps, and what was actually tested, apart
  from what merely compiled. Untested maps, co-op and performance stay listed as untested.

### Lessons that became the safety rules

The rules in `AGENTS.md` exist because these bit real ports. They are collected, with the fix each
one produced, in `docs/history/README.md`. In short:

- A rig can compile and link cleanly and still be wrong in game. Inspect the converted artifact,
  not just the exit code.
- The bytes on disk are not the bytes in the engine. A load ID bound to the running process, then
  a `check-load`, is how you know what actually loaded.
- A lost acknowledgement is not permission to retry. `delivery_uncertain` is terminal for that
  command; inspect fresh state instead.
- Recording and long operations must outlive a chat turn, so the runner is finite and independent
  of any UI. (Capture is deferred in this release; the principle still governs the design.)
- A compile, a clean startup and a passing unit test are cheaper signals than a gameplay pass. Do
  not present the cheap one as the expensive one.

## When you extend the toolkit for one person

If your change is specific to their machine, keep it on a branch and tell them it is local. If it
would help anyone with a similar setup, it belongs upstream: run the three checks, open a pull
request with the template, and let the automated reviewer and a maintainer look at it. Either way,
the toolkit stays malleable because you left a clean, testable change rather than a hidden edit.
