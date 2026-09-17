"""``judge list|show|eval``: narrow typed questions about modding evidence, asked of a hosted
System One model (TypeSafe's Jev) and scored against labeled cases.

The design rules are `docs/contributors/JUDGE.md`; this module implements them and nothing more.
An answer is **inferred state**: a typed value with a probability over a bounded piece of
evidence. It never becomes a build, install, test or acceptance fact, never writes to a bank,
promotes a signature, sends a game command or bypasses an allowlist. Code decides what to do
with it, and the thresholds are code.

Three routes:

- ``list`` and ``show`` are inert reads of the question sets that ship under
  ``knowledge/judge/``. They touch no network and carry no evidence.
- ``eval`` is a job, and the only route here that leaves the machine. Per case it materializes
  the set's criteria (section 3.1), redacts and bounds that case's state, writes the exact
  request bytes to ``request-<case>.json`` **before** sending, posts them to
  ``api.typesafe.ai``, writes the exact reply to ``response-<case>.json`` and finally
  ``scores.json`` (section 5). ``--dry-run`` writes the requests and sends nothing.

What leaves the machine is exactly what is in the request files: the declared state fields of
one case, line-redacted with ``PRIVATE`` and bounded to the set's ``max_bytes``, plus the
question texts. The key is read from ``TYPESAFE_API_KEY`` and never printed, logged or written
to a receipt; the state never reaches stdout either, where only counts, option ids and
probabilities appear. The route is opt-in per invocation and runs inside no build, install or
game job.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..core.errors import (BACKEND_FAILED, BACKEND_TIMEOUT, INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING,
                           INVALID_ARGUMENTS, JUDGE_KEY_MISSING, Failure)
from . import knowledge

SETS = Path(__file__).resolve().parent.parent / "knowledge" / "judge"
PROTOCOL = "pat.judge-eval/1"
SET_PROTOCOL = "pat.judge-set/1"
API_URL = "https://api.typesafe.ai/v1/systemone"
KEY_ENV = "TYPESAFE_API_KEY"

SET_ID = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")
FIELD = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
TYPES = ("choice", "noul", "score")

# The private pattern of JUDGE.md section 8. A console or crash line naming any of these words
# is the kind of line that carries a session ticket or a login, so the whole line is replaced
# before the state is encoded; the harness never tries to keep the safe half of such a line.
PRIVATE = re.compile(r"(token|ticket|authorization|password|connect|auth)", re.I)
REDACTED = "(redacted)"
ABSENT = "(not available)"
TRUNCATED = "\n(truncated)"

MAX_CASES = 500
MAX_CASES_BYTES = 16 * 1024 * 1024
MAX_SET_BYTES = 1024 * 1024
MAX_STATE_BYTES = 1024 * 1024        # ceiling on a set's own max_bytes
MAX_OPTIONS = 256
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
RETRY_STATUSES = (429, 529)
RETRY_BACKOFF = (1.0, 4.0)


# ----- sets -----------------------------------------------------------------------------

def _read_json(path: Path, limit: int, what: str):
    if path.is_symlink() or not path.is_file():
        raise Failure(INPUT_MISSING, f"{what} is missing or not a regular file: {path}")
    if path.stat().st_size > limit:
        raise Failure(INPUT_LIMIT, f"{what} exceeds {limit} bytes: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise Failure(INPUT_INVALID, f"{what} is not valid UTF-8 JSON: {path}") from exc


def set_path(set_id: str) -> Path:
    if not isinstance(set_id, str) or not SET_ID.match(set_id):
        raise Failure(INVALID_ARGUMENTS, "A set id is lowercase letters, digits and dashes (at most 64)",
                      "Run: pat judge list --json")
    path = SETS / f"{set_id}.json"
    if not path.is_file():
        available = ", ".join(sorted(p.stem for p in SETS.glob("*.json"))) or "none"
        raise Failure(INPUT_MISSING, f"No question set is named {set_id}", f"Sets that ship here: {available}")
    return path


def _text(value, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Failure(INPUT_INVALID, f"{what} must be a non-empty string")
    return value


def validate_set(data, label: str = "question set") -> dict:
    """Every rule of JUDGE.md section 3 a file can break, checked before anything is sent."""
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise Failure(INPUT_INVALID, f"{label}: unsupported question-set schema")
    for key in ("id", "title", "model"):
        _text(data.get(key), f"{label}: {key}")
    state = data.get("state")
    if not isinstance(state, dict) or not isinstance(state.get("fields"), dict) or not state["fields"]:
        raise Failure(INPUT_INVALID, f"{label}: state.fields must name at least one field")
    for name, description in state["fields"].items():
        if not FIELD.match(str(name)):
            raise Failure(INPUT_INVALID, f"{label}: {name!r} is not a state field name")
        _text(description, f"{label}: state.fields.{name}")
    if not isinstance(state.get("max_bytes"), int) or not 256 <= state["max_bytes"] <= MAX_STATE_BYTES:
        raise Failure(INPUT_INVALID, f"{label}: state.max_bytes must be an integer from 256 to {MAX_STATE_BYTES}")
    if not isinstance(state.get("redact"), bool):
        raise Failure(INPUT_INVALID, f"{label}: state.redact must be true or false")
    questions = data.get("questions")
    if not isinstance(questions, dict) or not questions:
        raise Failure(INPUT_INVALID, f"{label}: questions must name at least one question")
    for qid, question in questions.items():
        where = f"{label}: questions.{qid}"
        if not FIELD.match(str(qid)):
            raise Failure(INPUT_INVALID, f"{where} is not a question id")
        if not isinstance(question, dict) or question.get("type") not in TYPES:
            raise Failure(INPUT_INVALID, f"{where}.type must be one of {', '.join(TYPES)}")
        _text(question.get("instructions"), f"{where}.instructions")
        if ("criteria" in question) == ("criteria_from" in question):
            raise Failure(INPUT_INVALID, f"{where} needs exactly one of criteria or criteria_from")
        if "criteria_from" in question:
            _validate_criteria_from(question["criteria_from"], question["type"], state["fields"], where)
    policy = data.get("policy")
    if not isinstance(policy, dict):
        raise Failure(INPUT_INVALID, f"{label}: policy must carry act and ask")
    for key in ("act", "ask"):
        value = policy.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
            raise Failure(INPUT_INVALID, f"{label}: policy.{key} must be a number from 0 to 1")
    return data


def _validate_criteria_from(spec, type_: str, fields: dict, where: str) -> None:
    if not isinstance(spec, dict):
        raise Failure(INPUT_INVALID, f"{where}.criteria_from must be an object")
    forms = [k for k in ("knowledge", "state_lines", "state_regex") if k in spec]
    if len(forms) != 1:
        raise Failure(INPUT_INVALID, f"{where}.criteria_from needs exactly one of knowledge, state_lines, state_regex")
    if type_ != "choice":
        raise Failure(INPUT_INVALID, f"{where}: criteria_from builds options, so the question must be a choice")
    if forms[0] == "knowledge":
        if spec["knowledge"] not in knowledge.FILES:
            raise Failure(INPUT_INVALID, f"{where}.criteria_from.knowledge is not a shipped knowledge file")
        _text(spec.get("key"), f"{where}.criteria_from.key")
        _text(spec.get("describe"), f"{where}.criteria_from.describe")
    elif forms[0] == "state_lines":
        if spec["state_lines"] not in fields:
            raise Failure(INPUT_INVALID, f"{where}.criteria_from.state_lines names no declared state field")
    else:
        try:
            re.compile(spec["state_regex"])
        except (re.error, TypeError) as exc:
            raise Failure(INPUT_INVALID, f"{where}.criteria_from.state_regex is not a regular expression") from exc
        named = spec.get("fields")
        if not isinstance(named, list) or not named or any(f not in fields for f in named):
            raise Failure(INPUT_INVALID, f"{where}.criteria_from.fields must list declared state fields")
    plus = spec.get("plus", {})
    if not isinstance(plus, dict):
        raise Failure(INPUT_INVALID, f"{where}.criteria_from.plus must be an object of option to description")
    for option, description in plus.items():
        _text(description, f"{where}.criteria_from.plus.{option}")


def load_set(set_id: str) -> tuple[dict, Path]:
    path = set_path(set_id)
    data = validate_set(_read_json(path, MAX_SET_BYTES, "Question set"), f"judge/{path.name}")
    if data["id"] != set_id:
        raise Failure(INPUT_INVALID, f"judge/{path.name} carries id {data['id']!r}; a set's id is its file name")
    return data, path


def listing() -> dict:
    """Every set that ships, with the fields a caller needs to pick one. No evidence, no network."""
    rows = []
    for path in sorted(SETS.glob("*.json")):
        data = validate_set(_read_json(path, MAX_SET_BYTES, "Question set"), f"judge/{path.name}")
        rows.append({"id": data["id"], "title": data["title"], "model": data["model"],
                     "questions": sorted(data["questions"]), "state_fields": sorted(data["state"]["fields"]),
                     "max_bytes": data["state"]["max_bytes"], "redact": data["state"]["redact"],
                     "policy": data["policy"], "file": path.name})
    return {"protocol": SET_PROTOCOL, "sets": rows, "count": len(rows),
            "note": "A set is a question bank, not an answer. pat judge show <set> prints one; pat judge eval scores it "
                    "against labeled cases and is the only route here that sends anything off this machine."}


def show(set_id: str) -> dict:
    data, path = load_set(set_id)
    return {"protocol": SET_PROTOCOL, "file": path.name, "set": data,
            "note": "A judgment from this set is inferred state: it may pick which observed thing applies and say how "
                    "sure it is. It never promotes a signature, writes a ledger fact or acts. docs/contributors/JUDGE.md."}


# ----- state ----------------------------------------------------------------------------

def redact_text(text: str) -> tuple[str, int]:
    """Replace every line the private pattern matches; return the text and how many lines went."""
    lines = text.splitlines()
    kept = [REDACTED if PRIVATE.search(line) else line for line in lines]
    return "\n".join(kept), sum(1 for a, b in zip(lines, kept) if a != b)


def encoded_length(state: dict) -> int:
    return len(json.dumps(state, ensure_ascii=False, allow_nan=False).encode("utf-8"))


def bound_state(values: dict, max_bytes: int) -> tuple[dict, dict]:
    """Cut the longest field until the encoded state fits ``max_bytes``.

    Each cut keeps the head of the field and marks it, because a crash text's first lines carry
    the exception and the error message. Returns the bounded state and, per field cut, how many
    characters it had and how many were kept."""
    kept = dict(values)
    truncation: dict[str, dict] = {}
    for _ in range(len(kept) * 8 + 8):
        excess = encoded_length(kept) - max_bytes
        if excess <= 0:
            return kept, truncation
        name = max(sorted(kept), key=lambda k: len(kept[k]))
        body = kept[name][:-len(TRUNCATED)] if name in truncation else kept[name]
        body = body[:max(0, len(body) - max(excess, 1))]
        kept[name] = body + TRUNCATED
        truncation[name] = {"characters": len(values[name]), "kept_characters": len(body)}
    raise Failure(INPUT_LIMIT, f"State cannot be bounded to the set's max_bytes ({max_bytes})",
                  "Raise state.max_bytes in the set, or give the case fewer fields.")


def materialize_state(question_set: dict, case: dict) -> tuple[dict, dict]:
    """One case's declared fields, in declared order: absent ones replaced, then redacted, then
    bounded. Nothing else of the case is sent."""
    declared = question_set["state"]["fields"]
    raw = case.get("state") or {}
    absent = set(case.get("absent") or [])
    values: dict[str, str] = {}
    missing = []
    for name in declared:
        value = raw.get(name)
        if name in absent or not isinstance(value, str) or not value.strip() or value.strip() == ABSENT:
            values[name] = ABSENT
            missing.append(name)
        else:
            values[name] = value
    redactions = {}
    if question_set["state"]["redact"]:
        for name, value in values.items():
            values[name], hits = redact_text(value)
            if hits:
                redactions[name] = hits
    bounded, truncation = bound_state(values, question_set["state"]["max_bytes"])
    notes = {"absent": missing, "redacted_lines": redactions, "truncated": truncation,
             "bytes": encoded_length(bounded), "max_bytes": question_set["state"]["max_bytes"],
             "ignored_fields": sorted(set(raw) - set(declared))}
    return bounded, notes


# ----- criteria -------------------------------------------------------------------------

class _Row(dict):
    def __missing__(self, key):
        raise Failure(INPUT_INVALID, f"describe names {{{key}}}, which the knowledge row does not carry")


def _from_knowledge(spec: dict) -> dict:
    data = knowledge.load(spec["knowledge"])
    rows = data.get("rows")
    if not isinstance(rows, list) or not rows:
        raise Failure(INPUT_INVALID, f"{spec['knowledge']} carries no rows to build options from")
    options = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get(spec["key"]), str):
            raise Failure(INPUT_INVALID, f"{spec['knowledge']}: a row has no {spec['key']} to use as an option")
        options[row[spec["key"]]] = spec["describe"].format_map(_Row(row))
    return options


def _from_state_lines(spec: dict, state: dict) -> dict:
    """Number the lines of one field and offer each as an option: a judgment points at its
    evidence by selecting a line, never by writing one. Blank lines justify nothing and are
    skipped; the numbers stay the field's own."""
    options = {}
    for number, line in enumerate(state[spec["state_lines"]].splitlines(), 1):
        if line.strip():
            options[str(number)] = line.strip()
    return options


