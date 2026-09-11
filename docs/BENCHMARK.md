# Offline benchmark: comparing models and harnesses on receipts

Six repeatable modding tasks, scored only from the receipts an agent's `pat` invocations wrote
and the files those receipts inventory. No prose is graded and no game is involved. The result
says how reliably and how economically an agent drives the toolkit to an offline-verified
outcome; it says nothing about gameplay, and it gates no release.

## The tasks

| ID | Prompt asks for | Scored on |
| --- | --- | --- |
| `bench-01-compile-error` | Compile a script with a syntax error | one `gsc compile` of the fixture `broken.gsc`, final status `failed` with `backend_failed`, at most 3 invocations |
| `bench-02-build-hello` | Plan, build and verify `examples/hello-zm` | `project plan`, `project build`, `project verify` in that order, the build declares `examples/hello-zm`'s recipe and script as inputs, `packages/mod.ff` in its outputs, at most 6 |
| `bench-03-extract-rawfile` | Extract the rawfiles from a built `mod.ff` | one `ff extract` whose input `mod.ff` hash equals the bench-02 build's output hash and whose outputs match `assets/**/*.gsc`, at most 4 |
| `bench-04-port-feature` | Port `announce_round` from `examples/hello-zm-two` into a copy of `hello-zm`, build, verify | `project build` then `project verify`, a recipe and `scripts/hello.gsc` declared as inputs, `mod.ff` produced, the build's readback contains both `announce_round` and `on_player_spawned`, at most 10 |
| `bench-05-builtin-wrong-vm` | Fix a server script whose one call exists only on the client VM, then compile | one `gsc compile` of the corrected `face_glow.gsc`, final status `succeeded`, the compiled artifact no longer carries `setanimknob` and still carries `face_glow_think` and its `^3face glow armed` message, the saved `knowledge-lookup.json` is the toolkit's own `knowledge builtin` document naming `setanimknob`, at most 4 |
| `bench-06-classify-then-fix` | Classify a console slice (`Client Field Set actor is out of space`), fix the script that caused it, compile | one `gsc compile` of the corrected `riser_glow.gsc`, final status `succeeded`, the compiled artifact no longer carries the new field `bench_riser_glow` and still carries `riser_glow_think` and its `^5riser glow armed` message, the console slice is among the scored inputs, the saved `knowledge-lookup.json` is the toolkit's own `knowledge signature` document, at most 4 |

Task definitions are `tools/benchmark/tasks.json`; prompts are `tools/benchmark/prompts/`;
the broken script, the wrong-VM script and the failed load's script and log slice are fixtures.
`bench-05` and `bench-06` are the tasks the shipped knowledge data (`pat knowledge builtin`,
`pat knowledge signature`) exists for: a compiler accepts both fixtures unchanged, so the score
comes from what the corrected artifact carries, not from a compile passing. `examples/hello-zm-two` exists so the port task has a real
source and target.
The knowledge routes are inert and write no receipt, so each of these two prompts asks the agent to
save the route's stdout document as `knowledge-lookup.json` in the task directory; the scorer reads
that file. Artifacts are scored only through the compile receipt's recorded outputs, hash-checked,
so a file added or replaced after the job is not the job's artifact.

## Running one model on one harness

1. Fresh state: a new `PAT_HOME` with the required backends installed (`pat dev setup --only gsc
   oat --json`), a fresh agent session with the repository checked out, and an empty run directory
   `<RUN>` outside the repository with `run.json`:
   ```json
   {"model": "<model id>", "harness": "<harness name and version>", "started": "<ISO time>",
    "finished": "", "tokens_in": null, "tokens_out": null, "notes": ""}
   ```
2. For each task in order, substitute `<REPO>`, `<RUN>`, `<FIXTURE>` (`tools/benchmark/fixtures/
   bench-01`) and `<MOD_FF>` (the `mod.ff` from the agent's bench-02 build) into the prompt file
   and hand the text to the agent verbatim. Do not add instructions, hints or corrections. The
   agent has the repository's own docs, which is the point.
3. The agent's jobs must land under `<RUN>/<task id>/`. Where they land is part of following the
   prompt; a job written elsewhere is not found and scores as missing.
4. Fill in `finished` and the token counts if the harness reports them, then score:
   ```sh
   python tools/benchmark.py score --run <RUN> > <RUN>/score.json
   python tools/benchmark.py table --run <RUN>
   ```

Keep the run directory private (it holds paths from your machine); commit only the table row.

## Reading the numbers

- A task's score is the fraction of its checks that passed; the checks are listed per task in
  `score.json` with what was missing.
- Invocations are top-level receipts under the task directory: every `pat` job the agent ran,
  including retries and rebuilds. Fewer, within a correct result, is better; the budget is a
  ceiling, not a target.
- Wall time is, per task, first job start to last job end, and the total is the sum over tasks;
  it includes the agent's thinking between jobs inside a task and excludes time between tasks.
  It is comparable only between runs on the same machine.
- Inputs are checked: the scored job's receipt must declare the task's own source files
  (`inputs_contain`), and for the extract task the `mod.ff` it read must carry the hash the build
  task's receipt recorded (`input_hash_from`). A job run against an unrelated project scores as
  missing inputs.
- `failed_invocations` lists jobs that did not succeed; a wasted rebuild shows up here and in the
  count.
- `artifact_contains` and `artifact_excludes` read the compiled scripts and the readback the scored
  job produced: a fix scores by what left the artifact, not by what the report says was removed.

What the score does not measure: whether the ported feature works in game, whether the agent's
report to the user was honest, or anything about a model outside these four tasks. Compare runs on
the same toolkit version and the same machine.

## Baseline

| Model | Harness | Date | bench-01 | bench-02 | bench-03 | bench-04 | bench-05 | bench-06 | Total |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| claude-fable-5-1 | Claude Code in T3 Code | 2026-09-10 | 6/6 (1 call) | 6/6 (3 calls) | 6/6 (1 call) | 7/7 (3 calls) | not run | not run | 25/25 (8 calls, 0.8 s) |
| claude-fable-5-1 | Claude Code in T3 Code | 2026-09-11 | not run | not run | not run | not run | 6/6 (1 call) | 6/6 (1 call) | 12/12 (2 calls, 0.1 s) |

The baseline row was produced by the agent that wrote the benchmark, in the same session, on
Arch Linux (Omarchy) with the real backends, following each prompt verbatim. It is a floor for
effort and a check that the tasks are solvable with the repository's own docs, not an
independent measurement; its wall time excludes agent thinking because the commands were issued
back to back. The second row is the same agent running only the two knowledge tasks it added, with
the real gsc-tool 1.4.10 through `PAT_BACKEND_GSC`; both fixtures compile unchanged, and the
unmodified compiles scored 5/6 on each task (only the artifact check failed), which is what the tasks
are for. Rows from other models and harnesses are welcome as pull requests with the
`score.json` summary quoted in the body and the run directory kept private.
