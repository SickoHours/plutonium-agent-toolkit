"""``module accept``: a person's verdict, recorded in one module's evidence ledger.

A person plays the pack and says what they found. That is one of the six facts the shelf keeps
separate, and it is the only one no build, no readback and no agent observation can produce. The
other five have routes that write them; this one did not, so a verdict lived in a chat message or
a hand-written note and the ledger stayed silent about the only fact a person can give.

This route writes it where it belongs: one ``player-accepted`` row in the module's
``evidence.json``, scoped to the base, foundation and map the verdict was given on, pinned to the
package hash that was actually installed, citing the record that holds the person's own words.

A pack is a composition of modules, and a verdict on the pack is a verdict about each member on
that target, so the caller runs this once per member. Nothing here reads a composition: the
caller names the module, the scope and the package, and this route records what it was told.

The ledger is append-only. A second verdict is a second row, never an edit of the first; a
verdict that reverses an earlier one is a ``rejected`` row beside it, and the earlier row stays.
The row goes through the same validator ``module state --ledger`` reads before any of it reaches
disk, so a refusal leaves the file byte for byte as it was.

Nothing here touches a game, a network or a build. The route records a verdict; it does not form
one, and it never infers a verdict from a build, a run or a capture.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..core.errors import INPUT_INVALID, INPUT_MISSING, Failure
from ..core.jobs import Job
from . import compositions, ledger

PROTOCOL = "pat.module-accept/1"
OUTCOMES = ledger.OUTCOMES["player-accepted"]


def add_parser(actions, common):
    q = actions.add_parser("accept", help="Append one person's verdict to a module's evidence.json as a player-accepted row")
    q.add_argument("module", help="Module directory holding module.json; the ledger is written beside it")
    q.add_argument("--outcome", required=True, metavar="OUTCOME",
                   help=f"The person's verdict: {' or '.join(OUTCOMES)}")
    q.add_argument("--base", required=True, help="Base token the verdict was given on (the scope's base)")
    q.add_argument("--foundation", required=True, help="Foundation id as foundations/<id>.json names it")
    q.add_argument("--map", dest="map_id", required=True, metavar="MAP", help="The one map the verdict covers")
    q.add_argument("--package", required=True, metavar="SHA256",
                   help="The mod.ff that was installed when the person played it (64 hex)")
    q.add_argument("--record", required=True, metavar="PATH",
                   help="Workspace-relative path of the record holding the verdict; never climbs out of the workspace")
    q.add_argument("--record-sha256", metavar="HEX", help="That record's SHA-256 when it was cited, so drift is visible")
    q.add_argument("--reporter", help="Who gave the verdict")
    q.add_argument("--quote", help="The person's own words, verbatim")
    q.add_argument("--not-covered", action="append", default=[], metavar="TEXT",
                   help="Something this verdict does not cover (co-op, other maps, measured performance); repeatable")
    q.add_argument("--note", help="What the verdict covered and did not, in the recorder's words")
    q.add_argument("--at", help="When the verdict was given: YYYY-MM-DD or an ISO date-time")
    q.add_argument("--workspace", help="Workspace root the --record path is relative to; used to report whether it resolves")
    common(q)


def subject_id(directory: Path) -> str:
    """The module id from the declaration beside the ledger.

    Read, never recorded as an input of this job: the route writes a file in this directory, and
    the declaration is the one file that says which module the ledger is about.
    """
    declaration = directory / "module.json"
    if declaration.is_symlink() or not declaration.is_file():
        raise Failure(INPUT_MISSING, f"Module directory has no module.json: {directory}",
                      "A ledger is written beside the declaration it is about.")
    metadata = compositions.validate_declaration_metadata(json.loads(compositions._read_inspection(declaration)))
    return metadata["id"]


def build_row(args) -> dict:
    """The row exactly as given. Every value is the caller's; nothing is derived or inferred."""
    if args.outcome not in OUTCOMES:
        raise Failure(INPUT_INVALID, f"--outcome is one of {list(OUTCOMES)}: {args.outcome!r}",
                      "A person's verdict is accepted or rejected; a qualification belongs in --note or --not-covered.",
                      field="/outcome")
    record = {"path": args.record}
    if args.record_sha256:
        record["sha256"] = args.record_sha256
    row = {"type": "player-accepted", "outcome": args.outcome,
           "scope": {"base": args.base, "foundation": args.foundation, "maps": [args.map_id]},
           "record": record, "package_sha256": args.package}
    for key, value in (("at", args.at), ("reporter", args.reporter), ("quote", args.quote), ("note", args.note)):
        if value:
            row[key] = value
    if args.not_covered:
        row["not_covered"] = list(args.not_covered)
    return row


def resolves(args) -> bool | None:
    """Whether the cited record is a file in the workspace the caller named. ``None`` when no
    workspace was given: a citation this route cannot resolve is not a citation it doubts."""
    if not args.workspace:
        return None
    try:
        candidate = Path(args.workspace).expanduser() / ledger._relative(args.record, "record", "/record/path")
    except Failure:
        return False
    return candidate.is_file() and not candidate.is_symlink()


def execute(args, job: Job) -> dict:
    directory = Path(args.module).expanduser()
    if not directory.is_dir():
        raise Failure(INPUT_MISSING, f"Module directory is missing: {directory}")
    job.check_deadline()
    module_id = subject_id(directory)
    row = build_row(args)
    path = directory / ledger.FILENAME
    # Validated whole, then written once: a row the ledger refuses never reaches the file, and the
    # file the route refuses to write is the file it read. The lock is held across the read and
    # the write, so a second verdict recorded at the same moment waits and appends to the row this
    # one wrote instead of replacing it; the write is a temporary file, an fsync and a rename, so
    # a failure leaves the verdicts already there.
    with ledger.lock(path):
        created = not ledger.regular(path)
        text, rows = ledger.append_row(path, row, module_id)
        job.check_deadline()
        ledger.write_ledger(path, text)
    written, _ = ledger.validate(json.loads(text))
    return {"protocol": PROTOCOL, "module": module_id, "directory": str(directory), "ledger": str(path),
            "created": created, "rows": rows, "row": written["rows"][-1], "record_found": resolves(args),
            "facts": {"player_accepted": args.outcome == "accepted"},
            "note": "A person's verdict on this module in this scope. It says nothing about any other "
                    "scope, and nothing about whether the module was installed, launched or captured."}
