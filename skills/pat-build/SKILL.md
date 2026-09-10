---
name: pat-build
description: Build a T6 Zombies mod with pat and prove it offline. Use when the user wants to compile a script, link a fastfile, build or verify a project recipe, or asks whether a build "works". Ends at a receipt and the applicable preflights, never at a claim about gameplay.
---

# pat build

Produce one build with a receipt, read it back, run the preflights for what changed, and say
exactly what was proved. Words: `CONTEXT.md`. Facts: `docs/knowledge/fastfiles-and-zones.md`
and `docs/knowledge/gsc.md`.

## Steps

1. Pick the playbook. New machine: `docs/playbooks/first-build.md`. Script change:
   `docs/playbooks/add-a-script.md`. Otherwise plan then build the recipe. Proof: the
   playbook is open and its preconditions are true.
2. Plan. `pat project plan <recipe> --output <new dir> --json`. Proof: `ok: true` and
   `result.backends_available` is `true`; when it is `false`, `result.backends[]` lists each
   backend by `id` (`gsc`, `linker`, `unlinker`) with `available` false for the missing ones.
   A missing backend stops here: install it (`pat dev setup --only gsc` for `gsc`;
   `pat dev setup --only oat` for `linker` and `unlinker`) or point the exact binary at
   `PAT_BACKEND_GSC`, `PAT_BACKEND_LINKER` or `PAT_BACKEND_UNLINKER` (there is no
   `PAT_BACKEND_OAT`), then plan again.
3. Build. `pat project build <recipe> --output <new dir> --json`. Proof: `ok: true`,
   `result.rawfiles_verified` counts every script, and `receipt.json` has `status: succeeded`.
   A `backend_failed` result: read the step log named in the receipt and report the backend's
   own error line. The linker can print `ERROR:` and exit zero; the toolkit treats that as
   failure and so do you.
4. Preflight. Run each playbook under `docs/playbooks/preflight-*.md` whose class the change
   touched: scripts always; weapon rig, HUD text, audio memory when those assets changed. Proof: each gate is recorded as pass, fail or unknown against the `mod.ff` hash.
5. Verify when the build will be reused later. `pat project verify <receipt> --inputs --output
   <new dir> --json`. Proof: `result.outputs.verified` is `true` and, with `--inputs`,
   `result.inputs.verified` is `true`.

## Do not

- Re-run `manifest` in a session; `describe` only the route about to run.
- Rebuild with unchanged input hashes; the receipt is the fact.
- Delete an output directory to retry; investigate in place and use a new `--output`.

## Report

Offline verified with the hash and the preflight results. Installed, launched, playable,
captured, accepted: each a separate no unless a later playbook made it yes. Name the platform and
backend pins from the receipt.
