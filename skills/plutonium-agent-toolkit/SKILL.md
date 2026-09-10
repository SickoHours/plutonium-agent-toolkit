---
name: plutonium-agent-toolkit
description: Use the `pat` command to build, control and test Plutonium T6 Zombies mods for a user who describes outcomes and expects the agent to operate and adapt the tools. The build tools run on Windows and Linux; game control is Windows-only. Any harness; the toolkit is meant to be configured and edited to fit the user's machine.
---

# Plutonium Agent Toolkit

You are the agent operating this toolkit for someone modding Plutonium Black Ops II Zombies. They
describe the outcome; you install, configure, run, debug and, when the defaults do not fit their
machine, adapt the toolkit itself. It is open source and malleable on purpose.

Read the repository's `AGENTS.md` and `docs/FOR-AGENTS.md` for the full contract, and
`docs/SUPPORT.md` for what each route has actually earned (`available` = native receipt on Windows or
Linux, `implemented` = runs but no receipt, `offline` = unit-tested only, `deferred` = out of scope).
macOS is untested and not claimed; say so if the user is on one.

## Where things are

- `CONTEXT.md`: the words. One definition each, with the synonyms to avoid; use them exactly.
- `docs/TRACK-RECORD.md`: what has been built this way, with the scope of each verdict, and the
  workflows that went beyond the packaged routes. Read it before telling a user something is
  impossible; `docs/SUPPORT.md` grades the routes, not the ceiling.
- `docs/knowledge/README.md`: the facts (client layout, fastfiles, scripts, contracts, foundations,
  crash classes, engine limits). Read the page for the task once per session, then work from it.
- `docs/playbooks/`: the steps. First build, add a script, port a feature, diagnose a crash,
  package and install, and four preflight gate lists (scripts, weapon rig, HUD text, audio
  memory) to run before a build's first install. Each playbook is finite: exact commands, the
  receipt field that proves a step, the commands that are wasted, the stop conditions. Follow its
  "Do not" list.
- `skills/pat-*`: the flows. `pat-help` routes; `pat-grill`, `pat-build`, `pat-port`,
  `pat-diagnose` and `pat-review` do the work.

## Discover

- Unknown route: `pat manifest --json` once per session. Reuse it while the version is unchanged.
  A `status: succeeded` receipt is the fact; do not re-run a job to confirm it, and rebuild only
  after an input hash changed.
- Known route: `pat describe <group> <action> --json`. Use the returned `argv`.
- Installation state: `pat doctor --json`. Backend inventory: `pat dev backends --json`.
- Discovery never executes anything and needs no authorization.

## Operate

- One JSON document per invocation. Keep stdout and the exit status together as the receipt.
- Every job needs a new `--output` directory. Never delete outputs to retry.
- `error_code` tells you what to do: `config_missing` run the hinted `configure`;
  `backend_unavailable` run `dev setup`; `not_implemented` stop and report the route's status;
  `delivery_uncertain` inspect fresh state and never replay.
- Setup, discovery, `dev`, `gsc`, `ff`, `project`, `model`, `audio`, `image`, `lua`, `weapon` and
  `game mods`/`install-mod` need no running game. Anything else under `game` needs the user's
  authorization for that specific test.

## Adapt to the machine

Do not stop at "unsupported". In order: `pat configure` and `PAT_HOME` for paths; `PAT_BACKEND_*`
for a tool that lives elsewhere or a pinned download that will not run; then edit the small adapter
in `src/plutonium_agent_toolkit/` (add a test) if a real tool behaves differently on their build;
then add a route (`docs/contributors/ADDING-A-ROUTE.md`) if they need one that does not exist.
Never add an arbitrary-console escape hatch. Report what you changed.

## Build mods well

Build one module on a clean base and test it alone (`pat project init`, `examples/hello-zm` is the
smallest), name a test build `<base>_<feature>_test`, keep each mod's source, recipe and receipts
together, and compose known-good modules deliberately. `docs/FOR-AGENTS.md` has the behaviours.

## Report

Separate offline verified, installed, launched, playable, captured and player-accepted. If you
cannot look at the screenshot, say the visual checkpoint is unverified. Name what was not tested.