def _from_state_regex(spec: dict, state: dict) -> dict:
    pattern = re.compile(spec["state_regex"])
    options = {}
    for field in spec["fields"]:
        for number, line in enumerate(state[field].splitlines(), 1):
            for match in pattern.finditer(line):
                token = match.group(0)
                if token and token not in options:
                    options[token] = f"{token}, named in {field} line {number}"
    return options


def materialize_criteria(question: dict, state: dict, qid: str) -> tuple[dict | list | None, dict | None]:
    """The criteria this request carries, plus how they were built when they were built here.

    A ``criteria_from`` question whose state yields nothing is the one case where no question can
    be asked: what is left is the no-match option alone, and a choice of one is both meaningless
    and refused by the API. The criteria come back as ``None`` and the caller leaves that question
    out of this case's request rather than inventing an option or failing the whole run. It is
    recorded per case, in the request provenance and in the scores, as not asked."""
    if "criteria" in question:
        return _check_criteria(question["criteria"], question["type"], qid), None
    spec = question["criteria_from"]
    if "knowledge" in spec:
        options, how = _from_knowledge(spec), {"form": "knowledge", "source": spec["knowledge"]}
    elif "state_lines" in spec:
        options, how = _from_state_lines(spec, state), {"form": "state_lines", "field": spec["state_lines"]}
    else:
        options, how = _from_state_regex(spec, state), {"form": "state_regex", "fields": list(spec["fields"])}
    how["built"] = len(options)
    for option, description in (spec.get("plus") or {}).items():
        options[option] = description
    how["plus"] = sorted(spec.get("plus") or {})
    if len(options) < 2:
        how["not_asked"] = ("the state named nothing to choose between; only the no-match option was left"
                            if how["built"] == 0 else "fewer than two options were built from the state")
        return None, how
    if len(options) > MAX_OPTIONS:
        raise Failure(INPUT_LIMIT, f"questions.{qid}: {len(options)} options exceed the bound of {MAX_OPTIONS}",
                      "Narrow the criteria_from source; the model cannot choose an omitted value, so options are never dropped silently.")
    return _check_criteria(options, question["type"], qid), how


