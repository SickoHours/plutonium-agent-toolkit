"""``module qualify``: build one module alone on one target, then write its records from the receipts.

A declaration's ``bases`` and ``maps`` grow only by a build on that target. Doing that by hand is
four commands per module plus four files edited from their output, and a lane that ran it 140
times wrote the loop as a script twice. This route is that loop with receipts, and the widening
is earned inside it: nothing is written to the module until every step has succeeded, and a step
that fails leaves the job directory holding the refusal and the module untouched.

One job directory, one sub-receipt per step:

===========================  ==========================================================
``<id>/shelf/``              the module and its declared dependency closure, staged
``<id>/pack/``               the one-member composition synthesized for the target
``<id>/plan-unqualified/``   ``module plan --allow-unqualified``
``<id>/build-unqualified/``  ``module build --allow-unqualified``
``<id>/verify-unqualified/`` ``project verify --inputs``
``<id>/plan-qualified/``     ``module plan`` after the staged declaration is widened
``<id>/build-qualified/``    ``module build``; its package must be the same bytes
``<id>/verify-qualified/``   ``project verify --inputs``
``<id>/qualify.json``        the module's own row: steps, hashes, refusals, records
===========================  ==========================================================

The declaration is widened in the **staged copy**, never in the module, so both builds read the
same paths and the identity of their two packages means what it says: the declaration is metadata
the package does not contain, and a build that was blind to it produced the same bytes as the one
that trusted it. Only after the second verify are the four records written where they belong.

An adapter recipe is a cut for one foundation and one map (``docs/MODULES.md``), so widening
alone cannot qualify one: the route writes the target's cut as ``recipe-<base>.json`` from the
declared recipe with only ``foundation``, ``map``, ``profile`` and ``revision`` changed, builds
*that*, and records it under the declaration's ``recipes`` map. Its two packages are not expected
to be the same bytes (the profile name is inside the cut), so their hashes are both recorded and
neither is asserted against the other.

Nothing here touches a game, a network or a running process. Nothing is installed. A qualified
module is offline verified on that target and nothing more.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

from ..core.envelope import now
from ..core.errors import INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING, Failure
from ..core.jobs import Job
from ..core.receipts import sha256_file
from . import compositions, ledger, projects, targets

PROTOCOL = "pat.module-qualify/1"
MAX_SET = 512
MAX_TREE_FILES = 20000
MAX_LOADS = 16
MAX_HEADER = 64
MAX_JSON = 16 * 1024 * 1024
TEST_RECORD = "docs/TEST.md"
BINDINGS = "registry/module-recipes.json"

# Why a module was not qualified. The first three are the plan's own patterns (``adapt``); the
# rest are what only a build can tell, typed from the receipts the lanes read by hand.
REFUSAL_KINDS = ("target-unstaged", "shelf-missing", "missing-dependency", "dependency-unqualified",
                 "adapter-recipe-single-target-without-recipes", "probe", "map-scripts", "missing-fx",
                 "plan-refused", "build-failed", "verify-failed", "package-mismatch", "records-refused")
# The linker names a root it cannot resolve; an effect the target's zones do not carry is the one
# the lanes met (``ERROR: Missing asset "..." of type "fx"``).
MISSING_ASSET = 'ERROR: Missing asset "'


def add_parser(actions, common):
    q = actions.add_parser("qualify", help="Build one module alone on one target and write its declaration widening, "
                                           "test record, ledger row and workspace binding from the receipts")
    q.add_argument("module", nargs="?", help="Module directory holding module.json; omit with --set")
    q.add_argument("--set", dest="module_set", metavar="FILE",
                   help="A file of module directories, one per line (# comments allowed); run in dependency order, one job directory each")
    q.add_argument("--target", required=True, metavar="KEY",
                   help="<foundation>/<map>: the foundation id as foundations/<id>.json names it, and one map it stages")
    q.add_argument("--workspace", required=True, help="Workspace root holding foundations/, modules/ and registry/")
    q.add_argument("--member-root", action="append", default=[], metavar="DIR",
                   help="Directory of module directories to resolve dependencies from; repeatable (default: <workspace>/modules)")
    common(q)


# ----- the target ---------------------------------------------------------------------------

def parse_target(text: str) -> tuple[str, str]:
    """``<foundation>/<map>`` as ``docs/target-sets.md`` writes it, without the mode and location
    a placements target carries: qualification is per map, not per fenced area."""
    if not isinstance(text, str) or text.count("/") != 1:
        raise Failure(INPUT_INVALID, f"--target is <foundation>/<map>, for example dlc5-beta2/zm_factory: {text!r}",
                      "The foundation id is the one foundations/<id>.json names, never the base token.")
    foundation, map_id = text.split("/")
    if not targets.FOUNDATION.match(foundation) or not targets.MAP.match(map_id):
        raise Failure(INPUT_INVALID, f"--target is <foundation>/<map>, for example dlc5-beta2/zm_factory: {text!r}")
    return foundation, map_id


def read_json(path: Path, job: Job, limit: int = MAX_JSON) -> dict:
    source = job.input(path, limit=limit)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (ValueError, OSError, RecursionError) as exc:
        raise Failure(INPUT_INVALID, f"Not readable as JSON: {source}") from exc
    if not isinstance(value, dict):
        raise Failure(INPUT_INVALID, f"Expected a JSON object: {source}")
    return value


def target_inputs(workspace: Path, foundation: str, map_id: str, job: Job) -> dict:
    """The base token, link loads and zone header a composition on this target needs, read from
    the workspace's own ``foundations/<id>.json`` (and the local descriptor it points at, which is
    where a workspace keeps the staged copies). A foundation the workspace does not stage, or a
    map it does not stage on that foundation, is refused before anything is built."""
    staged = targets.foundations(workspace)
    if foundation not in staged:
        raise Failure(INPUT_MISSING, f"This workspace stages no foundation {foundation!r} (it has: {sorted(staged) or 'none'})",
                      "A target names a foundation the workspace declares in foundations/<id>.json.")
    if map_id not in staged[foundation]["maps"]:
        raise Failure(INPUT_MISSING, f"Foundation {foundation} does not stage {map_id} (it stages: {staged[foundation]['maps']})",
                      "Qualification builds against the zones the foundation stages for that map; stage the map first.")
    base = staged[foundation]["base"]
    if not base or not compositions.BASE.match(base):
        raise Failure(INPUT_INVALID, f"Foundation {foundation} declares no profile_prefix to use as the base token",
                      "The base token is the inverse of the foundation lookup; foundations/<id>.json carries it as profile_prefix.")
    path = workspace / "foundations" / staged[foundation]["file"]
    record = read_json(path, job)
    descriptor_path, descriptor = path, record
    if isinstance(record.get("private_descriptor"), str):
        descriptor_path = path.parent / record["private_descriptor"]
        descriptor = read_json(descriptor_path, job)
    link_loads = descriptor.get("link_loads", {})
    if not isinstance(link_loads, dict) or not isinstance(link_loads.get(map_id), list):
        raise Failure(INPUT_MISSING, f"The foundation record has no staged link loads for {map_id}",
                      "link_loads maps a map id to the base fastfiles a module links against on it.")
    loads = link_loads[map_id]
    if len(loads) > MAX_LOADS or any(not isinstance(v, str) or not v for v in loads):
        raise Failure(INPUT_INVALID, f"Foundation link loads for {map_id} are at most {MAX_LOADS} paths")
    maps = record.get("maps", {})
    per_map = maps.get(map_id, {}) if isinstance(maps, dict) else {}
    header = per_map.get("mod_zone_header") if isinstance(per_map, dict) else None
    if not isinstance(header, list):
        header = record.get("mod_zone_header", descriptor.get("mod_zone_header", []))
    if not isinstance(header, list) or len(header) > MAX_HEADER or any(not isinstance(line, str) for line in header):
        raise Failure(INPUT_INVALID, f"Foundation mod_zone_header is a list of at most {MAX_HEADER} strings")
    # A descriptor may carry another map's ipak line; this build is for one map.
    header = [f">level.ipak_read,{map_id}" if line.startswith(">level.ipak_read,zm_") else line for line in header]
    resolved = []
    for value in loads:
        load = (descriptor_path.parent / value).resolve()
        if load.is_symlink() or not load.is_file():
            raise Failure(INPUT_MISSING, f"A link load this foundation stages for {map_id} is missing: {load}")
        resolved.append(load)
    return {"foundation": foundation, "map": map_id, "base": base, "loads": resolved, "zone_header": header,
            "foundation_file": path, "descriptor": descriptor_path}


# ----- the shelf ----------------------------------------------------------------------------

def shelf(roots: list[Path], job: Job) -> dict[str, tuple[Path, dict]]:
    """Every declaration under the member roots, by id. Ordered roots win in order, the way
    ``module compose`` resolves them; nothing is read but ``module.json``."""
    index: dict[str, tuple[Path, dict]] = {}
    for root in roots:
        if not root.is_dir():
            raise Failure(INPUT_MISSING, f"Member root is missing: {root}")
        children = sorted(root.iterdir())
        if len(children) > 4096:
            raise Failure(INPUT_LIMIT, f"Member root exceeds 4096 entries: {root}")
        for child in children:
            job.check_deadline()
            declaration = child / "module.json"
            if child.is_symlink() or not child.is_dir() or declaration.is_symlink() or not declaration.is_file():
                continue
            try:
                data = json.loads(compositions._read_inspection(declaration))
                metadata = compositions.validate_declaration_metadata(data)
            except (Failure, ValueError, RecursionError):
                continue  # A shelf holds work in progress; a defective neighbour is not this module's refusal.
            index.setdefault(metadata["id"], (child, metadata))
    return index


def closure(mid: str, index: dict[str, tuple[Path, dict]]) -> tuple[list[str], list[str]]:
    """The module and everything it declares a dependency on, plus the ids the shelf does not
    hold. Order is not the build order; the planner derives that."""
    members, missing, stack = {mid}, [], list(index[mid][1]["dependencies"])
    while stack:
        dep = stack.pop()
        if dep in members:
            continue
        if dep not in index:
            if dep not in missing:
                missing.append(dep)
            continue
        members.add(dep)
        stack.extend(index[dep][1]["dependencies"])
    return sorted(members), sorted(missing)


def declared_for(metadata: dict, base: str, map_id: str) -> bool:
    return base in metadata["bases"] and ("*" in metadata["maps"] or map_id in metadata["maps"])


def order_set(ids: list[str], index: dict[str, tuple[Path, dict]]) -> list[str]:
    """The requested modules in dependency order: a module after every member of the set it
    depends on. A dependency outside the set does not move anything."""
    wanted, out, seen = list(dict.fromkeys(ids)), [], set()

    def visit(mid, path=()):
        if mid in seen or mid in path or mid not in index:
            return
        for dep in index[mid][1]["dependencies"]:
            if dep in wanted:
                visit(dep, path + (mid,))
        seen.add(mid)
        out.append(mid)

    for mid in wanted:
        visit(mid)
    return [mid for mid in out if mid in wanted]


# ----- staging ------------------------------------------------------------------------------

def _link_or_copy(source: str, destination: str) -> None:
    try:
        os.link(source, destination)
    except (OSError, NotImplementedError):
        shutil.copy2(source, destination)


def stage(source: Path, destination: Path) -> int:
    """One module directory as a working copy. Files are hard links where the filesystem allows
    it, so staging a hundred-megabyte donor tree costs nothing; every file this route rewrites is
    unlinked first (``replace``) so the original inode is never touched."""
    count = 0
    for directory, dirs, files in os.walk(source, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(directory, d)))
        count += len(files)
        if count > MAX_TREE_FILES:
            raise Failure(INPUT_LIMIT, f"Module directory exceeds {MAX_TREE_FILES} files: {source}")
        target = destination / Path(directory).relative_to(source)
        target.mkdir(parents=True, exist_ok=True)
        for name in sorted(files):
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file():
                continue
            _link_or_copy(str(path), str(target / name))
    return count


def replace(path: Path, data: str) -> None:
    """Write a staged file without writing through a hard link into the real module."""
    if path.exists() or path.is_symlink():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def serialise(data, raw: str | None = None) -> str:
    """JSON the way the file already writes it, so a record is an addition and not a reformat:
    the ledger and the registry differ on ``ensure_ascii`` across this shelf and a diff that
    re-escapes every accent hides the row that was added."""
    if raw is not None and json.dumps(data, indent=2) + "\n" != raw:
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return json.dumps(data, indent=2) + "\n"


# ----- one step -----------------------------------------------------------------------------

def sub_job(parent: Job, path: Path, command: str, argv: list[str]) -> Job:
    child = Job(path, command, argv, timeout=600)
    child.deadline = parent.deadline
    return child


def run_step(parent: Job, path: Path, command: str, argv: list[str], call) -> tuple[dict | None, Failure | None, Job]:
    """One sub-receipt. A failure is returned, not raised: the route reports every step it ran."""
    parent.check_deadline()
    child = sub_job(parent, path, command, argv)
    try:
        result = call(child)
    except Failure as exc:
        child.fail(exc)
        return None, exc, child
    child.finish(result)
    return result, None, child


def composition_args(args, composition: Path, action: str, allow_unqualified: bool, output: Path):
    """``module plan``/``module build`` arguments for one synthesized composition. ``--target`` is
    this route's ``<foundation>/<map>``, which is not the placements target list the planner takes."""
    return SimpleNamespace(action=action, composition=str(composition), allow_unqualified=allow_unqualified,
                           workspace=args.workspace, target=[], image_report=None,
                           timeout=args.timeout, output=str(output), json=True)


