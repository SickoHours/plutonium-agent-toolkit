---
name: pat-grill
description: Settle the material decisions for a T6 Zombies mod, port or test in one numbered round with a recommended answer each. Use before pat-port or pat-build when base, maps, weapon forms, donor, menu route or acceptance scope are not yet stated, or when the user says "grill me" about a modding plan.
metadata:
  source:
    repository: https://github.com/mattpocock/skills
    commit: 3cca18b368ae95cdbdebbff572ccafa662551015
    path: skills/productivity/grilling
    license: MIT
    vendored: vendor/matt-pocock/skills/productivity/grilling
    adaptation: Rewritten for Plutonium T6 Zombies modding with pat receipts, preflight gates and the six build facts
---

# pat grill

Adapted from Matt Pocock's `grilling` (`vendor/matt-pocock/`, MIT) for a user who wants to
decide, not to be interviewed. Facts are fetched, decisions are asked, and each decision comes
with a recommendation so the user can answer "yes to all" in one line. Words: `CONTEXT.md`.

## Facts are yours

Before asking anything, fetch what can be fetched: `pat doctor --json` for backends and
platform, `pat game mods --json` for installed profiles, the donor catalog receipt if one
exists, `docs/knowledge/foundations.md` for the base rule. A question whose answer is on disk is
not a question.

## The round

Ask the whole frontier at once, numbered, each with a recommended answer. The frontier for a
port is usually:

1. **Base**: which foundation and tag. Recommend the one the map needs; stock maps need no
   release files.
2. **Maps**: which maps the first test targets. Recommend one map; acceptance is per map.
3. **Forms**: normal and PAP both, or normal first. Recommend both, since a weapon is complete
   only with both.
4. **Donor**: which sealed donor and which assets are retained, adapted or unsupported.
   Recommend from the catalog.
5. **Menu route**: which developer-menu page and label, and the typed test route beside it.
6. **Acceptance scope**: what the user will judge on the first test, so the verdict is scoped.

Format each as: question title, the question, the recommendation. Then wait. Decisions that
depend on an open answer wait for the next round.

## Stop when

Every frontier question has an answer or an explicit "your call", and the answers are written
into the handoff or plan the next skill reads. One round is usual; two is the ceiling before
building starts with stated assumptions.

## Never

Ask for a password, token or login. Ask the user for a fact the toolkit or a page can supply.
