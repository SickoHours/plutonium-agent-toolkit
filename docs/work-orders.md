# Work orders: one piece of work from a person's ask to their verdict

A person who wants the result and not the labour says what they want. An agent does the work:
placement, donor, build, verify, install, load, and hands back a verdict. Today the person sees
that work as a scrolling terminal, or not at all. `pat work` gives it a shape three parties can
read: the agent doing it, a surface showing it, and a fresh agent picking it up later.

Three files, all in one work directory:

| File | Written by | What it is |
| --- | --- | --- |
| `work.json` | `work start`, once | The **order**: what was asked, in the person's words, the target, the donor and the door it came in by |
| `spine.json` | `work step`, appended | The **spine**: one row per step the agent took, with its outcome and the receipt that proves it, or none |
| `decisions.json` | `work ask` and `work answer`, appended | The **decision requests**: questions the agent could not settle alone, and the person's answers |

`work status` reads the three and says what a surface needs to show first: whether a question is
waiting on the person, which step is running, which comes next, and per spine row whether the
receipt it cites is there and unchanged.

Nothing here builds, plans, installs or reads the game. These routes record what other routes did
and tell a row backed by a receipt from a row that is only narration. The six facts about a module
stay in its evidence ledger (`evidence-ledger.md`); a spine row that says `load done` is a claim
about a step, never about a fact.

## The order

```json
{
  "schema": 1,
  "id": "3f9a1c2b8d7e6f50",
  "title": "Gums on Sumpf",
  "want": "I want the GobbleGum machine and the stock gums on Sumpf. Take the T5 donor if it is cleaner.",
  "target": "dlc5-beta2/zm_sumpf/zclassic",
  "door": "form",
  "donor": {"kind": "none", "ref": null},
  "subject": null,
  "by": "the person",
  "created": "2026-09-17T20:11:04+00:00"
}
```

| Field | Meaning |
| --- | --- |
| `title` | Up to 120 characters; what the surface calls this work |
| `want` | Up to 2000 characters; the ask in the person's own words, kept verbatim |
| `target` | A target key, `<foundation>/<map>/<mode>[/<location>]` (`target-sets.md`) |
| `door` | `form`: the person described what they want and placement decides the module. `shelf`: the person picked something that exists and `subject` names it |
| `donor` | `{kind, ref}`: `path` (a directory or archive on this machine), `release` (a named community release), `map` (a map of another game), or `none`, in which case the agent searches for prior art first (`playbooks/find-prior-art.md`) |
| `subject` | Shelf door only: the module or composition directory the work starts from, relative to the workspace |
| `by` | Who asked, if known |

The form door deliberately has no field for a module id, a category or a kind. Placement
(`playbooks/port-a-feature.md`) decides whether the ask is one module, a composition, or a
revision of something that exists, and the agent records that decision as the first spine row.
Asking the person to guess the shape is asking them to be wrong once.

## The spine

```json
{"schema": 1, "rows": [
  {"step": "placement", "outcome": "started", "at": "2026-09-17T20:12:00+00:00", "note": null, "receipt": null},
  {"step": "placement", "outcome": "done", "at": "2026-09-17T20:14:31+00:00",
   "note": "One new module, gums-sumpf, built alone on dlc5-beta2; the T5 donor's machine script is the reference.",
   "receipt": null},
  {"step": "build", "outcome": "done", "at": "2026-09-17T20:40:12+00:00", "note": null,
   "receipt": {"path": "jobs/gums-sumpf-build-001/receipt.json", "sha256": "<64 hex>"}}
]}
```

| Field | Meaning |
| --- | --- |
| `step` | One of `placement`, `donor`, `build`, `verify`, `install`, `load`, `verdict`, the order the work moves through. A step may repeat: a rebuild after a failed load is a second `build` row |
| `outcome` | `started`, `done`, `failed`, `skipped` |
| `at` | When the row was written, set by the route |
| `note` | Up to 2000 characters of the agent's words. Narration, never proof |
| `receipt` | The receipt this step wrote, relative to the workspace, with its SHA-256 at the time. A step with no receipt is recorded with none |

