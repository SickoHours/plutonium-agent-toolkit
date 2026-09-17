# `pat judge`: typed judgments about evidence

`pat judge` asks a hosted System One model (TypeSafe's Jev) narrow, typed questions about a piece
of modding evidence — a crash text, a slice of console — and scores its answers against cases a
person or a receipt already labeled. The design rules, the file formats and when a question set is
allowed to act are in [contributors/JUDGE.md](contributors/JUDGE.md); this page is what you need
before you run it.

Read this first, because this route is unlike every other one here:

- **It sends your evidence to a third party.** `judge eval` posts each case's state to
  `https://api.typesafe.ai/v1/systemone`. Other routes read the network — the pinned backend
  downloads, `registry add` with a URL, `module fetch`, `dev builtin` — and `agent` writes to a T3
  Code server the person runs. This is the only one that sends your evidence anywhere. What is
  sent is exactly the bytes in
  `request-<case>.json`, written into the output directory *before* the request goes out, so you
  can read it afterwards — or read it first with `--dry-run`, which writes the requests and sends
  nothing.
- **It is opt-in, per invocation.** No build, install, plan, verify, test or game route calls it.
  There is no flag anywhere else that turns it on, and a judgment never runs as a side effect of
  something you asked for.
- **It never acts.** An answer is inferred state: a typed value with a probability. It never
  becomes a build, install, test or acceptance fact, never promotes a crash signature, writes a
  bank row, sends a game command or bypasses the live lock. Code decides what to do with an
  answer, and the thresholds are code.
- **Your key stays yours.** The key is read from `TYPESAFE_API_KEY` in the environment and used in
  one request header. The toolkit never stores, prints or logs it, and `pat configure` has no
  field for it. Without it the route refuses with `judge_key_missing` before it writes or sends
  anything.

## What is sent, and what is not

Per case, the request carries the state fields the set declares and nothing else — no paths, no
file names, no case ids, no receipt, no toolkit version.

Before encoding, the harness:

1. replaces an **absent** field with `(not available)`, so the model never sees a missing value;
2. **redacts** line by line, when the set asks for it: any line naming `token`, `ticket`,
   `authorization`, `password`, `connect` or `auth` is replaced whole with `(redacted)`, because
   that is the kind of line that carries a session ticket or a login;
3. **bounds** the state to the set's `max_bytes`, cutting the longest field from the end and
   marking it `(truncated)`;
4. **materializes** the criteria that are built at run time (a catalog's rows, the numbered lines
   of a field, the scripts a regex finds in the state), so a judgment selects evidence rather than
   generating it.

Diagnostics go to `judge.log` in the output directory. Standard output carries counts, option ids
and probabilities — never the state, never the key.

## The routes

```sh
pat judge list --json                    # the question sets that ship, with id and title
pat judge show crash-triage --json       # one set: its questions, criteria and thresholds
pat judge eval crash-triage \
    --cases <your cases.json> \
    --output <new dir> [--dry-run] [--model jev-latest] [--timeout 30]
```

`list` and `show` are inert: they read the JSON under
`src/plutonium_agent_toolkit/knowledge/judge/` and touch no network. `eval` is a job like any
other: a new `--output` directory it refuses to overwrite, a `receipt.json` on every exit path,
and one JSON document on stdout.

### Cases stay on your machine

`--cases` is your own labeled file (format in section 4 of the contributors' page). It holds real
evidence, so it belongs in your workspace under `.local/judge/<set>/`, never in a public
repository. The toolkit hashes it into the receipt and reads nothing else from it.

### What a run leaves behind

| File | What it is |
| --- | --- |
| `request-<case>.json` | the exact bytes sent for that case, written before the send |
| `response-<case>.json` | the exact bytes the API answered |
| `scores.json` | per question: cases, labeled, agree, disagree, unknown, not asked, mean confidence on agree and on disagree, and the count of confident-and-wrong. Per case: expected, answer, confidence and the top three probabilities |
| `judge.log` | what the run did, in order |
| `receipt.json` | argv, the hashes of the set and the cases file, every output hash, status |

`confident_and_wrong` — an answer above the set's `act` threshold that disagrees with the label —
is the number that matters. Agreement alone is not a pass, and section 5 of the contributors' page
says which of the four kinds of miss each one is before anything is changed.

A question can also be **not asked** for a case: when a set builds a choice's options from the
state and the state names nothing, all that is left is the no-match option, which is neither a
question nor a valid request. That case is recorded as `not-asked` and counted as neither agree
nor disagree.

## Failure modes

| `error_code` | Meaning |
| --- | --- |
| `judge_key_missing` | `TYPESAFE_API_KEY` is not in this shell, or the API refused it (HTTP 401). Nothing was sent. `--dry-run` needs no key |
| `output_exists` | the `--output` directory already exists. Use a new one; never delete one to retry |
| `input_invalid` | the set, the cases file or the API's answer broke its own shape. The message names which |
| `input_missing` | no set by that id, or the cases file is not there |
| `backend_failed` | the API answered an error, including 429 (rate limit) and 529 (overloaded), which are retried twice before the job gives up |
| `backend_timeout` | the API did not answer within `--timeout` seconds |

## Status

`judge list`, `judge show` and `judge eval` are `implemented`: code and offline tests with the API
faked. See [SUPPORT.md](SUPPORT.md) for what that means and for the receipt when one is recorded.
