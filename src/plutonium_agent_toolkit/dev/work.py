"""``work start|step|ask|answer|status``: one piece of work from a person's ask to their verdict.

A **work order** is what a person asked for, in their words, with the target it is for and the
donor it starts from. A **spine** is the ordered record of the steps an agent took on it, each
row pointing at the receipt that proves it or saying plainly that it has none. A **decision
request** is a question the agent could not settle alone, with the options and what each
implies; its answer is a row beside it, written by whichever surface the person answered from.

Files, all inside one work directory the caller names once with ``--output``:

``work.json``       the order, written once by ``work start`` (a job with its receipt)
``spine.json``      the steps, appended by ``work step`` (a record file, locked, all-or-nothing)
``decisions.json``  the requests and their answers, appended by ``work ask`` and ``work answer``

``work status`` reads the three and reports the current step, every pending question, and per
spine row whether its receipt is there and unchanged. Nothing here builds, installs, plans or
touches a game; the routes record what other routes did, and the reader tells a row backed by
a receipt from a row that is only narration. Format: ``docs/work-orders.md``.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from ..core.envelope import now
from ..core.errors import INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING, Failure
from ..core.jobs import Job
from ..core.receipts import sha256_file
from . import ledger
from .targets import parse_key

PROTOCOL = "pat.work-status/1"
ORDER_SCHEMA = 1

# The steps a piece of work moves through, in the order the intent named them. A row may name
# any of them in any order (a rebuild after a failed load is a second ``build`` row); the order
# here is what ``status`` uses to say which step comes next when the last row is done.
STEPS = ("placement", "donor", "build", "verify", "install", "load", "verdict")
OUTCOMES = ("started", "done", "failed", "skipped")
DOORS = ("form", "shelf")
DONOR_KINDS = ("path", "release", "map", "none")
ANSWERED_VIA = ("app", "host", "person")

KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}\Z")
HEX16 = re.compile(r"^[a-f0-9]{16}\Z")
MAX_TITLE, MAX_WANT, MAX_TEXT, MAX_QUESTION, MAX_LABEL = 120, 2000, 2000, 500, 120
MAX_ROWS, MAX_DECISIONS, MIN_OPTIONS, MAX_OPTIONS = 256, 64, 2, 4
MAX_BYTES = 1024 * 1024


# ----- validation ----------------------------------------------------------------------

def _text(value, what: str, limit: int, field: str, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        raise Failure(INPUT_INVALID, f"{what} must be text", field=field)
    if len(value) > limit:
        raise Failure(INPUT_LIMIT, f"{what} is longer than {limit} characters", field=field)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise Failure(INPUT_INVALID, f"{what} holds a value UTF-8 cannot write", field=field) from exc
    return value


def _choice(value, what: str, allowed: tuple, field: str) -> str:
    if value not in allowed:
        raise Failure(INPUT_INVALID, f"{what} must be one of {', '.join(allowed)}: {value!r}", field=field)
    return value


def _relative(value, what: str, field: str) -> str:
    text = _text(value, what, 512, field)
    p = Path(text)
    if p.is_absolute() or ".." in p.parts or "\\" in text:
        raise Failure(INPUT_INVALID, f"{what} must be a forward-slash path relative to the workspace, never climbing out of it: {text!r}",
                      field=field)
    return text


def validate_order(data: dict) -> dict:
    """The order as ``work start`` writes it. Every field checked; nothing inferred."""
    if not isinstance(data, dict):
        raise Failure(INPUT_INVALID, "A work order is an object", field="/")
    if data.get("schema") != ORDER_SCHEMA:
        raise Failure(INPUT_INVALID, f"A work order is schema {ORDER_SCHEMA}", field="/schema")
    order = {"schema": ORDER_SCHEMA}
    order["id"] = data.get("id")
    if not isinstance(order["id"], str) or not HEX16.match(order["id"]):
        raise Failure(INPUT_INVALID, "A work order id is 16 hex characters", field="/id")
    order["title"] = _text(data.get("title"), "title", MAX_TITLE, "/title")
    order["want"] = _text(data.get("want"), "want", MAX_WANT, "/want")
    target = data.get("target")
    if not isinstance(target, str):
        raise Failure(INPUT_INVALID, "target must be a target key <foundation>/<map>/<mode>[/<location>]", field="/target")
    parse_key(target)
    order["target"] = target
    order["door"] = _choice(data.get("door"), "door", DOORS, "/door")
    donor = data.get("donor")
    if not isinstance(donor, dict):
        raise Failure(INPUT_INVALID, "donor is an object {kind, ref}", field="/donor")
    kind = _choice(donor.get("kind"), "donor.kind", DONOR_KINDS, "/donor/kind")
    ref = _text(donor.get("ref"), "donor.ref", MAX_TEXT, "/donor/ref", required=kind != "none")
    if kind == "none" and ref is not None:
        raise Failure(INPUT_INVALID, "a donor of kind none names no ref", field="/donor/ref")
    order["donor"] = {"kind": kind, "ref": ref}
    subject = data.get("subject")
    if order["door"] == "shelf":
        if not isinstance(subject, str):
            raise Failure(INPUT_INVALID, "the shelf door names the module or composition the work starts from", field="/subject")
        order["subject"] = _relative(subject, "subject", "/subject")
    elif subject is not None:
        raise Failure(INPUT_INVALID, "the form door names no subject; placement decides the module", field="/subject")
    else:
        order["subject"] = None
    order["by"] = _text(data.get("by"), "by", MAX_LABEL, "/by", required=False)
    order["created"] = _text(data.get("created"), "created", 64, "/created")
    return order


def validate_step(row: dict, index: int) -> dict:
    field = f"/rows/{index}"
    if not isinstance(row, dict):
        raise Failure(INPUT_INVALID, "A spine row is an object", field=field)
    out = {"step": _choice(row.get("step"), "step", STEPS, field + "/step"),
           "outcome": _choice(row.get("outcome"), "outcome", OUTCOMES, field + "/outcome"),
           "at": _text(row.get("at"), "at", 64, field + "/at"),
           "note": _text(row.get("note"), "note", MAX_TEXT, field + "/note", required=False),
           "receipt": None}
    receipt = row.get("receipt")
    if receipt is not None:
        if not isinstance(receipt, dict):
            raise Failure(INPUT_INVALID, "receipt is an object {path, sha256}", field=field + "/receipt")
        sha = receipt.get("sha256")
        if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise Failure(INPUT_INVALID, "receipt.sha256 is the file's SHA-256 when the row was written", field=field + "/receipt/sha256")
        out["receipt"] = {"path": _relative(receipt.get("path"), "receipt.path", field + "/receipt/path"), "sha256": sha}
    unknown = set(row) - {"step", "outcome", "at", "note", "receipt"}
    if unknown:
        raise Failure(INPUT_INVALID, f"unknown spine fields: {sorted(unknown)}", field=field)
    return out


def validate_request(data: dict, field: str = "/") -> dict:
    """A decision request as the agent wrote it, before it is given an id and a time."""
    if not isinstance(data, dict):
        raise Failure(INPUT_INVALID, "A decision request is an object", field=field)
    out = {"question": _text(data.get("question"), "question", MAX_QUESTION, field + "question"),
           "step": _choice(data.get("step"), "step", STEPS, field + "step")}
    options = data.get("options")
    if not isinstance(options, list) or not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        raise Failure(INPUT_INVALID, f"options is a list of {MIN_OPTIONS} to {MAX_OPTIONS} choices", field=field + "options")
    keys = []
    out["options"] = []
    for i, option in enumerate(options):
        f = f"{field}options/{i}"
        if not isinstance(option, dict):
            raise Failure(INPUT_INVALID, "an option is an object {key, label, implies}", field=f)
        key = option.get("key")
        if not isinstance(key, str) or not KEY.match(key):
            raise Failure(INPUT_INVALID, "an option key is a short lowercase word", field=f + "/key")
        if key in keys:
            raise Failure(INPUT_INVALID, f"option key repeated: {key}", field=f + "/key")
        keys.append(key)
        out["options"].append({"key": key, "label": _text(option.get("label"), "label", MAX_LABEL, f + "/label"),
                               "implies": _text(option.get("implies"), "implies", MAX_QUESTION, f + "/implies", required=False)})
    default = data.get("default")
    if default is not None and default not in keys:
        raise Failure(INPUT_INVALID, "default names one of the option keys", field=field + "default")
    out["default"] = default
    unknown = set(data) - {"question", "step", "options", "default"}
    if unknown:
        raise Failure(INPUT_INVALID, f"unknown request fields: {sorted(unknown)}", field=field)
    return out


# ----- files ---------------------------------------------------------------------------

def _read(path: Path, what: str) -> dict | None:
    if not ledger.regular(path):
        return None
    if path.stat().st_size > MAX_BYTES:
        raise Failure(INPUT_LIMIT, f"{what} is larger than {MAX_BYTES} bytes: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Failure(INPUT_INVALID, f"{what} is not readable JSON: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise Failure(INPUT_INVALID, f"{what} must be an object: {path}")
    return data


def _directory(text: str) -> Path:
    root = Path(text)
    if root.is_file() and root.name == "work.json":
        root = root.parent
    if not root.is_dir():
        raise Failure(INPUT_MISSING, f"Work directory not found: {root}", "Name the directory work start wrote, or its work.json.")
    if not ledger.regular(root / "work.json"):
        raise Failure(INPUT_MISSING, f"No work.json in {root}", "Run: pat work start <workspace> ... --output <this directory>")
    return root


def read_order(root: Path) -> dict:
    return validate_order(_read(root / "work.json", "work.json"))


def _rows(root: Path, name: str, key: str) -> list:
    data = _read(root / name, name)
    if data is None:
        return []
    rows = data.get(key)
    if not isinstance(rows, list):
        raise Failure(INPUT_INVALID, f"{name} has no {key} list", field="/" + key)
    return rows


def _write_rows(root: Path, name: str, key: str, rows: list, limit: int, what: str) -> None:
    if len(rows) > limit:
        raise Failure(INPUT_LIMIT, f"More than {limit} {what} in {name}; start a new piece of work")
    text = json.dumps({"schema": 1, key: rows}, indent=2, ensure_ascii=False) + "\n"
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise Failure(INPUT_LIMIT, f"{name} would exceed {MAX_BYTES} bytes")
    ledger.write_ledger(root / name, text)


# ----- routes --------------------------------------------------------------------------

def start(args, job: Job) -> dict:
    """The order, written once into the new output directory the job owns."""
    workspace = Path(args.workspace)
    if not workspace.is_dir():
        raise Failure(INPUT_MISSING, f"Workspace directory not found: {workspace}")
    donor = {"kind": args.donor_kind or "none", "ref": args.donor}
    if args.donor and not args.donor_kind:
        donor["kind"] = "path"
    order = validate_order({"schema": ORDER_SCHEMA, "id": uuid.uuid4().hex[:16], "title": args.title, "want": args.want,
                            "target": args.target, "door": "shelf" if args.subject else "form", "donor": donor,
                            "subject": args.subject, "by": args.by, "created": now()})
    if order["subject"] is not None and not (workspace / order["subject"]).exists():
        raise Failure(INPUT_MISSING, f"The subject is not in the workspace: {order['subject']}",
                      "The shelf door starts from a module or composition directory that exists.")
    path = job.root / "work.json"
    path.write_text(json.dumps(order, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"work": str(job.root), "order": order, "records": {"spine": "spine.json", "decisions": "decisions.json"},
            "next": f"pat work step {job.root} --step placement --outcome started --json",
            "verification": "An order is what was asked, recorded; it proves nothing was built."}


def step(args) -> dict:
    root = _directory(args.work)
    read_order(root)
    row = {"step": args.step, "outcome": args.outcome, "at": now(), "note": args.note, "receipt": None}
    if args.receipt:
        receipt = Path(args.receipt)
        workspace = Path(args.workspace) if args.workspace else None
        actual = receipt if receipt.is_absolute() else (workspace / receipt if workspace else root / receipt)
        if not ledger.regular(actual):
            raise Failure(INPUT_MISSING, f"Receipt not found: {actual}",
                          "A spine row cites a receipt that exists; a step with no receipt is recorded with none.")
        rel = receipt.as_posix() if not receipt.is_absolute() else (
            receipt.relative_to(workspace).as_posix() if workspace and receipt.is_relative_to(workspace) else None)
        if rel is None:
            raise Failure(INPUT_INVALID, "An absolute receipt path needs --workspace so the row can cite it relatively",
                          "Pass the workspace root, or cite the receipt relative to it.")
        row["receipt"] = {"path": rel, "sha256": sha256_file(actual)}
    with ledger.lock(root / "spine.json"):
        rows = _rows(root, "spine.json", "rows")
        rows = [validate_step(r, i) for i, r in enumerate(rows)]
        rows.append(validate_step(row, len(rows)))
        _write_rows(root, "spine.json", "rows", rows, MAX_ROWS, "spine rows")
    return {"work": str(root), "index": len(rows) - 1, "row": rows[-1], "rows": len(rows),
            "evidence": "receipted" if rows[-1]["receipt"] else "narrated"}


def ask(args) -> dict:
    root = _directory(args.work)
    read_order(root)
    request_path = Path(args.request)
    if not ledger.regular(request_path):
        raise Failure(INPUT_MISSING, f"Request file not found: {request_path}")
    request = validate_request(_read(request_path, "request"))
    request.update({"id": uuid.uuid4().hex[:16], "asked_at": now(), "answer": None})
    with ledger.lock(root / "decisions.json"):
        rows = _rows(root, "decisions.json", "requests")
        if any(r.get("answer") is None for r in rows):
            pending = [r.get("id") for r in rows if r.get("answer") is None]
            raise Failure(INPUT_INVALID, f"A question is already waiting on the person: {pending}",
                          "One question at a time. Wait for its answer before asking the next.")
        rows.append(request)
        _write_rows(root, "decisions.json", "requests", rows, MAX_DECISIONS, "decision requests")
    return {"work": str(root), "request": request, "pending": 1,
            "wait": f"pat work status {root} --json until requests[{len(rows) - 1}].answer is not null"}


def answer(args) -> dict:
    root = _directory(args.work)
    read_order(root)
    via = _choice(args.by, "--by", ANSWERED_VIA, "/answer/via")
    with ledger.lock(root / "decisions.json"):
        rows = _rows(root, "decisions.json", "requests")
        matches = [i for i, r in enumerate(rows) if r.get("id") == args.request_id]
        if not matches:
            raise Failure(INPUT_MISSING, f"No request with id {args.request_id!r} in {root / 'decisions.json'}")
        index = matches[0]
        request = rows[index]
        if request.get("answer") is not None:
            raise Failure(INPUT_INVALID, f"Request {args.request_id} was already answered ({request['answer']['choice']} via {request['answer']['via']})",
                          "An answer is written once; a changed mind is a new request.")
        keys = [o.get("key") for o in request.get("options", [])]
        if args.choice not in keys:
            raise Failure(INPUT_INVALID, f"choice must be one of {keys}: {args.choice!r}", field="/answer/choice")
        request["answer"] = {"choice": args.choice, "via": via, "at": now(),
                             "note": _text(args.note, "note", MAX_TEXT, "/answer/note", required=False)}
        _write_rows(root, "decisions.json", "requests", rows, MAX_DECISIONS, "decision requests")
    return {"work": str(root), "index": index, "request": request, "pending": sum(1 for r in rows if r.get("answer") is None)}


def _receipt_state(root: Path, workspace: Path | None, cited: dict | None) -> dict:
    """Whether the receipt a row cites is there and still the bytes the row hashed."""
    if cited is None:
        return {"evidence": "narrated", "receipt": None}
    base = workspace if workspace else root
    path = base / cited["path"]
    if not ledger.regular(path):
        return {"evidence": "receipt-missing", "receipt": {**cited, "found": False, "status": None}}
    try:
        current = sha256_file(path)
    except Failure:
        return {"evidence": "receipt-missing", "receipt": {**cited, "found": False, "status": None}}
    status = None
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.stat().st_size <= MAX_BYTES else None
        if isinstance(data, dict):
            status = data.get("status")
    except (OSError, ValueError):
        status = None
    if current != cited["sha256"]:
        return {"evidence": "receipt-drifted", "receipt": {**cited, "found": True, "current_sha256": current, "status": status}}
    return {"evidence": "receipted", "receipt": {**cited, "found": True, "status": status}}


def status(work: str, workspace: str | None = None) -> dict:
    root = _directory(work)
    ws = Path(workspace) if workspace else None
    if ws is not None and not ws.is_dir():
        raise Failure(INPUT_MISSING, f"Workspace directory not found: {ws}")
    order = read_order(root)
    raw_rows = _rows(root, "spine.json", "rows")
    rows = [validate_step(r, i) for i, r in enumerate(raw_rows)]
    spine = [{"index": i, **row, **_receipt_state(root, ws, row["receipt"])} for i, row in enumerate(rows)]
    requests = _rows(root, "decisions.json", "requests")
    pending = [r for r in requests if r.get("answer") is None]
    last = spine[-1] if spine else None
    done = [row["step"] for row in rows if row["outcome"] == "done"]
    next_step = None
    for name in STEPS:
        if name not in done:
            next_step = name
            break
    current = None
    if last is not None and last["outcome"] == "started":
        current = last["step"]
    counts = {kind: sum(1 for row in spine if row["evidence"] == kind) for kind in ("receipted", "narrated", "receipt-missing", "receipt-drifted")}
    return {"protocol": PROTOCOL, "work": str(root), "order": order,
            "waiting_on_person": bool(pending), "pending": pending, "requests": requests,
            "current_step": current, "next_step": next_step, "last": last, "spine": spine, "evidence": counts,
            "verification": "A spine row is a statement an agent wrote; only its receipt, found and unchanged, is the fact. "
                            "Nothing here reads the game, the ledger or a module's six facts."}


def execute(args, job: Job) -> dict:
    """The job entry the CLI dispatches ``work start`` to."""
    return start(args, job)
