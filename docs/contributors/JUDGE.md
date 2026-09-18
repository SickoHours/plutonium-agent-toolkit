# The judge bank: typed judgments as files

Recorded 2026-09-17. Design rules for `pat judge`, the route that asks a System One model
(TypeSafe's Jev) narrow typed questions about modding evidence. Read with the crash catalog's
rules in `docs/knowledge/README.md`; a question set grows the same way a signature does: from a
real case, with a receipt, never from a whiteboard.

## 1. What a judgment is, and is not

A judgment is a typed answer with a probability, produced by a classifier over a bounded piece
of evidence. It is **inferred state**. It never becomes a build, install, test, or acceptance
fact. It is stored as its own ledger row type, `judged`, and any consumer must show it as a
judgment. The regex catalog, the planner's checks, the screenshot gate and the person's verdict
stay the observed layer; a judgment sits between observation and action and may only:

- pick which observed thing applies (a catalog row, a module kind, a pattern),
- say how sure it is,
- point at the evidence line that justifies it.

It never writes to the bank, promotes a signature, sends a game command, or bypasses an
allowlist or the live lock. Code decides what to do with the answer; the thresholds are code.

## 2. Files

Public, in this repository, under `src/plutonium_agent_toolkit/knowledge/judge/`:

- `<set-id>.json`: a **question set**. Shape in section 3. Contains no evidence.

Private, in the person's workspace under `.local/judge/<set-id>/`:

- `cases.json`: **labeled cases**, section 4. Evidence plus the answer a person or a receipt
  already gave. Never committed to a public repository.
- `runs/<timestamp>/`: one directory per eval run: `request-<case>.json` (exact bytes sent),
  `response-<case>.json`, `scores.json`, `receipt.json`.

The API key is read from `TYPESAFE_API_KEY` in the environment, sourced by the person's shell
from a 600-permission file. It is never written to a receipt, a log, or a config file.

## 3. Question set shape

```json
{
  "schema": 1,
  "id": "crash-triage",
  "title": "Which catalog row explains a T6 crash",
  "model": "jev-latest",
  "state": {
    "fields": {
      "crash_text": "The crash .txt beside the dump: exception, com error, gsc error, gsc pos",
      "console_before_crash": "Up to 40 console lines before the crash, timestamps kept, dvar dumps dropped"
    },
    "max_bytes": 16384,
    "redact": true
  },
  "questions": {
    "<question-id>": {
      "type": "choice | noul | score",
      "instructions": "…",
      "criteria": { "…": "…" }            /* or "criteria_from", section 3.1 */
    }
  },
  "policy": {
    "act": 0.85,
    "ask": 0.50,
    "note": "Above act: code may branch on the answer. Between: show it, do not branch. Below: treat as no answer."
  }
}
```

Rules for questions, from the model's own guidance and from what the first runs showed:

- One coherent judgment per question. Split dimensions that are independently useful.
- Every option text must describe a concrete situation that stands alone. "Other" is not an
  option; a real no-match outcome with a description is.
- Noul `criteria` is an object with `true` and `false` texts, each concrete. A Noul that
  returns near 0.5 across all cases has a vague criterion; fix the wording, not the threshold.
- Question ids are for code and are not sent to the model. Put the whole meaning in
  `instructions`.
- Never show the model a missing value. If a field is absent, the harness writes
  `"(not available)"` and the case records that the field was absent.

### 3.1 Criteria built at run time

A set may declare `criteria_from` instead of `criteria` when the options come from a catalog or
from the state itself. The harness materializes them per request and records the result in the
request file.

```json
"criteria_from": { "knowledge": "crash-signatures.json", "key": "id",
                   "describe": "{cause} (log pattern: {regex})",
                   "plus": { "none": "No catalog row describes this failure" } }
```

```json
"criteria_from": { "state_lines": "crash_text",
                   "plus": { "none": "No single line justifies the answer" } }
```

`state_lines` numbers the lines of a state field and offers each as an option, which is how a
judgment points at its evidence (select, do not generate).

```json
"criteria_from": { "state_regex": "[a-z0-9_/]+::[a-z0-9_]+|maps/mp/[a-z0-9_/]+",
                   "fields": ["crash_text", "console_before_crash"],
                   "plus": { "none_named": "No script is named or none is clearly the owner" } }
```

## 4. Cases

```json
{
  "schema": 1,
  "set": "crash-triage",
  "cases": [
    {
      "id": "crash-2026-09-17-01-52-50",
      "state": { "crash_text": "…", "console_before_crash": "…" },
      "absent": [],
      "expected": { "signature": "cannot-cast-undefined-to-bool", "culprit_kind": "script_logic" },
      "labeled_by": "regex+Halo",
      "source": { "path": "…", "sha256": "…" },
      "at": "2026-09-17T22:10:00Z"
    }
  ]
}
```

`expected` may omit any question: an unlabeled question is scored as unknown, not wrong. A
label's `labeled_by` says where it came from: a receipt field, the regex catalog, or a person.

## 5. Scoring, and what a miss means

`pat judge eval <set> --cases <file> --output <dir>` writes `scores.json`:

- per question: cases, labeled, agree, disagree, unknown; mean confidence on agree and on
  disagree; count of confident-and-wrong (confidence above `policy.act` and disagree).
- per case: expected, answer, confidence, and the top three probabilities.

A miss is exactly one of four things, and the fix differs for each. Decide which before
changing anything:

| Miss | Sign | Fix |
| --- | --- | --- |
| Bad wording | confident and wrong, and a person reading the option text can see why | reword the option or instruction |
| Missing option | probability spread across two options that are both half right | add the option |
| Missing evidence | low confidence with the correct label, and the state lacks the fact | add the field to `state.fields` |
| Wrong label | the model is right and the case is wrong | fix the case, record who relabeled |

Confident-and-wrong is the number that matters. Agreement alone is not a pass.

## 6. When a set may act

A set goes behind a flag (`--judge typesafe`, default off) only when, on its own cases:

1. confident-and-wrong is zero on the current cases,
2. agreement on labeled cases beats the path it replaces (regex alone, or an agent's prose),
3. a person has read every disagree row once.

Behind the flag, the route writes `judged` rows and changes nothing else until a later, separate
decision lets code branch on the answer. Thresholds come from `runs/`, never from a cookbook.

## 7. The `judged` ledger row

```json
{ "type": "judged", "set": "crash-triage", "set_sha256": "…", "model": "jev-1.13.0",
  "state_sha256": "…", "answers": { "signature": { "choice": "…", "confidence": 0.99 } },
  "evidence_line": 5, "at": "…", "receipt": { "path": "…", "sha256": "…" } }
```

The row carries enough to recompute and to dispute. It carries no evidence text.

## 8. What leaves the machine

Every request ships the state to `api.typesafe.ai`. The harness redacts with the same private
pattern the load check uses, bounds the state to `max_bytes`, and writes the exact request
bytes to the run directory so the person can see what was sent. `--dry-run` writes the request
files and sends nothing. The route is opt-in per invocation and never runs inside a build,
install or game job.
