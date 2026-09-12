"""``registry add|list|search|show`` and ``module fetch``: published modules by name.

A registry is a file anyone can host (``registry.json``) that lists module and composition
repositories at exact commits. It holds no bytes. ``registry add`` records a registry (a local
file or an https URL, copied under the toolkit home and validated), ``search`` and ``show``
read the copies, and ``module fetch`` downloads one entry's repository snapshot at its listed
commit into a new output directory, verifies the declaration is there and matches, and writes a
receipt. Nothing else in the toolkit talks to the network except ``dev setup``.

Registry (``registry.json``, schema 1)::

    {
      "schema": 1,
      "name": "plutonium-module-registry",
      "description": "Modules and packs for Plutonium T6 Zombies, listed at exact commits",
      "entries": [
        {
          "name": "sickohours/hello_zm",
          "kind": "module",
          "repository": "https://github.com/SickoHours/plutonium-agent-toolkit",
          "path": "examples/hello-zm",
          "listed": {"commit": "<40 hex>", "at": "2026-09-11"},
          "distribution": "source",
          "declaration": {"id": "hello_zm", "version": "0.1.0", "title": "hello-zm", "category": "scripts",
                          "kind": "script", "tags": ["example"], "bases": ["stock"], "maps": ["*"]},
          "verification": {"snapshot_status": "unverified"}
        }
      ]
    }

Entry names are ``<github-owner>/<module id>``; ownership is the repository living under that
owner. Only GitHub repositories are fetched in this version, as exact-commit tarballs over
HTTPS, without git and without a token.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..core import config
from ..core.envelope import now
from ..core.errors import CONFIG_INVALID, INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING, OUTPUT_EXISTS, Failure
from ..core.jobs import Job
from ..core.receipts import sha256_file
from . import backends

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,38}/[a-z0-9_]{1,64}\Z")
OWNER_REPO = re.compile(r"^https://github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9_.-]{1,100})/?\Z")
COMMIT = re.compile(r"^[0-9a-f]{40}\Z")
REGISTRY_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}\Z")
KINDS = ("module", "composition")
DISTRIBUTIONS = ("source", "seed", "private")
# The build-evidence ladder of CONTEXT.md, as a listing may claim it for the listed snapshot on the
# base and map the summary names: the highest fact the registry's own record supports, never a
# trust score. "none" is the default and means the registry claims nothing.
EVIDENCE_STATES = ("none", "offline-verified", "installed", "launched", "loaded", "playable", "captured", "accepted")
SUMMARY_FIELDS = ("id", "version", "title", "category", "kind", "tags", "bases", "maps", "provides", "origin", "donor")
RESERVED_OWNERS = ("plutonium", "pat", "stock")
# The registry that ships inside the package: the toolkit's built-in modules and packs at the exact
# commit the release pins. Read without `registry add`; its name is reserved so nothing can shadow it.
BUILTIN_FILE = Path(__file__).with_name("builtin.json")
BUILTIN_NAME = "plutonium-agent-toolkit-builtin"
ORIGINS = ("builtin", "added")
MAX_REGISTRY = 8 * 1024 * 1024
MAX_ENTRIES = 5000
MAX_SNAPSHOT = 256 * 1024 * 1024
MAX_SNAPSHOT_FILES = 20000
TIMEOUT = 60


# ----- network (the only two readers) ---------------------------------------------------

def fetch_bytes(url: str, limit: int, timeout: int = TIMEOUT) -> bytes:
    """One HTTPS GET, bounded, no redirect away from HTTPS. Patched in tests."""
    if not url.startswith("https://"):
        raise Failure(INPUT_INVALID, "Only HTTPS is permitted")
    request = urllib.request.Request(url, headers={"User-Agent": "plutonium-agent-toolkit", "Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - https enforced above
            if not response.url.startswith("https://"):
                raise Failure(INPUT_INVALID, "Download redirected away from HTTPS")
            chunks, total = [], 0
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > limit:
                    raise Failure(INPUT_LIMIT, f"Download exceeded {limit} bytes")
                chunks.append(block)
            return b"".join(chunks)
    except urllib.error.HTTPError as exc:
        with exc:
            raise Failure(INPUT_MISSING, f"HTTP {exc.code} for {url}",
                          "A 404 for a GitHub snapshot usually means the commit is not on that repository, or the repository is private.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise Failure("backend_failed", f"Cannot reach {url}: {getattr(exc, 'reason', exc)}") from exc


# ----- registry files -------------------------------------------------------------------

def _text(value, what: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise Failure(INPUT_INVALID, f"{what} must be a non-empty string of at most {limit} characters")
    return value


def validate_registry(data, where: str) -> dict:
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise Failure(INPUT_INVALID, f"{where}: expected a schema 1 registry object")
    allowed = {"schema", "name", "description", "entries", "source"}
    if set(data) - allowed or not {"schema", "name", "entries"} <= set(data):
        raise Failure(INPUT_INVALID, f"{where}: registry fields are {sorted(allowed)}")
    name = data["name"]
    if not isinstance(name, str) or not REGISTRY_ID.match(name):
        raise Failure(INPUT_INVALID, f"{where}: registry name is a lowercase identifier with dashes")
    description = data.get("description", "")
    if not isinstance(description, str) or len(description) > 400:
        raise Failure(INPUT_INVALID, f"{where}: description is at most 400 characters")
    entries = data["entries"]
    if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
        raise Failure(INPUT_INVALID, f"{where}: entries is a list of at most {MAX_ENTRIES} entries")
    seen = set()
    rows = []
    for entry in entries:
        rows.append(validate_entry(entry, where))
        key = rows[-1]["name"]
        if key in seen:
            raise Failure(INPUT_INVALID, f"{where}: entry listed twice: {key}")
        seen.add(key)
    return {"schema": 1, "name": name, "description": description, "entries": rows}


def validate_entry(entry, where: str) -> dict:
    allowed = {"name", "kind", "repository", "path", "listed", "distribution", "declaration", "verification", "history", "evidence_state"}
    if not isinstance(entry, dict) or set(entry) - allowed or not {"name", "kind", "repository", "listed"} <= set(entry):
        raise Failure(INPUT_INVALID, f"{where}: an entry has fields name, kind, repository, listed (optional path, distribution, declaration, "
                                     "verification, evidence_state, history)")
    name = entry["name"]
    if not isinstance(name, str) or not NAME.match(name):
        raise Failure(INPUT_INVALID, f"{where}: entry name is <github-owner>/<module id>, lowercase: {name!r}")
    owner = name.split("/", 1)[0]
    if owner in RESERVED_OWNERS:
        raise Failure(INPUT_INVALID, f"{where}: owner {owner!r} is reserved")
    kind = entry["kind"]
    if kind not in KINDS:
        raise Failure(INPUT_INVALID, f"{where}: entry kind is one of {list(KINDS)}: {name}")
    repository = _text(entry["repository"], f"{where}: {name} repository", 512)
    m = OWNER_REPO.match(repository)
    if not m:
        raise Failure(INPUT_INVALID, f"{where}: {name} repository is an https://github.com/<owner>/<repo> URL")
    if m.group(1).lower() != owner:
        raise Failure(INPUT_INVALID, f"{where}: {name} is owned by {owner!r} but its repository lives under {m.group(1)!r}",
                      "Ownership is proven by where the repository lives; the entry name carries the repository owner.")
    path = entry.get("path", ".")
    if not isinstance(path, str) or not path or "\\" in path or path.startswith("/") or ".." in Path(path).parts or path != path.strip():
        raise Failure(INPUT_INVALID, f"{where}: {name} path is a forward-slash relative path inside the repository")
    listed = entry["listed"]
    if not isinstance(listed, dict) or not isinstance(listed.get("commit"), str) or not COMMIT.match(listed["commit"]):
        raise Failure(INPUT_INVALID, f"{where}: {name} listed.commit is a 40-character lowercase hex commit id")
    if set(listed) - {"commit", "at", "branch"}:
        raise Failure(INPUT_INVALID, f"{where}: {name} listed has commit, at, branch")
    distribution = entry.get("distribution", "source")
    if distribution not in DISTRIBUTIONS:
        raise Failure(INPUT_INVALID, f"{where}: {name} distribution is one of {list(DISTRIBUTIONS)}")
    declaration = entry.get("declaration", {})
    if not isinstance(declaration, dict) or set(declaration) - set(SUMMARY_FIELDS):
        raise Failure(INPUT_INVALID, f"{where}: {name} declaration summary has {', '.join(SUMMARY_FIELDS)}")
    for key in ("tags", "bases", "maps"):
        if key in declaration and (not isinstance(declaration[key], list) or not all(isinstance(x, str) for x in declaration[key])):
            raise Failure(INPUT_INVALID, f"{where}: {name} declaration.{key} is a list of strings")
    if "origin" in declaration or "donor" in declaration:
        # The same constraints as the declaration, so a summary cannot carry a value no module.json could.
        from . import compositions
        compositions._origin(declaration.get("origin"), f"{where}: {name} declaration")
        compositions._donor(declaration.get("donor"), f"{where}: {name} declaration")
    evidence_state = entry.get("evidence_state", "none")
    if evidence_state not in EVIDENCE_STATES:
        raise Failure(INPUT_INVALID, f"{where}: {name} evidence_state is one of {list(EVIDENCE_STATES)}",
                      "It is the highest build-evidence fact the registry's own record supports for the listed snapshot; leave it out to claim none.")
    verification = entry.get("verification", {})
    if not isinstance(verification, dict):
        raise Failure(INPUT_INVALID, f"{where}: {name} verification is an object")
    history = entry.get("history", [])
    if not isinstance(history, list) or len(history) > 256:
        raise Failure(INPUT_INVALID, f"{where}: {name} history is a list")
    return {"name": name, "kind": kind, "repository": repository.rstrip("/"), "path": Path(path).as_posix() if path != "." else ".",
            "listed": dict(listed), "distribution": distribution, "declaration": dict(declaration),
            "verification": dict(verification), "evidence_state": evidence_state, "history": list(history)}


def registries_dir() -> Path:
    p = config.home() / "registries"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _index_path() -> Path:
    return registries_dir() / "index.json"


def _read_index() -> dict:
    path = _index_path()
    if not path.is_file():
        return {"schema": 1, "registries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise Failure(CONFIG_INVALID, f"Registry index is not valid JSON: {path}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("registries"), list):
        raise Failure(CONFIG_INVALID, f"Registry index is malformed: {path}")
    return data


def _write_index(data: dict) -> None:
    path = _index_path()
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def add(source: str) -> dict:
    """Record a registry from a local file or an https URL; the copy is validated and stored."""
    if source.startswith("https://"):
        raw = fetch_bytes(source, MAX_REGISTRY)
        origin = {"kind": "url", "url": source}
    else:
        path = Path(source).expanduser()
        if path.is_symlink() or not path.is_file():
            raise Failure(INPUT_MISSING, f"Registry file is missing: {path}")
        if path.stat().st_size > MAX_REGISTRY:
            raise Failure(INPUT_LIMIT, f"Registry file exceeds {MAX_REGISTRY} bytes")
        raw = path.read_bytes()
        origin = {"kind": "file", "path": str(path.resolve())}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise Failure(INPUT_INVALID, f"Registry is not valid JSON: {source}") from exc
    registry = validate_registry(data, source)
    if registry["name"] == BUILTIN_NAME:
        raise Failure(INPUT_INVALID, f"The registry name {BUILTIN_NAME!r} is reserved for the registry that ships with the toolkit",
                      "Give your registry another name; the built-in one is always listed and cannot be replaced.")
    digest = __import__("hashlib").sha256(raw).hexdigest()
    stored = registries_dir() / f"{registry['name']}.json"
    stored.write_text(json.dumps({**registry, "source": {**origin, "sha256": digest, "fetched_at": now()}}, indent=2) + "\n", encoding="utf-8")
    index = _read_index()
    index["registries"] = [r for r in index["registries"] if r.get("name") != registry["name"]]
    index["registries"].append({"name": registry["name"], "file": stored.name, "source": origin, "sha256": digest, "added_at": now()})
    _write_index(index)
    return {"name": registry["name"], "entries": len(registry["entries"]), "stored": str(stored), "sha256": digest, "source": origin,
            "verification": "registry validated and copied; nothing was fetched or built"}


def builtin_registry() -> dict:
    """The shipped registry, validated on every read (it is small) and marked with its origin."""
    try:
        data = json.loads(BUILTIN_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Failure(CONFIG_INVALID, f"The built-in registry shipped with this installation is unreadable: {BUILTIN_FILE}",
                      "Reinstall the toolkit; this file is part of the package.") from exc
    registry = validate_registry(data, "built-in registry")
    if registry["name"] != BUILTIN_NAME:
        raise Failure(CONFIG_INVALID, f"The built-in registry must be named {BUILTIN_NAME}, not {registry['name']}")
    return registry | {"origin": "builtin", "source": {"kind": "builtin", "file": BUILTIN_FILE.name}}


def _load_all() -> list[dict]:
    rows = [builtin_registry()]
    for item in _read_index()["registries"]:
        path = registries_dir() / item["file"]
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        rows.append(validate_registry({k: v for k, v in data.items() if k != "source"}, path.name) | {"source": data.get("source"), "origin": "added"})
    return rows


def listing() -> dict:
    rows = [{"name": r["name"], "origin": r["origin"], "description": r["description"], "entries": len(r["entries"]), "source": r.get("source")}
            for r in _load_all()]
    return {"registries": rows, "count": len(rows), "directory": str(registries_dir()),
            "note": "The built-in registry ships with the toolkit and is always listed; added registries were recorded with registry add."}


def search(text: str | None = None, *, category: str | None = None, kind: str | None = None, tag: str | None = None,
           base: str | None = None, map_id: str | None = None, entry_kind: str | None = None, origin: str | None = None) -> dict:
    words = [w for w in (text or "").lower().split() if w]
    if origin is not None and origin not in ORIGINS:
        raise Failure(INPUT_INVALID, f"--origin is one of {list(ORIGINS)}")
    hits = []
    seen: dict[tuple, dict] = {}
    for registry in _load_all():
        if origin and registry["origin"] != origin:
            continue
        for e in registry["entries"]:
            d = e["declaration"]
            hay = " ".join([e["name"], d.get("id", ""), d.get("title", ""), d.get("category", ""), d.get("kind", ""), " ".join(d.get("tags", [])),
                            d.get("origin", "")]).lower()
            if words and not all(w in hay for w in words):
                continue
            if category and d.get("category") != category:
                continue
            if kind and d.get("kind") != kind:
                continue
            if tag and tag not in d.get("tags", []):
                continue
            if base and base not in d.get("bases", []):
                continue
            if map_id and not (map_id in d.get("maps", []) or "*" in d.get("maps", [])):
                continue
            if entry_kind and e["kind"] != entry_kind:
                continue
            key = (e["name"], e["listed"]["commit"])
            if key in seen:
                # The same entry at the same commit listed by another registry (an added registry that
                # also lists a built-in) is one hit that names both; another commit is another hit.
                seen[key].setdefault("also_listed_by", []).append(registry["name"])
                continue
            hit = {"registry": registry["name"], "origin": registry["origin"], "name": e["name"], "kind": e["kind"], "distribution": e["distribution"],
                   "title": d.get("title"), "category": d.get("category"), "module_kind": d.get("kind"), "tags": d.get("tags", []),
                   "bases": d.get("bases", []), "maps": d.get("maps", []), "commit": e["listed"]["commit"],
                   "module_origin": d.get("origin"), "donor": d.get("donor"), "evidence_state": e["evidence_state"],
                   "snapshot_status": e["verification"].get("snapshot_status", "unverified"),
                   "fetch": ["pat", "module", "fetch", f"{e['name']}@{e['listed']['commit']}", "--output", "<new dir>"]}
            if registry["origin"] == "builtin":
                from . import builtin

                hit["builtin_dir"] = builtin.module_dir_if_present(e)
                hit["fetch"] = ["pat", "dev", "builtin", "--only", e["name"], "--json"]
            seen[key] = hit
            hits.append(hit)
    hits.sort(key=lambda h: (h["name"], h["origin"] != "builtin", h["registry"]))  # built-in listings first for a name
    return {"hits": hits, "count": len(hits),
            "filters": {k: v for k, v in {"text": text, "category": category, "kind": kind, "tag": tag, "base": base, "map": map_id, "entry_kind": entry_kind, "origin": origin}.items() if v}}


def show(name: str) -> dict:
    if not NAME.match(name or ""):
        raise Failure(INPUT_INVALID, "Give an entry name as <github-owner>/<module id>")
    found = [(r, e) for r in _load_all() for e in r["entries"] if e["name"] == name]
    if not found:
        raise Failure(INPUT_MISSING, f"No registry lists {name}", "Run: pat registry search <words>, or add the registry that lists it.")
    rows = []
    for registry, e in found:
        row = {"registry": registry["name"], "origin": registry["origin"], **e,
               "fetch": ["pat", "module", "fetch", f"{e['name']}@{e['listed']['commit']}", "--output", "<new dir>"],
               "snapshot_url": snapshot_url(e["repository"], e["listed"]["commit"])}
        if registry["origin"] == "builtin":
            from . import builtin

            row["builtin_dir"] = builtin.module_dir_if_present(e)
            row["fetch"] = ["pat", "dev", "builtin", "--only", e["name"], "--json"]
        rows.append(row)
    return {"name": name, "listings": rows, "count": len(rows),
            "note": "A listing is what a registry claims at that commit. Fetch, then plan; the receipts are the facts."}


# ----- fetch ----------------------------------------------------------------------------

def snapshot_url(repository: str, commit: str) -> str:
    m = OWNER_REPO.match(repository)
    if not m:
        raise Failure(INPUT_INVALID, f"Only https://github.com/<owner>/<repo> repositories are fetched in this version: {repository}")
    return f"https://codeload.github.com/{m.group(1)}/{m.group(2)}/tar.gz/{commit}"


def resolve_reference(text: str) -> dict:
    """``owner/id@commit`` through the configured registries, or ``https://github.com/o/r@commit``."""
    if "@" not in text:
        raise Failure(INPUT_INVALID, "A reference pins a commit: <owner>/<id>@<40 hex>, or https://github.com/<owner>/<repo>@<40 hex>")
    head, _, commit = text.rpartition("@")
    if not COMMIT.match(commit):
        raise Failure(INPUT_INVALID, f"The commit is a 40-character lowercase hex id: {commit!r}",
                      "A short id or a branch name is not a pin; ask the registry (pat registry show) or the repository for the full commit.")
    if head.startswith("https://"):
        if not OWNER_REPO.match(head):
            raise Failure(INPUT_INVALID, f"Repository is an https://github.com/<owner>/<repo> URL: {head}")
        return {"name": None, "repository": head.rstrip("/"), "path": ".", "commit": commit, "registry": None, "entry": None}
    if not NAME.match(head):
        raise Failure(INPUT_INVALID, f"Entry names are <github-owner>/<module id>: {head!r}")
    found = [(r["name"], e) for r in _load_all() for e in r["entries"] if e["name"] == head]
    if not found:
        raise Failure(INPUT_MISSING, f"No configured registry lists {head}",
                      "Add the registry with pat registry add, or fetch by repository URL: https://github.com/<owner>/<repo>@<commit> --path <dir>.")
    # The same name may be listed by several registries at different commits (the built-in one and an
    # added one, say); the reference names a commit, so the listing at that commit is the one.
    matching = [(name, e) for name, e in found if e["listed"]["commit"] == commit]
    if not matching:
        listed = sorted({f"{e['listed']['commit']} ({name})" for name, e in found})
        raise Failure(INPUT_INVALID, f"{head} is listed at {', '.join(listed)}, not {commit}",
                      "Fetch a listed commit, or fetch by repository URL for an unlisted commit and say so in your report.")
    registry, entry = matching[0]
    return {"name": head, "repository": entry["repository"], "path": entry["path"], "commit": commit, "registry": registry, "entry": entry}


