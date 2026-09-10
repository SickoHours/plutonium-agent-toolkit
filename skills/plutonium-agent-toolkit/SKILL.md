---
name: plutonium-agent-toolkit
description: Use the `pat` command to build, control and test Plutonium T6 Zombies mods on Windows for a user who describes outcomes and expects the agent to operate the tools.
---

# Plutonium Agent Toolkit

Read the repository's `AGENTS.md` and `docs/SUPPORT.md` before acting. The support matrix tells
you which routes are contracts, which are offline-tested and which have native Windows evidence.

## Discover

- Unknown route: `pat manifest --json` once per session. Reuse it while the version is unchanged.
- Known route: `pat describe <group> <action> --json`. Use the returned `argv`.
- Installation state: `pat doctor --json`. Backend inventory: `pat dev backends --json`.
- Discovery never executes anything and needs no authorization.

## Operate

- One JSON document per invocation. Keep stdout and the exit status together as the receipt.
- Every job needs a new `--output` directory. Never delete outputs to retry.
- `error_code` tells you what to do: `config_missing` run the hinted `configure`; `backend_unavailable`
  run `dev setup`; `not_implemented` stop and report the route's status; `delivery_uncertain`
  inspect fresh state and never replay.
- Setup, discovery and `project`/`gsc`/`ff` jobs need no game. Anything in `game`, `capture` or
  `test start/cancel` needs the user's authorization for that specific test.

## Report

Separate offline verified, installed, launched, playable, captured and player-accepted. If you
cannot look at the screenshot, say the visual checkpoint is unverified. Name what was not tested.