A row is appended under a lock and the file is replaced whole, the way an evidence ledger is
(`evidence-ledger.md`): two agents writing at once both land, and an interrupted write leaves the
rows that were there.

`work status` re-hashes every cited receipt and reports each row's evidence as one of:

| Evidence | Meaning |
| --- | --- |
| `receipted` | The receipt is there and its bytes match the row |
| `narrated` | The row cites no receipt. It is the agent's statement and nothing else |
| `receipt-missing` | The row cites a receipt that is not at that path now |
| `receipt-drifted` | The receipt is there and its bytes changed since the row was written |

A surface renders these in visibly different weights. The sentence in `note` is what the agent
said; the receipt beside it is what happened.

## The decision requests

```json
{"schema": 1, "requests": [
  {"id": "9b0c7d1e2f3a4b5c", "step": "placement",
   "question": "Both weapon forms, or the normal form only?",
   "options": [
     {"key": "both", "label": "Normal and Pack-a-Punch", "implies": "Two models, two sets of animations, twice the pool cost"},
     {"key": "normal", "label": "Normal only", "implies": "Half the pool cost; the PAP machine offers nothing for this gun"}
   ],
   "default": "both",
   "asked_at": "2026-09-17T20:15:02+00:00",
   "answer": {"choice": "normal", "via": "app", "at": "2026-09-17T20:16:40+00:00", "note": null}}
]}
```

| Field | Meaning |
| --- | --- |
| `question` | Up to 500 characters, in the person's terms |
| `step` | The step the question belongs to |
| `options` | Two to four, each `{key, label, implies}`: a short key, the label a button shows, and what choosing it means |
| `default` | The key the agent would take if the person said "you decide", or none |
| `answer` | `null` until answered, then `{choice, via, at, note}`. `via` names the surface: `app`, `host` (the agent's own chat), or `person` (typed at a terminal) |

Two rules make this usable rather than noisy:

- **One question at a time.** `work ask` refuses while an earlier request is unanswered. The
  agent asks, then polls `work status` until `answer` is not null, then continues.
- **Only what the agent cannot settle alone.** The questions belong to the round the porting
  playbook already names: base, target map, both weapon forms or normal only, menu route,
  acceptance scope, and a placement outcome that is genuinely ambiguous. Everything else the
  agent decides and records in a spine note.

An answer is written once. A changed mind is a new request. Whichever surface answers first
wins, and the others read it from the file.

## The routes

| Route | Effect | What it does |
| --- | --- | --- |
| `work start <workspace> --title T --want TEXT --target KEY [--donor REF --donor-kind K] [--subject DIR] [--by WHO] --output <new dir>` | writes-output | Writes `work.json` and a receipt into the new directory. The shelf door is `--subject`, which must exist in the workspace |
| `work step <work> --step S --outcome O [--note TEXT] [--receipt PATH --workspace ROOT]` | writes-record | Appends one spine row. A cited receipt must exist; it is hashed into the row |
| `work ask <work> --request FILE` | writes-record | Appends one decision request from a JSON file holding `question`, `step`, `options`, `default` |
| `work answer <work> --request-id ID --choice KEY --by app\|host\|person [--note TEXT]` | writes-record | Records the answer, once |
| `work status <work> [--workspace ROOT]` | inert | The order, `waiting_on_person`, `pending`, `current_step`, `next_step`, `last`, and `spine` with each row's evidence. Protocol `pat.work-status/1` |

`<work>` is the work directory or its `work.json`. The workspace's `jobs/` is the natural home
(`jobs/<title>-work-001/`), so the directory is one job among the others and never reused.

## What this is not

- Not a task tracker. One piece of work is one directory; there is no list, no state machine
  and no assignment. A surface lists work directories by reading them.
- Not evidence. A spine row cites a receipt; the receipt is the fact. The module's six facts come
  from its ledger and nothing here writes one.
- Not a chat. A decision request is a question with a closed set of answers. Free discussion
  stays with the agent host.
- Not the port. The steps, the gates and the decisions of a port are `playbooks/port-a-feature.md`
  and the porting skill; this page only gives them a record a surface can read.