def plan_refusal(exc: Failure) -> dict:
    """The typed refusal a plan failure becomes. A failed ``map-scripts`` row is the pattern the
    lanes met three times: a replaced function lives in a script the target map does not carry."""
    refusals = exc.details.get("refusals") or []
    failed = [c for c in (exc.details.get("checks") or []) if c.get("outcome") == "failed"]
    scripts = [c for c in failed if str(c.get("id", "")).startswith("map-scripts:")]
    if scripts:
        return {"kind": "map-scripts", "message": "; ".join(f"{c['id']}: {c['detail']}" for c in scripts)[:1200],
                "hint": "The target map does not carry the script this module replaces into; that is a port, not a widening.",
                "missing": sorted({p for c in scripts for p in (c.get("missing") or [])})[:32],
                "error_code": exc.code}
    if any(r.get("kind") == "probe" for r in refusals):
        row = next(r for r in refusals if r.get("kind") == "probe")
        return {"kind": "probe", "message": row.get("message", exc.message)[:1200],
                "hint": "This module's test contract asks for the probe, and the probe on this shelf does not declare the target.",
                "error_code": exc.code}
    return {"kind": "plan-refused", "message": exc.message[:1200], "hint": exc.hint,
            "error_code": exc.code, "refusals": [{k: r.get(k) for k in ("kind", "modules", "message")} for r in refusals][:32]}


