"""``module plan|build``: several declared modules composed into one mod on a named base.

A module declaration (``module.json``) sits beside a module's ``project.json`` recipe and says
what the module is and needs. A composition recipe (``composition.json``) names a base, a map
and the module directories to compose. ``plan`` resolves the composition (dependency order,
conflicts, base and map fit, target collisions, resource budget) and hashes every input without
running a backend. ``build`` compiles every module's scripts, stages every asset, links one
``mod.ff`` as zone ``mod``, reads it back and byte-compares every rawfile, exactly as
``project build`` does for one recipe. Both formats are specified in ``docs/MODULES.md``.

Module declaration (``module.json``, schema 1)::

    {
      "schema": 1, "id": "hello_zm", "version": "0.1.0", "title": "hello-zm",
      "category": "scripts", "recipe": "project.json",
      "bases": ["stock"], "maps": ["*"],
      "dependencies": [], "conflicts": [],
      "resource_contract": {"threads": 1, "entities": 0, "hud": 0, "network_fields": 0},
      "menu_route": "none; prints on spawn",
      "source": {"repository": "https://github.com/<owner>/<repo>", "commit": "<40 hex>"}
    }

Composition recipe (``composition.json``, schema 1)::

    {
      "schema": 1, "name": "stock_hello_pack", "base": "stock", "map": "zm_transit",
      "modules": ["../hello-zm", "../hello-zm-two"], "loads": [],
      "budget": {"threads": 4, "entities": 0, "hud": 0, "network_fields": 0}
    }
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..core.errors import INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING, Failure
from ..core.jobs import Job
from . import projects
from .backends import executable

ID = re.compile(r"^[a-z0-9_]{1,64}\Z")
BASE = re.compile(r"^[a-z0-9]{1,16}\Z")
MAP = re.compile(r"^[a-z0-9_]{1,64}\Z")
VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,31}\Z")
CATEGORY = re.compile(r"^[a-z][a-z0-9-]{0,31}\Z")
COMMIT = re.compile(r"^[0-9a-f]{40}\Z")
STAGES = ("test", "pack", "pub")
CONTRACT_FIELDS = ("threads", "entities", "hud", "network_fields")
MAX_MODULES = 32
MAX_LIST = 64
MAX_CONTRACT = 100_000


def add_parser(sub, common):
    p = sub.add_parser("module", help="Declared modules composed into one mod on a named base: plan, build")
    actions = p.add_subparsers(dest="action", required=True)
    for action, help_text in (("plan", "Resolve a composition and hash its inputs; runs no backend"),
                              ("build", "Compile, link, read back and compare every module into one mod.ff")):
        q = actions.add_parser(action, help=help_text)
        q.add_argument("composition", help="Path to composition.json")
        common(q)


def _text(value, what: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise Failure(INPUT_INVALID, f"{what} must be a non-empty string of at most {limit} characters")
    return value


def _ids(value, what: str, owner: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_LIST:
        raise Failure(INPUT_INVALID, f"{owner}: {what} must be a list of at most {MAX_LIST} module ids")
    for item in value:
        if not isinstance(item, str) or not ID.match(item):
            raise Failure(INPUT_INVALID, f"{owner}: {what} entries use lowercase letters, digits and underscore: {item!r}")
        if item == owner:
            raise Failure(INPUT_INVALID, f"{owner}: a module cannot list itself under {what}")
    if len(set(value)) != len(value):
        raise Failure(INPUT_INVALID, f"{owner}: duplicate entries under {what}")
    return list(value)


def _contract(value, what: str) -> dict:
    if value is None:
        return {field: 0 for field in CONTRACT_FIELDS}
    if not isinstance(value, dict) or set(value) - set(CONTRACT_FIELDS):
        raise Failure(INPUT_INVALID, f"{what} names only {list(CONTRACT_FIELDS)}")
    rows = {}
    for field in CONTRACT_FIELDS:
        n = value.get(field, 0)
        if type(n) is not int or n < 0 or n > MAX_CONTRACT:
            raise Failure(INPUT_INVALID, f"{what}.{field} must be a whole number from 0 to {MAX_CONTRACT}")
        rows[field] = n
    return rows


def _module_dir(text: str, base: Path, job: Job) -> Path:
    """A module directory named in a composition: relative, forward slashes, may live beside the
    composition (``../hello-zm``), never absolute, never a link, never inside the job output."""
    if not isinstance(text, str) or not text or len(text) > 4096 or "\\" in text or text != text.strip():
        raise Failure(INPUT_INVALID, "Module paths are forward-slash relative paths")
    p = Path(text)
    if p.is_absolute() or not p.parts:
        raise Failure(INPUT_INVALID, f"Module paths are relative to the composition directory: {text}")
    full = base / p
    if full.is_symlink() or not full.is_dir():
        raise Failure(INPUT_MISSING, f"Module directory is missing or is a link: {text}")
    full = full.resolve()
    if full.is_relative_to(job.root):
        raise Failure(INPUT_INVALID, "Modules must live outside the job's output directory")
    return full


def load_declaration(directory: Path, job: Job) -> dict:
    path = directory / "module.json"
    if path.is_symlink() or not path.is_file():
        raise Failure(INPUT_MISSING, f"Module directory has no module.json: {directory}")
    src = job.input(path, limit=256 * 1024)
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise Failure(INPUT_INVALID, f"module.json is not valid JSON: {src}") from exc
    where = f"module.json in {directory.name}"
    projects._fields(data, {"schema", "id", "version", "title", "category", "recipe", "bases", "maps", "dependencies",
                            "conflicts", "resource_contract", "menu_route", "source"},
                     {"schema", "id", "version", "recipe", "bases", "maps"}, where)
    if data["schema"] != 1:
        raise Failure(INPUT_INVALID, f"{where}: expected schema 1")
    mid = data["id"]
    if not isinstance(mid, str) or not ID.match(mid):
        raise Failure(INPUT_INVALID, f"{where}: id uses lowercase letters, digits and underscore")
    if not isinstance(data["version"], str) or not VERSION.match(data["version"]):
        raise Failure(INPUT_INVALID, f"{mid}: version is a short version string (letters, digits, dot, plus, dash)")
    title = _text(data.get("title", mid), f"{mid}: title", 120)
    category = data.get("category", "module")
    if not isinstance(category, str) or not CATEGORY.match(category):
        raise Failure(INPUT_INVALID, f"{mid}: category is a lowercase identifier such as weapons, perks or scripts")
    recipe = projects._rel(_text(data["recipe"], f"{mid}: recipe", 4096), directory)
    if recipe.is_symlink() or not recipe.is_file():
        raise Failure(INPUT_MISSING, f"{mid}: recipe is missing: {data['recipe']}")
    bases = data["bases"]
    if not isinstance(bases, list) or not bases or len(bases) > MAX_LIST or len(set(bases)) != len(bases) \
            or not all(isinstance(b, str) and BASE.match(b) for b in bases):
        raise Failure(INPUT_INVALID, f"{mid}: bases is a non-empty list of distinct base tokens (lowercase letters and digits)")
    maps = data["maps"]
    if not isinstance(maps, list) or not maps or len(maps) > MAX_LIST or len(set(maps)) != len(maps) \
            or not all(isinstance(m, str) and (m == "*" or MAP.match(m)) for m in maps):
        raise Failure(INPUT_INVALID, f"{mid}: maps is a non-empty list of distinct map ids, or [\"*\"] for any map")
    menu_route = data.get("menu_route", "")
    if not isinstance(menu_route, str) or len(menu_route) > 200:
        raise Failure(INPUT_INVALID, f"{mid}: menu_route is a string of at most 200 characters")
    source = data.get("source")
    if source is not None:
        projects._fields(source, {"repository", "commit"}, {"repository"}, f"{mid}: source")
        repository = _text(source["repository"], f"{mid}: source.repository", 512)
        if not repository.startswith("https://"):
            raise Failure(INPUT_INVALID, f"{mid}: source.repository is an https URL")
        if "commit" in source and (not isinstance(source["commit"], str) or not COMMIT.match(source["commit"])):
            raise Failure(INPUT_INVALID, f"{mid}: source.commit is a 40-character lowercase hex commit id")
    return {"id": mid, "version": data["version"], "title": title, "category": category, "directory": directory,
            "recipe": recipe, "bases": list(bases), "maps": list(maps),
            "dependencies": _ids(data.get("dependencies", []), "dependencies", mid),
            "conflicts": _ids(data.get("conflicts", []), "conflicts", mid),
            "resource_contract": _contract(data.get("resource_contract"), f"{mid}: resource_contract"),
            "menu_route": menu_route, "source": source, "declaration": src}


def load_composition(path: Path, job: Job) -> dict:
    src = job.input(path, limit=256 * 1024)
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise Failure(INPUT_INVALID, f"Composition is not valid JSON: {src}") from exc
    projects._fields(data, {"schema", "name", "base", "map", "modules", "loads", "budget"},
                     {"schema", "name", "base", "map", "modules"}, "composition")
    if data["schema"] != 1:
        raise Failure(INPUT_INVALID, "Expected a schema 1 composition")
    base = data["base"]
    if not isinstance(base, str) or not BASE.match(base):
        raise Failure(INPUT_INVALID, "Composition base is a short token of lowercase letters and digits (stock, or the base release's short name)")
    map_id = data["map"]
    if not isinstance(map_id, str) or not MAP.match(map_id):
        raise Failure(INPUT_INVALID, "Composition map is one concrete map id; a composition is planned for one map")
    name = data["name"]
    if not isinstance(name, str) or not projects.NAME.match(name) \
            or not re.fullmatch(rf"{re.escape(base)}_[a-z0-9_]+_(?:{'|'.join(STAGES)})", name):
        raise Failure(INPUT_INVALID, f"Composition name follows <base>_<feature>_<stage> with base {base!r} and stage test, pack or pub")
    entries = data["modules"]
    if not isinstance(entries, list) or not entries or len(entries) > MAX_MODULES:
        raise Failure(INPUT_INVALID, f"modules lists 1 to {MAX_MODULES} module directories")
    directories = []
    for text in entries:
        directory = _module_dir(text, src.parent, job)
        if directory in directories:
            raise Failure(INPUT_INVALID, f"Module directory listed twice: {text}")
        directories.append(directory)
    load_rows = data.get("loads", [])
    if not isinstance(load_rows, list) or len(load_rows) > projects.MAX_LOADS:
        raise Failure(INPUT_INVALID, f"loads is a list of at most {projects.MAX_LOADS} fastfiles")
    loads = [job.input(projects._rel(text, src.parent)) for text in load_rows]
    return {"name": name, "base": base, "map": map_id, "directories": directories, "entries": list(entries),
            "loads": loads, "budget": _contract(data["budget"], "budget") if "budget" in data else None,
            "source": src}


def _order(modules: list[dict]) -> list[str]:
    """Dependency order (a module after everything it depends on); refuses cycles."""
    pending = {m["id"]: set(m["dependencies"]) for m in modules}
    order: list[str] = []
    while pending:
        ready = sorted(mid for mid, deps in pending.items() if not deps - set(order))
        if not ready:
            raise Failure(INPUT_INVALID, f"Dependency cycle among modules: {sorted(pending)}")
        for mid in ready:
            order.append(mid)
            del pending[mid]
    return order


def resolve(comp: dict, modules: list[dict]) -> dict:
    ids = [m["id"] for m in modules]
    if len(set(ids)) != len(ids):
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        raise Failure(INPUT_INVALID, f"Two module directories declare the same id: {duplicates}")
    known = set(ids)
    for m in modules:
        for dep in m["dependencies"]:
            if dep not in known:
                raise Failure(INPUT_INVALID, f"{m['id']} depends on {dep}, which is not in the composition",
                              "Add the module directory that declares that id to the composition's modules list.")
        for other in m["conflicts"]:
            if other in known:
                raise Failure(INPUT_INVALID, f"{m['id']} declares a conflict with {other}; both are in the composition")
        if comp["base"] not in m["bases"]:
            raise Failure(INPUT_INVALID, f"{m['id']} is declared for bases {m['bases']}, not for {comp['base']!r}",
                          "Build the module on a base it declares, or extend its declaration after testing it there.")
        if "*" not in m["maps"] and comp["map"] not in m["maps"]:
            raise Failure(INPUT_INVALID, f"{m['id']} is declared for maps {m['maps']}, not for {comp['map']!r}")
    order = _order(modules)
    totals = {field: sum(m["resource_contract"][field] for m in modules) for field in CONTRACT_FIELDS}
    if comp["budget"] is not None:
        for field in CONTRACT_FIELDS:
            if totals[field] > comp["budget"][field]:
                raise Failure(INPUT_LIMIT, f"Resource budget exceeded: {field} {totals[field]} > {comp['budget'][field]}",
                              "Raise the budget deliberately after measuring, or leave a module out; the sum counts every module.")
    return {"order": order, "resource_totals": totals}


def _targets(modules: list[dict], loaded: dict[str, tuple]) -> None:
    owners: dict[str, str] = {}
    for m in modules:
        _, compiled, loose, _ = loaded[m["id"]]
        for target in [t for _, t, _ in compiled] + [t for _, t, _, _ in loose]:
            key = target.as_posix().casefold()
            if key in owners:
                raise Failure(INPUT_INVALID, f"{owners[key]} and {m['id']} both produce {target.as_posix()}",
                              "Two modules cannot ship the same file; rename one target or drop one module.")
            owners[key] = m["id"]


def _backends(compiled: list) -> list[dict]:
    checks = []
    for name in (["gsc"] if compiled else []) + ["linker", "unlinker"]:
        try:
            checks.append({"id": name, "argv": executable(name), "available": True})
        except Failure as exc:
            checks.append({"id": name, "available": False, "message": exc.message})
    return checks


def execute(args, job: Job) -> dict:
    comp = load_composition(Path(args.composition), job)
    modules = [load_declaration(d, job) for d in comp["directories"]]
    resolved = resolve(comp, modules)
    loaded = {m["id"]: projects.load_recipe(m["recipe"], job) for m in modules}
    _targets(modules, loaded)
    by_id = {m["id"]: m for m in modules}
    compiled, loose, loads = [], [], list(comp["loads"])
    for mid in resolved["order"]:
        _, c, l, extra_loads = loaded[mid]
        compiled += c
        loose += l
        loads += [p for p in extra_loads if p not in loads]
    if len(compiled) > projects.MAX_SCRIPTS or len(loose) > projects.MAX_ASSETS or len(loads) > projects.MAX_LOADS:
        raise Failure(INPUT_LIMIT, f"A composition holds at most {projects.MAX_SCRIPTS} scripts, {projects.MAX_ASSETS} assets and {projects.MAX_LOADS} loads in total")
    checks = _backends(compiled)
    rows = [{"id": mid, "version": by_id[mid]["version"], "title": by_id[mid]["title"], "category": by_id[mid]["category"],
             "directory": str(by_id[mid]["directory"]), "declaration_sha256": job.inputs[str(by_id[mid]["declaration"])],
             "recipe_sha256": job.inputs[str(by_id[mid]["recipe"].resolve())],
             "dependencies": by_id[mid]["dependencies"], "conflicts": by_id[mid]["conflicts"],
             "bases": by_id[mid]["bases"], "maps": by_id[mid]["maps"], "resource_contract": by_id[mid]["resource_contract"],
             "menu_route": by_id[mid]["menu_route"], "source": by_id[mid]["source"]}
            for mid in resolved["order"]]
    plan = {
        "schema_version": 1, "name": comp["name"], "base": comp["base"], "map": comp["map"], "game": "t6", "mode": "zm",
        "modules": rows, "order": resolved["order"],
        "scripts": [{"source": str(p), "target": t.as_posix(), "instance": i} for p, t, i in compiled],
        "assets": [{"source": str(p), "target": t.as_posix(), "type": k, "name": n} for p, t, k, n in loose],
        "loads": [str(p) for p in loads],
        "resource_totals": resolved["resource_totals"], "budget": comp["budget"],
        "backends": checks, "backends_available": all(c["available"] for c in checks),
        "input_files": len(job.inputs),
        "verification": "composition resolved (dependency order, conflicts, base and map fit, target collisions, resource budget); "
                        "declarations, recipes and declared inputs hashed; backend presence checked; nothing compiled",
    }
    (job.root / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    summary = {"plan": "plan.json", "name": comp["name"], "base": comp["base"], "map": comp["map"],
               "modules": [{"id": r["id"], "version": r["version"], "order": i + 1} for i, r in enumerate(rows)],
               "resource_totals": resolved["resource_totals"], "budget": comp["budget"],
               "scripts": len(compiled), "assets": len(loose), "loads": len(loads)}
    if args.action == "plan":
        return {**summary, "backends": checks, "backends_available": plan["backends_available"],
                "input_files": plan["input_files"], "verification": plan["verification"]}
    built = projects._build({"name": comp["name"]}, compiled, loose, loads, plan, args, job)
    return {**built, **{k: v for k, v in summary.items() if k != "plan"},
            "verification": "every module's scripts compiled, one mod.ff linked and read back, every rawfile byte-compared; "
                            "the composition's fit and budget were checked from declarations, not measured in game"}