def _check_criteria(criteria, type_: str, qid: str):
    """The API's own rules, checked here so a bad set fails before a request is paid for."""
    where = f"questions.{qid}.criteria"
    if type_ == "choice":
        if not isinstance(criteria, dict) or len(criteria) < 2:
            raise Failure(INPUT_INVALID, f"{where}: a choice needs at least two options")
        for option, description in criteria.items():
            if not isinstance(option, str) or not option:
                raise Failure(INPUT_INVALID, f"{where}: an option name must be a non-empty string")
            _text(description, f"{where}.{option}")
        return dict(criteria)
    if type_ == "noul":
        if not isinstance(criteria, dict) or set(criteria) != {"true", "false"}:
            raise Failure(INPUT_INVALID, f"{where}: a noul's criteria is an object with true and false texts")
        for key in ("true", "false"):
            _text(criteria[key], f"{where}.{key}")
        return {"true": criteria["true"], "false": criteria["false"]}
    if not isinstance(criteria, list) or len(criteria) < 2:
        raise Failure(INPUT_INVALID, f"{where}: a score's criteria is an ordered array of at least two levels")
    return [_text(level, f"{where}[{i}]") for i, level in enumerate(criteria)]


def build_request(question_set: dict, model: str, state: dict) -> tuple[dict, dict]:
    questions, how = {}, {}
    for qid, question in question_set["questions"].items():
        criteria, built = materialize_criteria(question, state, qid)
        how[qid] = {"options": 0 if criteria is None else len(criteria), **(built or {"form": "literal"})}
        if criteria is None:
            continue
        questions[qid] = {"type": question["type"], "instructions": question["instructions"], "criteria": criteria}
    if not questions:
        raise Failure(INPUT_INVALID, "This case builds no answerable question; nothing was sent",
                      "Every criteria_from question materialized to its no-match option alone. Read the state fields the set declares.")
    return {"model": model, "state": state, "questions": questions}, how