def build_refusal(exc: Failure, job: Job) -> dict:
    """The typed refusal a build failure becomes. The linker's own log is the only place a root
    the target's zones do not carry is named, so it is read here and the asset is quoted."""
    missing = []
    if job.root.is_dir():
        for log in sorted(job.root.glob("step-*.log")):
            try:
                text = log.read_text(encoding="utf-8", errors="replace")[-256 * 1024:]
            except OSError:
                continue
            for line in text.splitlines():
                if MISSING_ASSET in line:
                    name = line.split(MISSING_ASSET, 1)[1]
                    if name not in missing:
                        missing.append(name.rstrip())
    effects = [m for m in missing if m.endswith('of type "fx"')]
    if effects:
        return {"kind": "missing-fx", "message": "The target's zones do not carry: " + "; ".join(effects)[:1200],
                "hint": "An effect the donor map carried is not on this target; the module has to ship its own effect closure.",
                "missing": effects[:32], "error_code": exc.code}
    return {"kind": "build-failed", "message": exc.message[:1200], "hint": exc.hint, "error_code": exc.code,
            "missing": missing[:32]}


# ----- the records ---------------------------------------------------------------------------

def relative_to(path: Path, root: Path) -> str:
    """A receipt path as the workspace's own records cite it. A job directory outside the
    workspace keeps its absolute path; nothing is invented to make it look relative."""
    try:
        return Path(os.path.relpath(path, root)).as_posix()
    except ValueError:
        return str(path)