def fetch(args, job: Job) -> dict:
    ref = resolve_reference(args.reference)
    path = args.path or ref["path"] or "."
    if "\\" in path or path.startswith("/") or ".." in Path(path).parts or path != path.strip():
        raise Failure(INPUT_INVALID, "--path is a forward-slash relative path inside the repository")
    url = snapshot_url(ref["repository"], ref["commit"])
    archive_dir = job.root / "snapshot"
    archive_dir.mkdir()
    archive = archive_dir / f"{ref['commit']}.tar.gz"
    raw = fetch_bytes(url, MAX_SNAPSHOT)
    archive.write_bytes(raw)
    archive_sha = sha256_file(archive)
    extracted = job.root / "repository"
    backends.safe_extract(archive, extracted, strip_root=True)
    count = sum(1 for p in extracted.rglob("*") if p.is_file())
    if count > MAX_SNAPSHOT_FILES:
        raise Failure(INPUT_LIMIT, f"The snapshot holds more than {MAX_SNAPSHOT_FILES} files")
    module_dir = extracted / path if path != "." else extracted
    if not module_dir.is_dir():
        raise Failure(INPUT_MISSING, f"The snapshot has no directory {path!r}")
    declaration = module_dir / "module.json"
    composition = module_dir / "composition.json"
    if not declaration.is_file() and not composition.is_file():
        raise Failure(INPUT_MISSING, f"{path!r} in the snapshot holds neither module.json nor composition.json",
                      "A repository is a module when module.json sits beside its payload (docs/MODULES.md).")
    kind = "module" if declaration.is_file() else "composition"
    facts = {}
    if kind == "module":
        try:
            data = json.loads(declaration.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise Failure(INPUT_INVALID, "The fetched module.json is not valid JSON") from exc
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise Failure(INPUT_INVALID, "The fetched module.json has no id")
        source = data.get("source") or {}
        if isinstance(source, dict):
            if isinstance(source.get("commit"), str) and source["commit"] != ref["commit"]:
                raise Failure(INPUT_INVALID, f"The fetched declaration names commit {source['commit'][:12]}, not the fetched {ref['commit'][:12]} (declaration-mismatch)",
                              "The declaration must bind to the snapshot it ships in; the author updates source.commit when they publish.")
            if isinstance(source.get("repository"), str) and source["repository"].rstrip("/").lower() != ref["repository"].lower():
                raise Failure(INPUT_INVALID, f"The fetched declaration names repository {source['repository']}, not {ref['repository']} (declaration-mismatch)")
        if ref["name"] and data["id"] != ref["name"].split("/", 1)[1]:
            raise Failure(INPUT_INVALID, f"The registry lists {ref['name']} but the declaration's id is {data['id']!r} (declaration-mismatch)")
        facts = {"id": data.get("id"), "version": data.get("version"), "title": data.get("title"), "category": data.get("category"),
                 "kind": data.get("kind"), "tags": data.get("tags", []), "bases": data.get("bases"), "maps": data.get("maps"),
                 "distribution": data.get("distribution", "seed" if "seed" in data else "source"),
                 "payload": "seed" if "seed" in data else "recipe"}
        if facts["payload"] == "seed":
            seed_manifest = module_dir / str(data.get("seed", "seed.json"))
            package = seed_manifest.parent / "mod.ff" if seed_manifest.is_file() else None
            facts["seed_manifest_present"] = seed_manifest.is_file()
            facts["seed_package_present"] = bool(package and package.is_file())
    (job.root / "fetch.json").write_text(json.dumps({
        "schema_version": 1, "reference": args.reference, "name": ref["name"], "registry": ref["registry"], "repository": ref["repository"],
        "commit": ref["commit"], "path": path, "url": url, "archive_sha256": archive_sha, "archive_bytes": len(raw),
        "files": count, "kind": kind, "declaration_sha256": sha256_file(declaration) if declaration.is_file() else None,
        "composition_sha256": sha256_file(composition) if composition.is_file() else None, "facts": facts, "fetched_at": now()}, indent=2) + "\n", encoding="utf-8")
    member = {"name": ref["name"], "commit": ref["commit"], "path": f"<relative path to {job.root.name}/repository/{path}>"} if ref["name"] \
        else {"path": f"<relative path to {job.root.name}/repository/{path}>"}
    return {"name": ref["name"], "repository": ref["repository"], "commit": ref["commit"], "path": path, "url": url,
            "archive_sha256": archive_sha, "archive_bytes": len(raw), "files": count, "kind": kind,
            "module_dir": str(module_dir), "facts": facts, "fetch_record": "fetch.json",
            "composition_member": member,
            "next": ["Name module_dir under modules in your composition (a reference member keeps name and commit).",
                     "pat module plan <composition> --output <new dir> --json",
                     "A private seed fetched without its package can be planned around, not built."],
            "verification": "exact-commit snapshot downloaded over HTTPS, hashed, extracted with the archive safety checks; the declaration's own repository and commit checked; nothing built"}
