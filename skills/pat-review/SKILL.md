---
name: pat-review
description: Review a T6 Zombies mod change before install on three separate axes: standards (the contracts in docs/knowledge), spec (what was asked for), and evidence (which of the six build facts the change has actually earned). Use when the user asks to review a build, a branch, or a candidate, or before any package-and-install.
metadata:
  source:
    repository: https://github.com/mattpocock/skills
    commit: 3cca18b368ae95cdbdebbff572ccafa662551015
    path: skills/engineering/code-review
    license: MIT
    vendored: vendor/matt-pocock/skills/engineering/code-review
    adaptation: Rewritten for Plutonium T6 Zombies modding with pat receipts, preflight gates and the six build facts
---

# pat review

Adapted from Matt Pocock's two-axis `code-review` (`vendor/matt-pocock/`, MIT) with a third
axis that this domain needs: a change can meet every standard and match its spec and still have
earned only "offline verified". The three reports stay separate; they are never merged or
reranked. Words: `CONTEXT.md`.

## Pin the change

The diff between a fixed point and the candidate, and the candidate's `mod.ff` hash and build
receipt. A missing receipt ends the review: nothing is reviewable without one.

## Axis 1: standards

Against `docs/knowledge/zombies-contracts.md`, `docs/knowledge/gsc.md` and the preflight
playbooks. Report each place the change breaks a documented contract, citing the page and the
rule. Items: ownership record present and complete; cleanup on every life event; budgets counted
across the full load; normal and PAP both delivered or the gap stated; menu route and typed test
route present; WeaponDef invariants (shared ammo cap, inventory type, impact type). Judgement
calls are labelled as such. Under 400 words.

## Axis 2: spec

Against the request or handoff the change was built from. Report: requirements missing or
partial; behaviour not asked for; requirements that look implemented but wrong. Quote the spec
line for each finding. No spec: say "no spec available" and skip the axis. Under 400 words.

## Axis 3: evidence earned

For the six build facts, state which the candidate has earned and cite the artifact: offline
verified (receipt `status: succeeded`, readback count, preflight results by hash); installed
(install receipt hash equals build hash); launched, playable (a fresh inspected frame with a
spawned character); captured; accepted (a dated scoped verdict by a person on this exact hash,
map and form). Anything without an artifact is "not earned". A claim in prose that outruns its
artifact is a finding on this axis. Under 200 words.

## Aggregate

Three headings, verbatim reports, one closing line with the count per axis and the worst item
within each axis. No single winner across axes; that reranking is what the separation prevents.