def widen(raw: str, base: str, map_id: str, recipes: tuple[str, str] | None) -> tuple[str, dict]:
    """``bases`` and ``maps`` grown by exactly this target, and an adapter's per-target recipe
    recorded under ``recipes``. Nothing else in the declaration moves."""
    data = json.loads(raw)
    changed = {"base": False, "map": False, "recipe": False}
    if base not in data["bases"]:
        data["bases"].append(base)
        changed["base"] = True
    if map_id not in data["maps"] and "*" not in data["maps"]:
        data["maps"].append(map_id)
        changed["map"] = True
    if recipes is not None:
        key, value = recipes
        if data.setdefault("recipes", {}).get(key) != value:
            data["recipes"][key] = value
            changed["recipe"] = True
    return serialise(data, raw), changed


def test_section(row: dict, number: int) -> str:
    """The ``docs/TEST.md`` section for this build: every receipt this route wrote, by path and
    sha256, and the six facts kept apart."""
    steps = row["steps"]
    lines = [
        "",
        f"## Build {number:02d} — {row['foundation']} / {row['map']} qualification — {row['at'][:10]} UTC",
        "",
        f"Candidate: `{row['id']}` v{row['version']}, foundation `{row['foundation']}`, base token `{row['base']}`, map `{row['map']}`;"
        f" composition `{row['composition']}` (this module plus its declared dependency closure from this shelf), built alone by"
        f" `pat module qualify` ({PROTOCOL}). The declaration was widened in a staged copy and written here only after every step succeeded.",
        "",
    ]
    if row["payload"] == "adapter":
        lines.append(f"- Adapter cut for this target: `{row['records']['recipe']}` (sha256 `{row['records']['recipe_sha256']}`),"
                     f" written from the declared recipe with only `foundation`, `map`, `profile` and `revision` changed,"
                     f" and recorded as `recipes[\"{row['foundation']}/{row['map']}\"]`."
                     f" `mod.ff` sha256 `{steps['build-qualified']['package_sha256']}`;"
                     f" the declaration-blind build of the default cut on this target produced"
                     f" `{steps['build-unqualified']['package_sha256']}` (a per-target cut names its own profile, so the two are not the same bytes).")
    else:
        lines.append(f"- `mod.ff` sha256 `{steps['build-qualified']['package_sha256']}`; the declaration-blind build produced the same bytes"
                     f" (`{steps['build-unqualified']['package_sha256']}`).")
    lines.append(f"- Declaration sha256 after widening `bases` by `{row['base']}` and `maps` by `{row['map']}`: `{row['records']['declaration_sha256']}`.")
    for label, keys in (("Pre-declaration attempt (`--allow-unqualified`; this module was reported unqualified for the target)",
                         ("plan-unqualified", "build-unqualified", "verify-unqualified")),
                        ("Qualified receipts (`result.unqualified` empty)",
                         ("plan-qualified", "build-qualified", "verify-qualified"))):
        cited = [f"{key.split('-')[0]} `{steps[key]['receipt']}` (`{steps[key]['receipt_sha256']}`)" for key in keys if key in steps]
        if cited:
            lines.append(f"- {label}: " + ", ".join(cited) + ".")
    build = steps.get("build-qualified", {})
    lines.append(f"- Readback: {build.get('rawfiles_verified')} rawfile(s) compiled, linked and read back byte for byte;"
                 f" {build.get('embedded_assets')} embedded and {build.get('referenced_assets')} referenced assets;"
                 f" `pat project verify --inputs` found inputs and outputs unchanged.")
    lines.append("- Six facts: offline verified (compile, link, readback, declaration validation) **yes**; installed **no**; launched **no**;"
                 " loaded/playable **no**; captured **no**; player accepted **no**. Nothing here says the feature behaves on this map.")
    lines.append("")
    return "\n".join(lines)