# ----- cases ----------------------------------------------------------------------------

def load_cases(path: Path, set_id: str) -> list[dict]:
    data = _read_json(path, MAX_CASES_BYTES, "Cases file")
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise Failure(INPUT_INVALID, f"{path}: unsupported cases schema")
    if data.get("set") != set_id:
        raise Failure(INPUT_INVALID, f"{path} holds cases for set {data.get('set')!r}, not {set_id!r}")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise Failure(INPUT_INVALID, f"{path}: cases must be a non-empty list")
    if len(cases) > MAX_CASES:
        raise Failure(INPUT_LIMIT, f"{path}: more than {MAX_CASES} cases in one run")
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not CASE_ID.match(str(case.get("id", ""))):
            raise Failure(INPUT_INVALID, f"{path}: every case needs an id of letters, digits, dot, dash or underscore")
        if case["id"] in seen:
            raise Failure(INPUT_INVALID, f"{path}: two cases share the id {case['id']!r}")
        seen.add(case["id"])
        if not isinstance(case.get("state"), dict):
            raise Failure(INPUT_INVALID, f"{path}: case {case['id']} has no state object")
        if not isinstance(case.get("expected", {}), dict):
            raise Failure(INPUT_INVALID, f"{path}: case {case['id']} expected must be an object")
        if not isinstance(case.get("absent", []), list):
            raise Failure(INPUT_INVALID, f"{path}: case {case['id']} absent must be a list of field names")
    return cases


