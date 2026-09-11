"""Seed packages: a module whose payload is an already-linked fastfile.

A seed is ``mod.ff`` plus its soundbanks and a manifest that hashes them and lists the assets
the package embeds, the ones it references from the base, and the roots the pack's zone must
name so the linker copies them out of the seed. ``module declare`` writes the manifest by
reading the package back with OpenAssetTools; ``module plan`` hashes it like any other input;
``module build`` links the pack against every seed (``-l``) and the base's zones and names every
root in the zone, which is how the authoring workspace composes its native weapon modules.

Manifest (``seed.json``, schema 1)::

    {
      "schema": 1, "package": "mod.ff",
      "files": {"mod.ff": "<sha256>", "halo_penetrator.all.sabl": "<sha256>"},
      "roots": ["weapon,halo_penetrator_zm", "soundbank,halo_penetrator.all", "xanim,..."],
      "embedded": ["fx,...", "image,...", "material,...", ...],
      "referenced": ["image,$identitynormalmap", "techniqueset,..."],
      "provides": {"weapons": ["halo_penetrator_zm"], "localize": ["HALO_PENETRATOR"]},
      "strings": "mod.str",
      "source": {"tool": "OpenAssetTools Unlinker", "listing_sha256": "<sha256>"}
    }

Localized strings are not copied out of a loaded fastfile by the linker: it reads them from a
``localizedstrings/<zone>.str`` file. ``declare`` therefore extracts the seed's strings to
``mod.str`` beside the manifest, and ``module build`` merges every seed's strings into the
pack's own string file and names ``localize,mod`` in the zone.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..core.errors import INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING, Failure
from ..core.jobs import Job
from ..core.receipts import sha256_file
from . import titles

ASSET = re.compile(r"^[a-z0-9_]{1,32},[^\s,][^\r\n,]{0,255}\Z")
BANK = re.compile(r"^[a-z0-9_.]+\.sab[ls]\Z")
LISTING = re.compile(r"^(\w+), ?(,?) ?(.+?)\s*$")
SKIP = {"Loaded", "Loading", "Failed", "Unloaded", "Loading", "Zone", "Content", "MAPENT"}
# Asset types the linker copies out of a loaded fastfile when named as a root. Every other embedded
# asset arrives as a dependency of one of these; naming the leaves too is harmless but noisy.
ROOT_TYPES = ("weapon", "soundbank", "xanim", "xmodel", "material", "fx", "rawfile", "localize", "image",
              "techniqueset", "menu", "menulist", "font", "stringtable", "tracer", "physpreset", "physconstraints")
# Types that only ever come from the base or are generated per zone: never roots.
NEVER_ROOTS = {"keyvaluepairs", "localize", "techniqueset", "image"}
MAX_ASSETS = 8192
MAX_FILES = 64
MAX_PACKAGE = 2 * 1024**3


def parse_listing(text: str) -> tuple[list[str], list[str]]:
    """Unlinker ``--list`` output to (embedded, referenced) ``type,name`` rows, in listing order."""
    embedded, referenced = [], []
    seen = set()
    for line in text.splitlines():
        m = LISTING.match(line)
        if not m or m.group(1) in SKIP:
            continue
        kind, is_ref, name = m.group(1), bool(m.group(2)), m.group(3).strip()
        if kind.startswith(("Loaded", "Loading")) or not name:
            continue
        row = f"{kind},{name}"
        if row in seen:
            continue
        seen.add(row)
        (referenced if is_ref else embedded).append(row)
        if len(seen) > MAX_ASSETS:
            raise Failure(INPUT_LIMIT, f"The package lists more than {MAX_ASSETS} assets")
    return embedded, referenced


def roots_of(embedded: list[str]) -> list[str]:
    rows = []
    for row in embedded:
        kind = row.split(",", 1)[0]
        if kind in NEVER_ROOTS:
            continue
        if kind in ROOT_TYPES or kind in ("weapon", "soundbank"):
            rows.append(row)
    # Weapons and soundbanks first: they are what a pack composes; the rest keeps listing order.
    head = [r for r in rows if r.split(",", 1)[0] in ("weapon", "soundbank")]
    tail = [r for r in rows if r not in head]
    return head + tail


def provides_of(embedded: list[str]) -> dict:
    out: dict[str, list[str]] = {}
    for row in embedded:
        kind, name = row.split(",", 1)
        key = {"weapon": "weapons", "localize": "localize", "soundbank": "soundbanks", "rawfile": "rawfiles",
               "xmodel": "models", "fx": "effects"}.get(kind)
        if key:
            out.setdefault(key, []).append(name)
    return {k: sorted(v) for k, v in sorted(out.items())}


STRING_REF = re.compile(r"^[A-Z0-9_]{1,128}\Z")


def parse_strings(text: str, owner: str) -> dict[str, str]:
    """A T6 localized-strings file (REFERENCE / LANG_ENGLISH pairs) to a mapping; anything else is refused."""
    rows: dict[str, str] = {}
    ref = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//") or line.split()[0] in ("VERSION", "CONFIG", "FILENOTES", "ENDMARKER"):
            continue
        key, _, value = line.partition(" ")
        value = value.strip()
        if key == "REFERENCE":
            if not STRING_REF.match(value):
                raise Failure(INPUT_INVALID, f"{owner}: localized string reference is uppercase letters, digits and underscore: {value!r}")
            ref = value
        elif key == "LANG_ENGLISH" and ref:
            try:
                rows[ref] = json.loads(value) if value.startswith('"') else value
            except ValueError as exc:
                raise Failure(INPUT_INVALID, f"{owner}: localized string {ref} is not a quoted string") from exc
            ref = None
        else:
            raise Failure(INPUT_INVALID, f"{owner}: unsupported line in localized strings: {line[:60]!r}")
        if len(rows) > 4096:
            raise Failure(INPUT_LIMIT, f"{owner}: more than 4096 localized strings")
    return rows


def write_strings(rows: dict[str, str]) -> str:
    body = "".join(f"REFERENCE {k}\nLANG_ENGLISH {json.dumps(v)}\n\n" for k, v in sorted(rows.items()))
    return 'VERSION "1"\nCONFIG ""\nFILENOTES ""\n\n' + body + "ENDMARKER\n"


def load_manifest(directory: Path, relative: str, job: Job, owner: str, allow_missing_files: bool = False) -> dict:
    """Validate a seed manifest named by a declaration and hash every file it lists.

    With ``allow_missing_files`` (a ``private`` module) a listed file may be absent; the manifest
    is still validated and the result says ``private: True`` so a plan can name what is missing."""
    if not isinstance(relative, str) or not relative or "\\" in relative or Path(relative).is_absolute() \
            or ".." in Path(relative).parts:
        raise Failure(INPUT_INVALID, f"{owner}: seed is a forward-slash relative path inside the module directory")
    path = directory / relative
    if path.is_symlink() or not path.is_file():
        raise Failure(INPUT_MISSING, f"{owner}: seed manifest is missing: {relative}",
                      "Write one with: pat module declare <mod.ff> --output <new dir>, then copy seed.json beside the package.")
    src = job.input(path, limit=4 * 1024 * 1024)
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise Failure(INPUT_INVALID, f"{owner}: seed manifest is not valid JSON") from exc
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise Failure(INPUT_INVALID, f"{owner}: seed manifest must be a schema 1 object")
    allowed = {"schema", "package", "files", "roots", "embedded", "referenced", "provides", "source", "strings"}
    if set(data) - allowed or not {"schema", "package", "files", "roots", "embedded", "referenced"} <= set(data):
        raise Failure(INPUT_INVALID, f"{owner}: seed manifest fields are {sorted(allowed)}")
    files = data["files"]
    if not isinstance(files, dict) or not files or len(files) > MAX_FILES:
        raise Failure(INPUT_INVALID, f"{owner}: seed files is a map of 1 to {MAX_FILES} file names to sha256")
    package = data["package"]
    if package != "mod.ff" or package not in files:
        raise Failure(INPUT_INVALID, f"{owner}: a seed package is named mod.ff and listed under files",
                      "A T6 fastfile is bound to its file name; a seed built as another zone cannot be linked against as mod.")
    seed_dir = src.parent
    hashed: dict[str, Path] = {}
    missing: list[str] = []
    for name, digest in files.items():
        if not isinstance(name, str) or not (name == "mod.ff" or BANK.match(name)):
            raise Failure(INPUT_INVALID, f"{owner}: seed files are mod.ff and soundbanks (.sabl/.sabs): {name!r}")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise Failure(INPUT_INVALID, f"{owner}: seed file {name} needs a 64-hex sha256")
        p = seed_dir / name
        if p.is_symlink() or not p.is_file():
            if allow_missing_files:
                missing.append(name)
                continue
            raise Failure(INPUT_MISSING, f"{owner}: seed file is missing: {name}",
                          "A seed ships its package beside the manifest; a module published without it is distribution: private.")
        actual = sha256_file(job.input(p, limit=MAX_PACKAGE))
        if actual != digest:
            raise Failure("input_changed", f"{owner}: seed file {name} does not match its manifest hash",
                          "Regenerate the manifest with module declare, or restore the original package.")
        hashed[name] = p
    for key in ("roots", "embedded", "referenced"):
        rows = data[key]
        if not isinstance(rows, list) or len(rows) > MAX_ASSETS or not all(isinstance(r, str) and ASSET.match(r) for r in rows):
            raise Failure(INPUT_INVALID, f"{owner}: seed {key} is a list of 'type,name' rows")
        if len(set(rows)) != len(rows):
            raise Failure(INPUT_INVALID, f"{owner}: duplicate rows under seed {key}")
    if not data["roots"] or not set(data["roots"]) <= set(data["embedded"]):
        raise Failure(INPUT_INVALID, f"{owner}: seed roots must be a non-empty subset of embedded")
    strings = None
    if "strings" in data:
        rel = data["strings"]
        if not isinstance(rel, str) or "/" in rel or "\\" in rel or not rel.endswith(".str"):
            raise Failure(INPUT_INVALID, f"{owner}: seed strings is a .str file name beside the manifest")
        sp = seed_dir / rel
        if sp.is_symlink() or not sp.is_file():
            raise Failure(INPUT_MISSING, f"{owner}: seed strings file is missing: {rel}")
        strings = job.input(sp, limit=4 * 1024 * 1024)
        parse_strings(strings.read_text(encoding="utf-8", errors="replace"), owner)
    provides = data.get("provides", {})
    if not isinstance(provides, dict) or any(not isinstance(v, list) or not all(isinstance(x, str) for x in v) for v in provides.values()):
        raise Failure(INPUT_INVALID, f"{owner}: seed provides maps kinds to lists of names")
    return {"manifest": src, "directory": seed_dir, "package": hashed.get("mod.ff"), "files": hashed,
            "roots": list(data["roots"]), "embedded": list(data["embedded"]), "referenced": list(data["referenced"]),
            "provides": provides, "strings": strings, "private": bool(missing), "missing": missing}


def declare(package: Path, args, job: Job) -> dict:
    """Read a package back and write a seed manifest plus a draft declaration beside it in the job."""
    from types import SimpleNamespace

    from . import fastfiles

    src = job.input(package, limit=MAX_PACKAGE)
    if src.name != "mod.ff":
        raise Failure(INPUT_INVALID, "Point module declare at a file named mod.ff",
                      "A T6 fastfile is bound to its file name; rename nothing, copy the package as mod.ff beside its soundbanks.")
    banks = sorted(p for p in src.parent.iterdir() if p.is_file() and not p.is_symlink() and BANK.match(p.name))
    inspect = fastfiles.execute(SimpleNamespace(action="inspect", input=str(src), load=list(args.load or []), timeout=args.timeout), job)
    listing = (job.root / inspect["inventory_log"]).read_text(encoding="utf-8", errors="replace")
    embedded, referenced = parse_listing(listing)
    if not embedded:
        raise Failure(INPUT_INVALID, "The package lists no embedded assets; is this a T6 mod fastfile?")
    roots = roots_of(embedded)
    files = {"mod.ff": sha256_file(src)}
    for bank in banks:
        files[bank.name] = sha256_file(job.input(bank))
    manifest = {"schema": 1, "package": "mod.ff", "files": files, "roots": roots, "embedded": embedded,
                "referenced": referenced, "provides": provides_of(embedded),
                "source": {"tool": "OpenAssetTools Unlinker --list", "listing_sha256": sha256_file(job.root / inspect["inventory_log"])}}
    if any(row.startswith("localize,") for row in embedded):
        extract = fastfiles.execute(SimpleNamespace(action="extract", input=str(src), load=list(args.load or []), types="localize",
                                                    model_format="GLTF", image_format="DDS", timeout=args.timeout),
                                    Job(job.root / "strings", "ff extract", ["pat", "ff", "extract", str(src)], timeout=max(60, args.timeout)))
        found = sorted((job.root / "strings" / "assets").rglob("*.str"))
        if found:
            rows = {}
            for f in found:
                rows.update(parse_strings(f.read_text(encoding="utf-8", errors="replace"), src.parent.name))
            (job.root / "mod.str").write_text(write_strings(rows), encoding="utf-8")
            manifest["strings"] = "mod.str"
            manifest["provides"]["localize"] = sorted(rows)
    (job.root / "seed.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    weapons = manifest["provides"].get("weapons", [])
    mid = re.sub(r"[^a-z0-9_]", "_", (args.id or (weapons[0] if weapons else src.parent.name)).lower())[:64] or "module"
    game = getattr(args, "game", None) or titles.DEFAULT_TITLE
    titles.get(game)  # reject an unknown title before writing the draft
    draft = {
        "schema": 1, "id": mid, "version": "0.1.0", "game": game, "title": args.title or mid,
        "category": args.category or ("weapons" if weapons else "module"),
        "seed": "seed.json",
        "bases": [args.base] if args.base else ["<the base token this package was built and tested on>"],
        "maps": [args.map] if args.map else ["<the map id it was tested on>"],
        "dependencies": [], "conflicts": [],
        "resource_contract": {"threads": 0, "entities": 0, "hud": 0, "network_fields": 0},
        "menu_route": "<how a person reaches it in game>",
        "distribution": "seed",
    }
    (job.root / "module.json").write_text(json.dumps(draft, indent=2) + "\n", encoding="utf-8")
    return {"seed_manifest": "seed.json", "declaration_draft": "module.json", "package_sha256": files["mod.ff"],
            "soundbanks": [b.name for b in banks], "embedded": len(embedded), "referenced": len(referenced),
            "roots": len(roots), "provides": manifest["provides"],
            "strings": manifest.get("strings"),
            "next": ["Copy seed.json (and mod.str when present) beside the package and the soundbanks in the module directory.",
                     "Fill bases and maps in module.json from what was actually tested; the draft only guesses the id and category.",
                     "The declaration is not evidence: the package's own build, install and play receipts stay separate."],
            "verification": "OpenAssetTools listing parsed and hashed; the package was not linked, loaded or played"}