def ledger_row(row: dict) -> dict:
    build = row["steps"]["build-qualified"]
    return {"type": "built-alone",
            "scope": {"base": row["base"], "foundation": row["foundation"], "maps": [row["map"]]},
            "at": row["at"],
            "receipt": {"path": build["receipt"], "sha256": build["receipt_sha256"]},
            "package_sha256": build["package_sha256"],
            "offline_verified": True,
            "note": f"pat module qualify ({PROTOCOL}): the module alone with its declared dependency closure, built on "
                    f"{row['base']}/{row['map']}, status succeeded; {build.get('rawfiles_verified')} rawfile(s) read back, "
                    f"{build.get('embedded_assets')} embedded and {build.get('referenced_assets')} referenced assets; "
                    f"pat project verify --inputs unchanged. The declaration was widened to this base and map by this receipt. "
                    f"Offline only: not installed, not launched, not played."}


def binding_row(row: dict) -> dict:
    build = row["steps"]["build-qualified"]
    return {"id": f"{row['base']}-{row['map']}-qualify-01", "modules": [row["id"]], "sha256": build["package_sha256"],
            "foundation": row["foundation"], "map": row["map"], "offline_verified": True, "installed": False,
            "runtime_verified": False, "player_accepted": False, "receipt": build["receipt"]}


def write_records(row: dict, directory: Path, workspace: Path, staged: Path) -> dict:
    """The four records, written together or not at all. Every file's previous bytes are held
    until the last one is on disk; a failure anywhere puts every one of them back."""
    written: list[tuple[Path, bytes | None]] = []
    notes: list[str] = []

    def put(path: Path, text: str) -> None:
        written.append((path, path.read_bytes() if path.is_file() and not path.is_symlink() else None))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    try:
        declaration = directory / "module.json"
        raw = declaration.read_text(encoding="utf-8")
        recipes = (f"{row['foundation']}/{row['map']}", row["records"]["recipe"]) if row["payload"] == "adapter" else None
        if row["payload"] == "adapter":
            cut = directory / row["records"]["recipe"]
            if not cut.is_file():
                put(cut, (staged / row["records"]["recipe"]).read_text(encoding="utf-8"))
        text, changed = widen(raw, row["base"], row["map"], recipes)
        put(declaration, text)
        row["records"]["widened"] = changed
        row["records"]["declaration_sha256"] = sha256_file(declaration)

        test = directory / TEST_RECORD
        previous = test.read_text(encoding="utf-8") if test.is_file() else f"# {row['id']} test record\n"
        number = 1 + sum(1 for line in previous.splitlines() if line.startswith("## Build "))
        put(test, previous.rstrip("\n") + "\n" + test_section(row, number))
        row["records"]["test_build"] = number

        path = directory / ledger.FILENAME
        book = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"schema": 1, "subject": {"id": row["id"]}, "rows": []}
        book.setdefault("rows", []).append(ledger_row(row))
        normalized, diagnostics = ledger.validate(book)
        if normalized is None or diagnostics:
            raise Failure(INPUT_INVALID, f"The built-alone row does not validate against {ledger.PROTOCOL}: {diagnostics[:4]}",
                          "The ledger row is written through the same validator module state --ledger reads.")
        put(path, serialise(book, path.read_text(encoding="utf-8") if path.is_file() else None))
        row["records"]["ledger_rows"] = len(normalized["rows"])

        bindings = workspace / BINDINGS
        if bindings.is_file():
            raw_bindings = bindings.read_text(encoding="utf-8")
            data = json.loads(raw_bindings)
            entry = next((e for e in data.get("recipes", []) if e.get("id") in (row["id"], directory.name)), None)
            if entry is None:
                notes.append(f"{BINDINGS} has no entry for {row['id']}; the build row was not written")
            else:
                entry.setdefault("builds", []).append(binding_row(row))
                put(bindings, serialise(data, raw_bindings))
                row["records"]["binding"] = entry["id"]
        else:
            notes.append(f"{BINDINGS} is not in this workspace; the build row was not written")
    except Exception:
        for path, before in reversed(written):
            if before is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(before)
        raise
    row["records"]["files"] = [relative_to(path, workspace) for path, _ in written]
    row["records"]["notes"] = notes
    return row["records"]


# ----- one module ----------------------------------------------------------------------------

def refuse(row: dict, kind: str, message: str, hint: str = "", **extra) -> dict:
    row["refusals"].append({"kind": kind, "module": row["id"], "message": message, "hint": hint, **extra})
    row["outcome"] = "refused"
    return row