# ----- the API --------------------------------------------------------------------------

def require_key() -> str:
    key = os.environ.get(KEY_ENV, "")
    if not key.strip():
        raise Failure(JUDGE_KEY_MISSING, f"{KEY_ENV} is not in the environment; nothing was sent",
                      f"Export it from your own file in this shell, for example: set -a; . ~/.config/typesafe/env; set +a. "
                      f"The toolkit never reads, writes or prints the key. Use --dry-run to build the requests without one.")
    return key.strip()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would re-send the bearer to whatever host answered. Refuse instead."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _opener():
    return urllib.request.build_opener(_NoRedirect())


def _send(body: bytes, key: str, timeout: int) -> tuple[int, bytes]:
    """One POST of already-encoded bytes. The key lives in this call's headers and nowhere else."""
    request = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with _opener().open(request, timeout=timeout) as response:  # noqa: S310 - fixed https endpoint
            return response.status, response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, exc.read(MAX_RESPONSE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            raise Failure(BACKEND_TIMEOUT, f"The judge API did not answer within {timeout} s",
                          "The request files in this directory are the exact bytes; run again into a new --output.") from exc
        raise Failure(BACKEND_FAILED, f"Cannot reach {API_URL}: {reason}",
                      "This route is the only one that needs the internet; nothing was scored.") from exc


def _http_failure(status: int, payload: bytes) -> Failure:
    detail = payload[:400].decode("utf-8", errors="replace").strip()
    if status == 401:
        return Failure(JUDGE_KEY_MISSING, f"The judge API refused the key ({KEY_ENV}): HTTP 401",
                       "The key in this shell is absent, wrong or expired. The toolkit never stores it.")
    if status == 422:
        return Failure(INPUT_INVALID, f"The judge API refused the request: HTTP 422. {detail}",
                       "The request file in this directory is the exact body it refused; fix the question set.")
    return Failure(BACKEND_FAILED, f"The judge API answered HTTP {status}. {detail}",
                   "429 and 529 are rate limit and overload; wait, then run again into a new --output.")


def ask(body: bytes, key: str, timeout: int, log) -> tuple[bytes, dict]:
    """Send one request, retrying only the two statuses the API documents as safe to retry."""
    for attempt, pause in enumerate((*RETRY_BACKOFF, None)):
        status, payload = _send(body, key, timeout)
        log(f"POST {API_URL} -> HTTP {status} ({len(payload)} bytes)")
        if status not in RETRY_STATUSES or pause is None:
            break
        log(f"retrying after {pause}s (attempt {attempt + 1})")
        time.sleep(pause)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise Failure(INPUT_LIMIT, f"The judge API answered with more than {MAX_RESPONSE_BYTES} bytes")
    if status != 200:
        raise _http_failure(status, payload)
    try:
        parsed = json.loads(payload)
    except ValueError as exc:
        raise Failure(INPUT_INVALID, "The judge API answered with something that is not JSON",
                      "The exact bytes are in the response file beside this receipt.") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("answers"), dict):
        raise Failure(INPUT_INVALID, "The judge API answer carries no answers object")
    return payload, parsed


