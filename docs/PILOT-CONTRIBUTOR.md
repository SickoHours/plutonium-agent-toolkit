# Pilot: the contributor journey

The second acceptance test before `1.0.0`. **Can a development agent that did not build this
toolkit understand the repository, implement a change, test it, and open a reviewable pull
request, using only what is in the repository?**

## Rules

Same as [PILOT-USER.md](PILOT-USER.md): a person other than the maintainer, an agent on a
different harness, no real-time help, findings recorded as they happen.

## The seeded task

The maintainer opens an issue labelled `pilot-task` describing a small, real change. Good
candidates, in increasing difficulty:

1. Add a `--json` alias check: `pat version` should also accept `pat --version` and print the
   same JSON. (parser only, one test)
2. Add a new map recipe to `game/maps.json` for a location the catalog is missing, with a test
   asserting the catalog still validates and the count changed. (data plus test plus doc)
3. Add `pat audio normalize` that runs FFmpeg's `loudnorm` filter and verifies the output with
   ffprobe. (new route through the whole contract: registry, parser, adapter, fake backend,
   tests, SUPPORT row, changelog)

Pick one. Do not pick something already done.

## Script for the pilot

> Clone https://github.com/SickoHours/plutonium-agent-toolkit. Read CONTRIBUTING.md and
> AGENTS.md, then read the issue I link. Implement it the way the repository's own guides say
> to, with tests, on a branch. Run the checks CONTRIBUTING.md names. Open a pull request using
> the template and fill every section honestly, including "Not verified". Then respond to the
> automated reviewer until the checks are green. Do not ask me how the codebase works; the
> repository is supposed to tell you. If it does not, write down what was missing.

## What the pilot records

| Question | Answer |
| --- | --- |
| Harness and model used | |
| Minutes from clone to first green local test run | |
| Minutes from clone to pull request opened | |
| Which docs the agent read, in order | |
| Places where the agent had to read source because the docs were insufficient | list each |
| Did the agent find `docs/contributors/ADDING-A-ROUTE.md` without being told? | yes / no |
| Did it register the route with an honest `status`? | yes / no |
| Did it add a fake backend and failure-path tests? | yes / no |
| Did it update `docs/SUPPORT.md` and `CHANGELOG.md` unprompted? | yes / no |
| Review rounds until green | |
| Anything it did that AGENTS.md forbids | list each |

## What counts as passing

A mergeable pull request that follows the repository's own rules without the pilot having to
explain any of them. The route (if one was added) is registered `implemented`, not `available`,
because the pilot's machine produced no native receipt. Every gap the agent hit in the docs
becomes an issue labelled `pilot`, and the maintainer closes it by improving the doc, not by
answering the question once.