def qualify_one(directory: Path, index: dict[str, tuple[Path, dict]], info: dict, args, job: Job, workspace: Path) -> dict:
    metadata = index_entry(directory, index, job)
    mid = metadata["id"]
    base, map_id, foundation = info["base"], info["map"], info["foundation"]
    home = job.root / mid
    # A declaration says ``recipe``; only the recipe itself says whether it is a project recipe the
    # toolkit compiles or a donor cut a workspace builder makes for one target.
    cut = adapter_cut(directory, metadata)
    payload = "adapter" if cut is not None else metadata["payload"]
    row = {"id": mid, "directory": str(directory), "version": metadata["version"], "payload": payload,
           "target": f"{foundation}/{map_id}", "foundation": foundation, "map": map_id, "base": base,
           "at": now(), "outcome": "refused", "steps": {}, "refusals": [], "records": {},
           "already_declared": declared_for(metadata, base, map_id), "recipe_cut": list(cut) if cut else None,
           "job": relative_to(home, workspace)}

    members, missing = closure(mid, index)
    row["closure"] = members
    if missing:
        return finish(refuse(row, "missing-dependency", f"{mid} depends on {missing}, which this shelf does not hold",
                             "Add the module directory that declares that id to a --member-root.", modules=missing), home)
    for dep in [m for m in members if m != mid]:
        dep_dir, dep_meta = index[dep]
        if not declared_for(dep_meta, base, map_id):
            refuse(row, "dependency-unqualified",
                   f"{mid} depends on {dep}, which is declared for bases {dep_meta['bases']} and maps {dep_meta['maps']}, not for {base}/{map_id}",
                   f"Qualify it first: pat module qualify {dep_dir} --target {foundation}/{map_id}", modules=[dep])
        if dep_meta["payload"] == "recipe" and f"{foundation}/{map_id}" not in dep_meta["recipes"]:
            dep_cut = adapter_cut(dep_dir, dep_meta)
            if dep_cut is not None and dep_cut != (foundation, map_id):
                refuse(row, "adapter-recipe-single-target-without-recipes",
                       f"{mid} depends on {dep}, whose recipe is the {dep_cut[0]}/{dep_cut[1]} cut and whose recipes names no entry for {foundation}/{map_id}",
                       f"Qualify it first: pat module qualify {dep_dir} --target {foundation}/{map_id}", modules=[dep])
    if row["refusals"]:
        return finish(row, home)

    # (a) the one-member composition, with the closure staged beside it so both builds read one
    # shelf and the widening in the copy is the only difference between them.
    staged_root = home / "shelf"
    for member in members:
        stage(index[member][0], staged_root / index[member][0].name)
    probe = probe_directory(index, members)
    if probe is not None:
        # ``prepare_probe`` looks for a sibling directory named ``test_probe``; staging it under
        # that name leaves exactly one candidate, so a contract that asks for the probe is
        # answered by this shelf's probe or refused for what it declares, never for being absent.
        stage(probe, staged_root / "test_probe")
    pack = home / "pack"
    pack.mkdir(parents=True, exist_ok=True)
    composition = pack / "composition.json"
    composition.write_text(json.dumps(
        {"schema": 1, "name": f"{base}_{mid}_test", "base": base, "map": map_id,
         "modules": [relative_to(staged_root / index[m][0].name, pack) for m in members],
         "loads": [relative_to(load, pack) for load in info["loads"]],
         "zone_header": info["zone_header"]}, indent=2) + "\n", encoding="utf-8")
    row["composition"] = relative_to(composition, workspace)
    staged = staged_root / directory.name

    for phase, allow in (("unqualified", True), ("qualified", False)):
        if phase == "qualified" and not prepare_qualified(row, staged, index, info, job):
            return finish(row, home)
        planned, exc, child = run_step(job, home / f"plan-{phase}", "module plan",
                                       ["pat", "module", "plan", str(composition)],
                                       lambda c, a=allow: compositions.execute(composition_args(args, composition, "plan", a, c.root), c))
        record_step(row, f"plan-{phase}", child, planned, exc, workspace)
        if exc is not None:
            return finish(refuse(row, **plan_refusal(exc)), home)
        built, exc, child = run_step(job, home / f"build-{phase}", "module build",
                                     ["pat", "module", "build", str(composition)],
                                     lambda c, a=allow: compositions.execute(composition_args(args, composition, "build", a, c.root), c))
        record_step(row, f"build-{phase}", child, built, exc, workspace)
        if exc is not None:
            return finish(refuse(row, **build_refusal(exc, child)), home)
        if phase == "qualified" and built["unqualified"]:
            return finish(refuse(row, "plan-refused",
                                            f"The qualified build still reports {built['unqualified']} unqualified",
                                            "The widening did not cover this target; nothing was written."))
        verified, exc, child = run_step(job, home / f"verify-{phase}", "project verify",
                                        ["pat", "project", "verify", str(child.root / "receipt.json"), "--inputs"],
                                        lambda c, r=child.root: projects.execute(
                                            SimpleNamespace(action="verify", receipt=str(r / "receipt.json"), inputs=True,
                                                            timeout=args.timeout, output=str(c.root), json=True), c))
        record_step(row, f"verify-{phase}", child, verified, exc, workspace)
        if exc is not None:
            return finish(refuse(row, "verify-failed", exc.message[:1200], exc.hint, error_code=exc.code), home)

    blind = row["steps"]["build-unqualified"]["package_sha256"]
    earned = row["steps"]["build-qualified"]["package_sha256"]
    row["package_identical"] = blind == earned
    if row["payload"] != "adapter" and not row["package_identical"]:
        return finish(refuse(row, "package-mismatch",
                                        f"The declaration-blind build produced {blind} and the qualified build {earned}",
                                        "A declaration is metadata the package does not contain; two different packages mean an input moved between the builds."))

    # (f) the records, together or not at all.
    try:
        write_records(row, directory, workspace, staged)
    except (Failure, OSError, ValueError, KeyError) as exc:
        message = exc.message if isinstance(exc, Failure) else f"{type(exc).__name__}: {exc}"
        return finish(refuse(row, "records-refused", str(message)[:1200],
                                        "Every record was put back; the module is as it was."))
    row["outcome"] = "qualified"
    return finish(row, home)