# ----- scoring --------------------------------------------------------------------------

def _top(probabilities: dict, count: int = 3) -> list[dict]:
    rows = [(k, v) for k, v in probabilities.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    rows.sort(key=lambda row: (-row[1], row[0]))
    return [{"option": k, "probability": round(float(v), 6)} for k, v in rows[:count]]


def read_answer(qid: str, type_: str, answer, case_id: str) -> dict:
    """One answer in the shape the tables need: the value, the probability of that value, and the
    distribution it came from. A noul carries no confidence of its own, so the probability of the
    side it landed on is reported as one; the raw noul stays beside it."""
    where = f"case {case_id}, question {qid}"
    if not isinstance(answer, dict) or answer.get("type") != type_:
        raise Failure(INPUT_INVALID, f"{where}: the API answered type {answer.get('type') if isinstance(answer, dict) else answer!r}, not {type_}")
    if type_ == "choice":
        choice = answer.get("choice")
        if not isinstance(choice, str):
            raise Failure(INPUT_INVALID, f"{where}: the answer carries no choice")
        probabilities = answer.get("probabilities") if isinstance(answer.get("probabilities"), dict) else {}
        confidence = answer.get("confidence")
        return {"answer": choice, "confidence": _number(confidence, where), "top": _top(probabilities)}
    if type_ == "noul":
        noul = _number(answer.get("noul"), where)
        value = noul >= 0.5
        return {"answer": value, "noul": noul, "confidence": round(noul if value else 1 - noul, 6),
                "top": _top({"true": noul, "false": round(1 - noul, 6)})}
    score = _number(answer.get("score"), where)
    probabilities = answer.get("probabilities") if isinstance(answer.get("probabilities"), dict) else {}
    return {"answer": score, "confidence": _number(answer.get("confidence"), where), "top": _top(probabilities)}


def _number(value, where: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise Failure(INPUT_INVALID, f"{where}: the answer carries no number where one belongs")
    return round(float(value), 6)


def agrees(type_: str, expected, answer, where: str) -> bool:
    if type_ == "choice":
        if not isinstance(expected, str):
            raise Failure(INPUT_INVALID, f"{where}: a choice label is the option's name")
        return expected == answer
    if type_ == "noul":
        if not isinstance(expected, bool):
            raise Failure(INPUT_INVALID, f"{where}: a noul label is true or false")
        return expected is answer
    if isinstance(expected, bool) or not isinstance(expected, (int, float)):
        raise Failure(INPUT_INVALID, f"{where}: a score label is the number the level should land on")
    # JUDGE.md leaves score scoring open; a weighted score agrees when it lands on its level.
    return abs(float(expected) - float(answer)) <= 0.5


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def score_run(question_set: dict, model: str, rows: list[dict]) -> dict:
    """``scores.json``: per question the counts and the two mean confidences, per case the
    expected label, the answer, its confidence and the top three probabilities. Agreement alone
    is not a pass; confident_and_wrong is the number that matters (section 5).

    ``not_asked`` is the count section 5 does not name, because a question can be missing from a
    case's request: a criteria_from question whose state named nothing has no options to choose
    between. Those cases are excluded from labeled, agree and disagree rather than counted as a
    miss the model never had the chance to make."""
    act = float(question_set["policy"]["act"])
    questions = {}
    for qid, question in question_set["questions"].items():
        type_ = question["type"]
        cases, agree, disagree, unknown, not_asked, wrong = [], [], [], 0, 0, 0
        for row in rows:
            expected = row["expected"].get(qid) if isinstance(row["expected"], dict) else None
            read = row["answers"].get(qid)
            entry = {"case": row["case"], "expected": expected}
            if read is None:
                # The state offered nothing to choose between, so this question was left out of
                # that case's request. It is neither right nor wrong, and it is not a label gap.
                entry.update({"answer": None, "confidence": None, "top": [], "verdict": "not-asked",
                              "reason": row.get("not_asked", {}).get(qid, "not asked for this case")})
                not_asked += 1
                cases.append(entry)
                continue
            entry.update({"answer": read["answer"], "confidence": read["confidence"], "top": read["top"]})
            if "noul" in read:
                entry["noul"] = read["noul"]
            if qid not in (row["expected"] or {}):
                entry["verdict"] = "unknown"
                unknown += 1
            else:
                ok = agrees(type_, expected, read["answer"], f"case {row['case']}, question {qid}")
                entry["verdict"] = "agree" if ok else "disagree"
                (agree if ok else disagree).append(read["confidence"])
                if not ok and read["confidence"] > act:
                    entry["confident_and_wrong"] = True
                    wrong += 1
            cases.append(entry)
        questions[qid] = {"type": type_, "cases": len(rows), "labeled": len(agree) + len(disagree),
                          "agree": len(agree), "disagree": len(disagree), "unknown": unknown,
                          "not_asked": not_asked, "mean_confidence_agree": _mean(agree),
                          "mean_confidence_disagree": _mean(disagree), "confident_and_wrong": wrong, "rows": cases}
    totals = {key: sum(q[key] for q in questions.values())
              for key in ("labeled", "agree", "disagree", "unknown", "not_asked", "confident_and_wrong")}
    usage = {"requests": len(rows),
             "input_tokens": sum(int(row["usage"].get("input_tokens") or 0) for row in rows),
             "output_tokens": sum(int(row["usage"].get("output_tokens") or 0) for row in rows)}
    return {"schema": 1, "set": question_set["id"], "model": model, "policy": question_set["policy"],
            "cases": len(rows), "questions": questions, "totals": totals, "usage": usage,
            "note": "A judgment is inferred state. confident_and_wrong counts answers above policy.act that disagree with "
                    "the label; JUDGE.md section 5 says which of the four misses each one is before anything is changed."}


# ----- the job --------------------------------------------------------------------------

def add_parser(sub, common) -> None:
    q = sub.add_parser("judge", help="Typed judgments about modding evidence from a hosted System One model; opt-in, and the only route that sends evidence off this machine")
    actions = q.add_subparsers(dest="action", required=True)
    a = actions.add_parser("list", help="The question sets that ship with the toolkit, with id and title")
    a.add_argument("--json", action="store_true")
    a = actions.add_parser("show", help="Print one question set exactly as it ships")
    a.add_argument("set", help="Set id, for example crash-triage")
    a.add_argument("--json", action="store_true")
    a = actions.add_parser("eval", help="Score one set against labeled cases; sends each case's redacted, bounded state to api.typesafe.ai")
    a.add_argument("set", help="Set id, for example crash-triage")
    a.add_argument("--cases", required=True, help="Labeled cases file (JUDGE.md section 4); keep it out of a public repository")
    a.add_argument("--model", help="Model to ask instead of the set's own, for example jev-latest")
    a.add_argument("--dry-run", action="store_true", help="Write the request files and send nothing; no key is needed")
    common(a)


class _Log:
    """Diagnostics for this run. Never stdout, never the key, never a line of the state."""

    def __init__(self, path: Path):
        self.path = path
        self.handle = path.open("x", encoding="utf-8")

    def __call__(self, line: str) -> None:
        self.handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {line}\n")
        self.handle.flush()

    def close(self) -> None:
        self.handle.close()


def execute(args, job) -> dict:
    question_set, path = load_set(args.set)
    job.input(path)
    cases_path = job.input(Path(args.cases).expanduser())
    cases = load_cases(cases_path, args.set)
    model = args.model or question_set["model"]
    _text(model, "--model")
    key = None if args.dry_run else require_key()
    log = _Log(job.root / "judge.log")
    try:
        log(f"set {args.set} ({path.name}), {len(cases)} case(s), model {model}, dry_run {bool(args.dry_run)}")
        log(f"state is redacted per line with the private pattern and bounded to {question_set['state']['max_bytes']} bytes"
            if question_set["state"]["redact"] else "the set does not ask for redaction; only the byte bound applies")
        prepared, rows = [], []
        for case in cases:
            job.check_deadline()
            state, notes = materialize_state(question_set, case)
            request, how = build_request(question_set, model, state)
            body = json.dumps(request, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8")
            name = f"request-{case['id']}.json"
            (job.root / name).write_bytes(body)
            log(f"{case['id']}: wrote {name} ({len(body)} bytes), state {notes['bytes']} bytes, "
                f"absent {notes['absent'] or 'none'}, redacted lines {sum(notes['redacted_lines'].values())}, "
                f"truncated {sorted(notes['truncated']) or 'none'}, options "
                + ", ".join(f"{qid}={row['options']}" for qid, row in how.items()))
            prepared.append({"case": case["id"], "request": name, "request_bytes": len(body), "criteria": how, **notes})
            if args.dry_run:
                continue
            payload, parsed = ask(body, key, args.timeout, log)
            reply = f"response-{case['id']}.json"
            (job.root / reply).write_bytes(payload)
            answers = {qid: read_answer(qid, question["type"], parsed["answers"].get(qid), case["id"])
                       for qid, question in request["questions"].items()}
            rows.append({"case": case["id"], "expected": case.get("expected") or {}, "answers": answers,
                         "not_asked": {qid: row["not_asked"] for qid, row in how.items() if "not_asked" in row},
                         "response": reply, "usage": parsed.get("usage") if isinstance(parsed.get("usage"), dict) else {},
                         "model": parsed.get("model")})
            log(f"{case['id']}: wrote {reply}; " + ", ".join(f"{qid}={a['answer']}@{a['confidence']}" for qid, a in answers.items()))
        result = {"protocol": PROTOCOL, "set": args.set, "set_file": path.name, "model_requested": model,
                  "cases": len(cases), "dry_run": bool(args.dry_run), "requests": prepared, "log": "judge.log",
                  "endpoint": API_URL if not args.dry_run else None}
        if args.dry_run:
            log("dry run: nothing was sent and nothing was scored")
            result["note"] = ("Dry run: the request files are the exact bytes a real run would send, and nothing left "
                              "this machine. Read one before running without --dry-run.")
            return result
        answered = {row["model"] for row in rows if isinstance(row.get("model"), str)}
        scores = score_run(question_set, sorted(answered)[0] if len(answered) == 1 else model, rows)
        (job.root / "scores.json").write_text(json.dumps(scores, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        log(f"scores.json: {scores['totals']}")
        result.update({"model_answered": sorted(answered), "scores": scores, "scores_file": "scores.json",
                       "note": "Judgments are inferred state and promote nothing. A set may act only under JUDGE.md "
                               "section 6, and only behind its own flag."})
        return result
    finally:
        log.close()
