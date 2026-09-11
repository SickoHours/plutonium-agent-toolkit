---
name: pat-help
description: Which pat skill or playbook fits the situation. A router over the skills in this repository.
disable-model-invocation: true
---

# pat help

You do not remember every skill, so ask. Every flow below runs on `pat` commands with one JSON
receipt per invocation, and every flow ends by stating the six build facts separately: offline
verified, installed, launched, playable, captured, accepted. Words are defined in `CONTEXT.md`.

## The main flow: idea to tested module

1. **`pat-grill`** settles the material decisions in one round: base, maps, forms, donor, menu
   route, acceptance scope. Facts are fetched, decisions are asked, each with a recommendation.
2. **`pat-port`** when assets or behaviour come from a donor; **`pat-build`** when it is a
   script or recipe change on an existing module. Both end at a build receipt and the preflight
   playbooks for the classes the change touches.
3. **`pat-review`** before install: standards, spec, and the evidence level actually earned, as
   three separate reports.
4. `docs/playbooks/compose-a-pack.md` when several accepted modules should become one pack on a
   named base and map (`pat module plan|build`; formats in `docs/MODULES.md`);
   `docs/playbooks/attach-to-a-pack.md` when one module joins an existing pack (the pack is the
   base member; a prebuilt pack becomes a seed with `pat module declare`).
5. `docs/playbooks/package-and-install.md` puts the profile on disk without touching the game.
   Live operations after that need the user's go and a qualified host.

## On-ramps

- **The user names a published module or pack** ("add the round announcer from the registry", a
  GitHub link): `pat registry search <words>` or `show <owner/id>`, then `pat module fetch
  <owner/id@commit> --output <new dir>` and name `module_dir` as a reference member of the
  composition. A hit with `origin: builtin` is one the toolkit ships: `pat dev builtin` puts it on
  the machine and the hit's `builtin_dir` is the member path. `docs/REGISTRY.md`; publishing your
  own: `docs/playbooks/publish-a-module.md`.
- **The user names a feature and no donor is on disk**: `docs/playbooks/find-prior-art.md`
  before `pat-grill`. Someone has usually ported or extracted it for some game; a lead found,
  fetched, hashed and inspected is a donor, and a search not run is a port built from nothing.
- **Hand a task to a T3 Code thread** (a GUI button, a scheduled job, another agent's plan):
  `pat agent models` for the instances, models and reasoning choices this machine offers, then
  `pat agent dispatch` with the playbook and target in the prompt and the user's chosen model;
  follow with `pat agent status`. `docs/AGENT-HOSTS.md`. Never pick the model yourself.
- **The user wants buttons, not a terminal** (a library view, a pack builder, an install and load
  panel, a dispatch form): `pat plane serve --library <dir> --jobs <dir>` and open the printed URL.
  Every control is one of the routes above with its own receipt; `docs/CONTROL-PLANE.md`.
- **Something broke in the game** (menu return, close, dialog): **`pat-diagnose`**. It builds a
  red loop before theorising and ends by adding the gate that would have caught it.
- **First time on this machine**: `docs/playbooks/first-build.md`, then the setup prompt in the
  repository root if backends are missing; `pat dev install-skills` puts these skills where the
  harnesses on the machine read them.
- **`docs/SUPPORT.md` has a receipt for a development route from the other OS only**: run it;
  it is expected to work here, and a Linux receipt is strong evidence for Windows. Fix the
  adapter on the spot if the real program differs; `docs/playbooks/qualify-on-this-host.md`
  records the receipt and opens the pull request when the matrix should say so. (macOS: untested
  and unclaimed; game routes off Windows: unsupported by transport.)

## Reference underneath

- `CONTEXT.md` is the glossary. When a word is the problem, read it.
- `docs/knowledge/` holds the facts (client layout, fastfiles, scripts, contracts, crashes,
  limits). Read the page for the task once.
- `docs/playbooks/` holds the steps. Each step names the receipt field that proves it.
- `docs/SUPPORT.md` is canonical for what each route has earned.

## Phase boundaries

Grill, port or build, and review are three phases. Keep grill and the plan in one context.
Start the build fresh from the written plan. Diagnosis is its own session: hand off the failed
candidate hash, the log slice and the frame, not the conversation.