def index_entry(directory: Path, index: dict[str, tuple[Path, dict]], job: Job) -> dict:
    """The declaration of the module being qualified, read from the directory the caller named and
    put on the shelf under its own id.

    Read, never recorded as an input of this job: the route rewrites this file at the end, and a
    job must not invalidate its own receipt. Each step's own receipt hashes the staged copy it
    actually built from, which is the hash a record should cite anyway."""
    declaration = directory / "module.json"
    if declaration.is_symlink() or not declaration.is_file():
        raise Failure(INPUT_MISSING, f"Module directory has no module.json: {directory}")
    job.check_deadline()
    metadata = compositions.validate_declaration_metadata(json.loads(compositions._read_inspection(declaration)))
    known = index.get(metadata["id"])
    if known is None or known[0].resolve() != directory.resolve():
        index[metadata["id"]] = (directory, metadata)
    return metadata


def adapter_cut(directory: Path, metadata: dict) -> tuple[str, str] | None:
    """``(foundation, map)`` when the declaration's default recipe is an adapter cut, else None.
    Read without a job: this is a shelf question asked before anything is staged."""
    if metadata["payload"] != "recipe":
        return None
    path = directory / metadata["payload_path"]
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    from . import adapters
    if not adapters.is_adapter_recipe(data):
        return None
    return data["foundation"], data["map"]


def probe_directory(index: dict[str, tuple[Path, dict]], members: list[str]) -> Path | None:
    """The shelf's ``test_probe``, staged beside the members so a module whose test contract asks
    for it finds exactly one candidate (``testing/planner.prepare_probe``)."""
    if "test_probe" in index:
        return index["test_probe"][0]
    for mid in members:
        candidate = index[mid][0].parent / "test_probe"
        if (candidate / "module.json").is_file():
            return candidate
    return None


def prepare_qualified(row: dict, staged: Path, index, info: dict, job: Job) -> bool:
    """Widen the staged declaration, and for an adapter write the target's cut beside the staged
    recipe first. Returns False with a refusal recorded when the cut cannot be written."""
    declaration = staged / "module.json"
    raw = declaration.read_text(encoding="utf-8")
    metadata = index[row["id"]][1]
    recipes = None
    if row["payload"] == "adapter":
        key = f"{row['foundation']}/{row['map']}"
        existing = metadata["recipes"].get(key)
        name = existing or f"recipe-{row['base']}.json"
        cut = staged / name
        if existing is None:
            source = json.loads((staged / metadata["payload_path"]).read_text(encoding="utf-8"))
            source["foundation"] = row["foundation"]
            source["map"] = row["map"]
            source["profile"] = f"{row['base']}_{row['id']}_test"
            source["revision"] = f"{row['base']}-{row['map']}-qualify-v1"
            if cut.exists():
                refuse(row, "adapter-recipe-single-target-without-recipes",
                       f"{name} already exists beside the recipe but recipes names no entry for {key}",
                       "Record the existing cut under recipes yourself, or move it aside; this route never overwrites a recipe.")
                return False
            replace(cut, serialise(source, (staged / metadata["payload_path"]).read_text(encoding="utf-8")))
        row["records"]["recipe"] = name
        row["records"]["recipe_reused"] = existing is not None
        row["records"]["recipe_sha256"] = sha256_file(cut)
        recipes = (key, name)
    text, changed = widen(raw, row["base"], row["map"], recipes)
    replace(declaration, text)
    row["records"]["staged_declaration_sha256"] = sha256_file(declaration)
    row["records"]["widened"] = changed
    return True


