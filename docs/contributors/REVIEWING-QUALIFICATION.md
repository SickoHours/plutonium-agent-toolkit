# Reviewing a Windows qualification pull request

The qualification pull request from the Windows machine is the most important review this
repository will see before the beta. It carries the first native receipts. This is the
maintainer's checklist for it.

## Before reading code

1. Confirm the branch is `qualify/windows-<date>` and CI is green.
2. Open each receipt under `docs/receipts/<version>/`. For every file check:
   - `environment.native_windows` is `true` and `environment.compatibility_layer` is `null`.
     A Wine or WSL run is not a Windows run.
   - `environment.git_head` matches a commit on the branch and `git_dirty` is `false`.
   - The username, machine name, user-profile path, toolkit home, work directory and all
     32-hex request/load/job IDs are redacted. Search the file for `Users\\` and for the
     pilot's GitHub login.
   - `summary.failed` is empty, or every failed step is explained in the pull request body.
3. For `tier3-game.json`, `human_observations` must have no `null`. `town_spawn_playable` and
   `hello_zm_line_visible_after_spawn` must be `true` for any `game`-level claim. If the
   launcher prompted or focus moved, that is recorded, not hidden.

## Reading the code changes

Every fix the agent made on Windows is a real defect in the fakes or the adapter. For each:

- Is there a regression test, and does the fake backend under `tests/fakes/` now reproduce the
  real behaviour that broke? If the fix is only in the adapter, the fakes are still lying.
- Did the fix widen a pattern or loosen a check to make the run pass? `LOAD_FAILURE`,
  `ERROR`, `TITLE`, `PROMPT` and the receipt validators are the usual places. A loosened check
  needs its own justification in the pull request, not a green run.
- Did it touch `docs/SUPPORT.md`? It should, and only for routes with a receipt.

## Flipping routes

For each route the receipts cover with a passing step:

1. `status="implemented"` becomes `status="available"` in the owning `routes.py`.
2. Its `docs/SUPPORT.md` row moves to level `native` (Tier 2) or `game` (Tier 3) and links the
   receipt file.
3. A line under `## [Unreleased]` in `CHANGELOG.md` names the route and the receipt.

Routes with a failing or absent step stay `implemented`, and their `docs/SUPPORT.md` row says
what failed. Do not flip a route because a neighbouring one passed.

## After merging

Run `python tools/bump_version.py 0.1.0b1`, commit, run `python tools/release_check.py`, tag
with the SemVer form it prints, and push the tag. The release workflow does the rest. The
announcement links the GitHub Release and `docs/SUPPORT.md`; it does not claim anything the
support matrix does not.
