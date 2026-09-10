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
   named base and map (`pat module plan|build`; formats in `docs/MODULES.md`).
5. `docs/playbooks/package-and-install.md` puts the profile on disk without touching the game.
   Live operations after that need the user's go and a qualified host.

## On-ramps

- **Something broke in the game** (menu return, close, dialog): **`pat-diagnose`**. It builds a
  red loop before theorising and ends by adding the gate that would have caught it.
- **First time on this machine**: `docs/playbooks/first-build.md`, then the setup prompt in the
  repository root if backends are missing.
- **`docs/SUPPORT.md` has no receipt for a development route on this Windows or Linux host, or
  marks it unverified here**: `docs/playbooks/qualify-on-this-host.md`. Unverified means
  unmeasured; measure it and open the pull request. (macOS: untested and unclaimed; game routes
  off Windows: unsupported by transport.)

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