def record_step(row: dict, name: str, child: Job, result: dict | None, exc: Failure | None, workspace: Path) -> None:
    receipt = child.receipt_path
    step = {"receipt": relative_to(receipt, workspace), "ok": exc is None,
            "receipt_sha256": sha256_file(receipt) if receipt.is_file() else None,
            "error_code": exc.code if exc is not None else None}
    if result and name.startswith("build"):
        step["package_sha256"] = (result.get("packages") or [{}])[0].get("sha256")
        for key in ("rawfiles_verified", "embedded_assets", "referenced_assets", "soundbanks"):
            step[key] = result.get(key)
        step["unqualified"] = [u["id"] for u in result.get("unqualified") or []]
    if result and name.startswith("plan"):
        step["unqualified"] = [u["id"] for u in result.get("unqualified") or []]
        step["adapt"] = result.get("adapt") or []
    row["steps"][name] = step


def finish(row: dict, home: Path) -> dict:
    """The module's own row on disk beside its sub-receipts, whatever the outcome."""
    home.mkdir(parents=True, exist_ok=True)
    (home / "qualify.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    return row


# ----- the route -----------------------------------------------------------------------------

def read_set(path: Path, job: Job) -> list[Path]:
    source = job.input(path, limit=1024 * 1024)
    rows = []
    for line in source.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            rows.append(Path(line).expanduser())
    if not rows:
        raise Failure(INPUT_INVALID, f"--set names no module directories: {source}")
    if len(rows) > MAX_SET:
        raise Failure(INPUT_LIMIT, f"--set holds at most {MAX_SET} module directories")
    return rows


def execute(args, job: Job) -> dict:
    if bool(args.module) == bool(args.module_set):
        raise Failure(INPUT_INVALID, "Name one module directory, or --set with a file of them", "Not both, and not neither.")
    foundation, map_id = parse_target(args.target)
    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.is_dir():
        raise Failure(INPUT_MISSING, f"Workspace is missing: {workspace}")
    info = target_inputs(workspace, foundation, map_id, job)
    roots = [Path(r).expanduser().resolve() for r in args.member_root] or [workspace / "modules"]
    index = shelf(roots, job)
    directories = [Path(args.module).expanduser().resolve()] if args.module else [p.resolve() for p in read_set(Path(args.module_set), job)]
    wanted = {}
    for directory in directories:
        wanted[index_entry(directory, index, job)["id"]] = directory
    order = order_set(list(wanted), index)

    rows, results = [], job.root / "results.json"
    started = time.monotonic()
    for mid in order:
        job.check_deadline()
        try:
            row = qualify_one(wanted[mid], index, info, args, job, workspace)
        except Failure as exc:
            # The set continues past a failure; the module's own row carries it.
            row = {"id": mid, "directory": str(wanted[mid]), "target": f"{foundation}/{map_id}", "outcome": "refused",
                   "steps": {}, "records": {}, "at": now(),
                   "refusals": [{"kind": "shelf-missing" if exc.code == INPUT_MISSING else "plan-refused",
                                 "module": mid, "message": exc.message[:1200], "hint": exc.hint, "error_code": exc.code}]}
            finish(row, job.root / mid)
        rows.append(row)
        index = shelf(roots, job)  # a qualified module is a declared dependency for the next one
        results.write_text(json.dumps({"schema": 1, "protocol": PROTOCOL, "target": f"{foundation}/{map_id}",
                                       "modules": table(rows)}, indent=2) + "\n", encoding="utf-8")
    qualified = [r for r in rows if r["outcome"] == "qualified"]
    summary = {"protocol": PROTOCOL, "target": f"{foundation}/{map_id}", "base": info["base"],
               "workspace": str(workspace), "results": "results.json" if results.is_file() else None,
               "modules": table(rows), "qualified": len(qualified), "refused": len(rows) - len(qualified),
               "elapsed_seconds": round(time.monotonic() - started, 3),
               "verification": "each module built alone on the target twice (declaration-blind and qualified), read back and verified; "
                               "records written from those receipts only. Offline: nothing installed, launched or played."}
    if args.module and not qualified:
        raise Failure(INPUT_INVALID, rows[0]["refusals"][0]["message"] if rows[0]["refusals"] else "The module was not qualified",
                      rows[0]["refusals"][0].get("hint", "") if rows[0]["refusals"] else "",
                      refusals=rows[0]["refusals"], **{k: v for k, v in summary.items() if k != "verification"})
    return summary


def table(rows: list[dict]) -> list[dict]:
    """The results table: one row per module, the same fields whatever the outcome."""
    return [{"id": r["id"], "outcome": r["outcome"], "target": r["target"], "job": r.get("job"),
             "already_declared": r.get("already_declared"),
             "package_sha256": (r["steps"].get("build-qualified") or {}).get("package_sha256"),
             "package_identical": r.get("package_identical"),
             "receipts": {name: step["receipt"] for name, step in r["steps"].items()},
             "records": r.get("records") or {},
             "refusal": (r["refusals"][0] if r.get("refusals") else None)} for r in rows]
