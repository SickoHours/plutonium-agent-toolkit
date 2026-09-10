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

## Adapt to the machine, in this order

1. **Configuration.** `pat configure --plutonium-storage-t6 <path> [--plutonium-launcher <path>]
   [--backends-dir <path>] [--evidence-dir <path>]`. Find the real paths on their machine; do not
   assume the defaults. Everything is stored under `PAT_HOME`
   (`%LOCALAPPDATA%\PlutoniumAgentToolkit` by default), which you can relocate by setting `PAT_HOME`
   if their profile is unusual or they want the toolkit somewhere specific.
2. **Backend overrides.** If a tool they already have should be used, or a pinned download will not
   run on their system, set `PAT_BACKEND_<NAME>` to an absolute path (a `.py` override runs through
   the interpreter, for tests). Backends are otherwise downloaded and hash-verified by
   `pat dev setup`.
3. **Edit the adapter.** If a real tool behaves differently on their build than the adapter
   expects, the adapter is wrong for them, so change it. The adapters in `src/plutonium_agent_toolkit/`
   are small and single-purpose. Read `docs/contributors/ARCHITECTURE.md`, make the change, add a
   test to `tests/` (a fake backend under `tests/fakes/` if needed), run the suite, and tell the
   user what you changed. If the change would help everyone, offer to open a pull request.
4. **Add a route.** If they need a capability that is not here, add it. `docs/contributors/
   ADDING-A-ROUTE.md` and `ADDING-A-BACKEND.md` are step by step. Register it with an honest
   `status`, and do not build an arbitrary-console escape hatch to shortcut it.

Prefer the earliest step that solves the problem. Reach for editing the code as readily as editing
config; both are normal here. What you should not do is silently work around a failure (focusing
the game, deleting an output to retry, guessing a console string). Fix the cause or report it.

## Debug on their machine

Every command gives you what you need to diagnose it without asking the user:

- The stdout JSON carries `ok`, `error_code`, `message`, `hint` and often `details`. The `hint`
  usually names the fix (`config_missing` names the `configure` to run; `backend_unavailable` names
  the `dev setup`; `not_implemented` names the route's status).
- Every job writes `receipt.json` into its output directory, listing argv, input and output
  hashes, and the `log` file for each backend step. Read the step log for the real backend error.
- `pat doctor --json` reports the platform, whether it is native Windows (not Wine), the
  configuration, and which backends are present.
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

Respect both in what you tell the user, and keep offline verified, installed, launched, playable,
captured and player-accepted as separate statements. A mod that compiles and links is not a mod
that plays. Say which one you have.

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

### Organize a mod so an agent can reason about it

- One recipe (`project.json`) per mod, naming its scripts, assets and dependency loads explicitly.
- Keep build outputs in fresh directories, never overwriting; the receipt ties source to package.
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
