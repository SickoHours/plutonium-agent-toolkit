---
name: pat-diagnose
description: Diagnose a T6 Zombies mod that returned to the menu, closed the game, or showed an error dialog. Use when the user says "crashed", "it broke", "back to menu", or reports a load failure. Builds a red loop before any theory; ends by adding the gate that would have caught it.
metadata:
  source:
    repository: https://github.com/mattpocock/skills
    commit: 3cca18b368ae95cdbdebbff572ccafa662551015
    path: skills/engineering/diagnosing-bugs
    license: MIT
    vendored: vendor/matt-pocock/skills/engineering/diagnosing-bugs
    adaptation: Rewritten for Plutonium T6 Zombies modding with pat receipts, preflight gates and the six build facts
---

# pat diagnose

Adapted from Matt Pocock's `diagnosing-bugs` (`vendor/matt-pocock/`, MIT) for a target that no
unit test can drive. The discipline is the same: a loop that goes red on this failure comes
before any hypothesis. Words: `CONTEXT.md`. Facts: `docs/knowledge/crashes.md` and
`docs/knowledge/engine-limits.md`; `pat knowledge signature --log <slice> --json` classifies the
saved slice. Steps: `docs/playbooks/diagnose-a-crash.md`.

## The order

1. Preserve the failure before anything else: copy the log slice, the frame or dialog text, the
   process identity and the installed package hash beside the task, privately. Every later step
   can overwrite the log; this one cannot be redone.
2. Classify from the saved log slice or dialog text: script link, asset registration, engine
   limit, allocation, process crash, host kill. Check the signature table first; most classes
   have been seen and have a known fix shape.
3. Build the red loop at the lowest rung that reproduces this exact failure: compile with the
   right instance, build with readback, fastfile inspect, a preflight gate, then only with the
   user's go on a qualified host, one load and one `check-load`. Run it once and show it.
4. Minimise until every remaining element is load-bearing.
5. Three to five ranked hypotheses, each with a falsifiable prediction, written before any probe.
6. One probe per hypothesis, in rank order, changing one variable.
7. Fix, re-run to green, then add a regression that consumes the original failed artifact (the
   one preserved in step 1) to the preflight for that class; keep the failed package and its
   evidence beside the fix.

## Hard guardrails

- Never replay a `delivery_uncertain` game command; read fresh state.
- Never focus, minimise, kill or send keystrokes to the game as a workaround; report instead.
- A core that cannot be symbolised has unresolved frames; say so, never fill them in.

## Stop when

No rung below a game load reproduces it and there is no live authority or qualified host. Report
the classes ruled out, the loop attempted, and what a live test would need. Two classes remain
equally supported after minimising: report both with the distinguishing observation.

## Report

Class and signature. The red loop command. Proved facts and inferred facts in separate sentences.
The gate that now catches it. The corrected candidate is offline verified only until each later
fact is earned.
