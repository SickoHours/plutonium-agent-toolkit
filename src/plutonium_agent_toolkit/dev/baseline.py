"""``registry baseline``: a deterministic, static check of a module or composition directory.

A registry runs a baseline on a snapshot before it lists the entry, and a submitter's agent runs
the same command offline first. The baseline reads files and does nothing else: it executes
nothing in the tree, runs no backend, uses no model and touches no network. The same bytes always
produce the same ``baseline.json`` (the report carries no path of the machine, no time and no
job id, so two scans of one tree compare equal). It is not a security audit, certification,
warranty or endorsement; it names what a static read of the files can see, so a person can
review it.

Policy version ``1``, enforcement ``selective``: three finding ids block a listing
(``native-plugin``, ``download-and-execute``, ``path-escape``); every other finding, every
capability and every warning is reported for review. Outcomes::

    passed           no finding and no capability (warnings may be present)
    review-required  a non-blocking finding or a capability to look at
    needs-fixes      a blocking finding
    incomplete       something could not be read; treated like needs-fixes (fail closed)

Every row has the same shape::

    {"id": "native-plugin", "kind": "finding", "blocking": true,
     "file": "tools/hook.txt", "line": null, "evidence": "PE executable header (MZ)"}

Rules, from files alone. Findings: ``native-plugin`` (a file whose first bytes are a PE, ELF or
Mach-O executable, whatever its name; or text naming Plutonium's plugins folder or a
``plugins/<x>.dll`` path), ``download-and-execute`` (``iex (iwr ...)``, ``Invoke-Expression``,
``curl ... | sh``, ``wget ... | sh``, or a file a script downloads and later starts in the same
file with ``Start-Process``, ``&`` or a dot-slash prefix), ``path-escape`` (a link anywhere in
the tree; an absolute path or a Windows drive in any declared path; a ``..`` segment in a path
the formats confine to their own directory: ``recipe`` and ``seed`` in ``module.json``,
``source``, ``target`` and ``loads`` in ``project.json``; and any declared directory or file
that resolves outside the scanned directory. A composition names sibling directories with
``..`` by design (``docs/MODULES.md``), so a pack is scanned from the directory that holds the
pack and every member it names, such as the repository root; scanned alone, its siblings are
outside the snapshot and are reported), ``unpinned-acquisition`` (an http(s) URL to an archive,
package or installer with no SHA-256 on the same or the next five lines) and
``declaration-mismatch`` (a declaration naming another repository or commit than the listing,
or a ``source`` whose fields are not strings of the documented form; a declared path missing on
disk; ``bases`` or ``maps`` empty or not lists; a declaration that is not valid JSON).
Capabilities: ``installer``, ``bundled-package``, ``lua-ui``, ``file-io``, ``client-dvar``,
``function-replacement``, ``command-hook``, ``global-tooling``, ``bundled-assets`` and
``large-text``. Warning: ``no-resource-contract``. ``docs/REGISTRY.md`` has the table.

Reading is careful about the tree changing under the scan: every file is opened without
following links and without blocking, its open descriptor must describe the same regular file
the listing saw (otherwise the entry is ``unreadable`` and the outcome ``incomplete``), and bytes
are counted against the tree bound as they are read, so a file that grows after the listing
cannot push the tree past ``MAX_BYTES`` (``input_limit``).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from bisect import bisect_right
from pathlib import Path, PurePosixPath, PureWindowsPath

from ..core.errors import INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING, Failure
from ..core.jobs import Job

POLICY_VERSION = "1"
ENFORCEMENT = "selective"
BLOCKING = ("native-plugin", "download-and-execute", "path-escape")
FINDINGS = BLOCKING + ("unpinned-acquisition", "declaration-mismatch")
CAPABILITIES = ("installer", "bundled-package", "lua-ui", "file-io", "client-dvar", "function-replacement",
                "command-hook", "global-tooling", "bundled-assets", "large-text")
WARNINGS = ("no-resource-contract",)
OUTCOMES = ("passed", "review-required", "needs-fixes", "incomplete")
DISCLAIMER = "A baseline is a static check of files; it is not a security audit, certification, warranty or endorsement."

MAX_FILES = 20000
MAX_BYTES = 2 * 1024**3
MAX_TEXT = 4 * 1024 * 1024
SNIFF = 8 * 1024
CHUNK = 1024 * 1024
ASSETS_THRESHOLD = 8 * 1024 * 1024
EVIDENCE = 160
ROWS_PER_FILE_AND_RULE = 20
MAX_DOWNLOADED_NAMES = 64
DEADLINE_EVERY = 200
# No link is followed, no pipe blocks, no text mode, no inheritance; flags absent on a platform are 0.
OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)

# PE, ELF, and Mach-O (32/64-bit in both byte orders, and the fat/universal header).
EXECUTABLE_MAGIC = (
    (b"MZ", "PE executable header (MZ)"),
    (b"\x7fELF", "ELF executable header"),
    (b"\xfe\xed\xfa\xce", "Mach-O executable header (feedface)"),
    (b"\xfe\xed\xfa\xcf", "Mach-O executable header (feedfacf)"),
    (b"\xce\xfa\xed\xfe", "Mach-O executable header (cefaedfe)"),
    (b"\xcf\xfa\xed\xfe", "Mach-O executable header (cffaedfe)"),
    (b"\xca\xfe\xba\xbe", "Mach-O universal header (cafebabe)"),
)
PLUGIN_TEXT = (re.compile(r"plutonium[\\/]+plugins", re.I), re.compile(r"\bplugins[\\/][^\s]+\.dll\b", re.I))
DOWNLOAD_EXEC = (
    re.compile(r"iex\s*\(\s*(?:iwr|invoke-webrequest)", re.I),
    re.compile(r"invoke-expression", re.I),
    re.compile(r"\bcurl\s[^\n|]*\|\s*(?:sh|bash|zsh)\b", re.I),
    re.compile(r"\bwget\s[^\n|]*\|\s*(?:sh|bash|zsh)\b", re.I),
)
DOWNLOAD_LINE = re.compile(r"\b(?:curl|wget|invoke-webrequest|iwr|start-bitstransfer|downloadfile)\b", re.I)
DOWNLOAD_TARGET = re.compile(r"(?:^|\s)(?:-o|--output|-OutFile|-Destination)\s+[\"']?([^\s\"']+)", re.I)
URL = re.compile(r"https?://[^\s\"'<>()\[\]]+", re.I)
ARCHIVE_SUFFIXES = (".zip", ".tar.gz", ".tgz", ".7z", ".rar", ".ff", ".ipak", ".exe", ".msi")
SHA256 = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])")
SCRIPT_RULES = (
    ("file-io", re.compile(r"\bfs_(?:fopen|write|writeline|read|readline|remove|listfiles|fclose)\b", re.I)),
    ("client-dvar", re.compile(r"\bsetclientdvars?\b", re.I)),
    ("function-replacement", re.compile(r"\breplacefunc\b", re.I)),
    ("command-hook", re.compile(r"\bnotifyonplayercommand\b", re.I)),
)
SCRIPT_SUFFIXES = {".gsc", ".csc", ".gsh"}
PACKAGE_SUFFIXES = {".ff", ".ipak", ".sabl", ".sabs"}
INSTALLER_SUFFIXES = {".bat", ".cmd", ".ps1", ".sh", ".exe", ".msi"}
INSTALLER_STEMS = ("install", "setup", "uninstall")
UI_DIRS = {"ui", "ui_mp"}
DECLARATIONS = {"module.json": "module", "composition.json": "composition", "project.json": "recipe"}
PATH_KEYS = ("source", "target", "recipe", "seed", "path")
LIST_KEYS = ("modules", "loads")
GLOBAL_PREFIX = "raw/scripts/"
COMMIT = re.compile(r"^[0-9a-f]{40}\Z")


class Replaced(OSError):
    """The entry changed between the directory listing and the open; it is reported as unreadable."""


def add_parser(actions, common):
    q = actions.add_parser("baseline", help="Static check of a module or composition directory before it is listed; runs nothing in the tree")
    q.add_argument("directory", help="Module or composition directory to scan (for a pack: the directory holding the pack and every member it names)")
    q.add_argument("--repository", help="The https repository URL the listing will name; compared with module.json source.repository")
    q.add_argument("--commit", help="The 40-hex commit the listing will name; compared with module.json source.commit")
    common(q)


# ----- rows -----------------------------------------------------------------------------

def _clip(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= EVIDENCE else text[:EVIDENCE - 3] + "..."


def _excerpt(line: str, start: int, end: int) -> str:
    """A short window around a match, never the whole line when it is long."""
    s, e = max(0, start - 40), min(len(line), end + 80)
    return ("..." if s > 0 else "") + line[s:e].strip() + ("..." if e < len(line) else "")


def _kind(rule: str) -> str:
    if rule in FINDINGS:
        return "finding"
    if rule in CAPABILITIES:
        return "capability"
    if rule in WARNINGS:
        return "warning"
    raise ValueError(f"unknown baseline rule {rule!r}")


class Rows:
    """Findings, capabilities and warnings: one row per (file, line, id), bounded per file and rule.

    Findings keep up to ``ROWS_PER_FILE_AND_RULE`` rows per file; capabilities and warnings are
    one row per file. Rows beyond the bound are counted under ``truncated`` so nothing is dropped
    silently."""

    def __init__(self):
        self.rows: list[dict] = []
        self.truncated: dict[tuple, int] = {}
        self._seen: set[tuple] = set()
        self._per: dict[tuple, int] = {}

    def add(self, rule: str, file: str, line: int | None, evidence: str) -> None:
        kind = _kind(rule)
        key = (file, line, rule)
        if key in self._seen:
            return
        self._seen.add(key)
        cap = ROWS_PER_FILE_AND_RULE if kind == "finding" else 1
        count = self._per.get((file, rule), 0)
        if count >= cap:
            self.truncated[(file, rule)] = self.truncated.get((file, rule), 0) + 1
            return
        self._per[(file, rule)] = count + 1
        self.rows.append({"id": rule, "kind": kind, "blocking": rule in BLOCKING, "file": file, "line": line, "evidence": _clip(evidence)})

    def sorted(self, kind: str) -> list[dict]:
        return sorted((r for r in self.rows if r["kind"] == kind), key=lambda r: (r["file"], -1 if r["line"] is None else r["line"], r["id"]))

    def omitted(self) -> list[dict]:
        return [{"file": f, "id": r, "omitted": n} for (f, r), n in sorted(self.truncated.items())]


# ----- text rules -----------------------------------------------------------------------

def _line_starts(text: str) -> list[int]:
    starts = [0]
    pos = text.find("\n")
    while pos != -1:
        starts.append(pos + 1)
        pos = text.find("\n", pos + 1)
    return starts


def _basename(value: str) -> str:
    name = value.split("#", 1)[0].split("?", 1)[0].rstrip(".,;:!)'\"")
    return re.split(r"[\\/]+", name)[-1].strip().lower()


def _scan_text(rows: Rows, rel: str, suffix: str, text: str) -> None:
    lines = text.split("\n")
    starts = _line_starts(text)

    def where(pos: int) -> tuple[int, str, int]:
        """1-based line number, the line, and the column of an offset into ``text``."""
        n = bisect_right(starts, pos)
        return n, lines[n - 1], pos - starts[n - 1]

    def add_match(rule: str, m: re.Match) -> None:
        n, line, col = where(m.start())
        rows.add(rule, rel, n, _excerpt(line, col, col + len(m.group(0))))

    for pattern in PLUGIN_TEXT:
        for m in pattern.finditer(text):
            add_match("native-plugin", m)
    for pattern in DOWNLOAD_EXEC:
        for m in pattern.finditer(text):
            add_match("download-and-execute", m)
    # A file the script downloads and later starts. The downloaded name is the value after
    # -o/--output/-OutFile/-Destination on a download line (curl, wget, Invoke-WebRequest, iwr,
    # Start-BitsTransfer, DownloadFile), or the file name of a URL on that line; a later (or the
    # same) line that names it after Start-Process, & or .\ (./) is the finding.
    downloaded: dict[str, int] = {}
    for number, line in enumerate(lines, 1):
        if len(downloaded) >= MAX_DOWNLOADED_NAMES or not DOWNLOAD_LINE.search(line):
            continue
        for m in DOWNLOAD_TARGET.finditer(line):
            downloaded.setdefault(_basename(m.group(1)), number)
        for m in URL.finditer(line):
            downloaded.setdefault(_basename(m.group(0)), number)
    for name, first in sorted(downloaded.items()):
        if not name:
            continue
        started = re.compile(r"(?:start-process\s+(?:-filepath\s+)?|&\s*|\.[\\/])[\"']?(?:[^\s\"']*[\\/])?" + re.escape(name) + r"(?![\w.-])", re.I)
        for index in range(first - 1, len(lines)):
            m = started.search(lines[index])
            if m:
                rows.add("download-and-execute", rel, index + 1,
                         _excerpt(lines[index], m.start(), m.end()) + f" (downloaded on line {first})")
                break
    for m in URL.finditer(text):
        target = m.group(0).rstrip(".,;:!?)'\"").split("#", 1)[0].split("?", 1)[0].lower()
        if not target.endswith(ARCHIVE_SUFFIXES):
            continue
        n, line, col = where(m.start())
        if SHA256.search("\n".join(lines[n - 1:n + 5])):
            continue
        rows.add("unpinned-acquisition", rel, n, _excerpt(line, col, col + len(m.group(0))))
    if suffix in SCRIPT_SUFFIXES:
        for rule, pattern in SCRIPT_RULES:
            m = pattern.search(text)
            if m:
                add_match(rule, m)


# ----- declarations ---------------------------------------------------------------------

def _absolute_or_drive(value: str) -> bool:
    """Rooted on either OS, or carrying a Windows drive (``C:outside/x`` is drive-relative and
    would resolve outside the tree on Windows)."""
    windows = PureWindowsPath(value)
    return value.startswith(("/", "\\")) or PurePosixPath(value).is_absolute() or windows.is_absolute() or bool(windows.drive)


def _parts(value: str) -> list[str]:
    return [p for p in re.split(r"[\\/]+", value) if p and p != "."]


def _global(value: str) -> bool:
    """The global scripts folder itself or anything inside it: Plutonium loads it for every profile."""
    norm = value.replace("\\", "/").lower()
    while norm.startswith("./"):
        norm = norm[2:]
    return norm.rstrip("/") == GLOBAL_PREFIX.rstrip("/") or norm.startswith(GLOBAL_PREFIX)


def _inside(full: Path, root: Path) -> bool:
    """Lexical: nothing outside the tree is touched to answer this."""
    return Path(os.path.normpath(str(full))).is_relative_to(root)


def _line_of(text: str, value) -> int | None:
    pos = text.find(json.dumps(value))
    return None if pos < 0 else text.count("\n", 0, pos) + 1


def _reject_constant(name: str):
    raise ValueError(f"{name} is not valid JSON")


def _load_json(rows: Rows, rel: str, text: str):
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except ValueError as exc:
        rows.add("declaration-mismatch", rel, getattr(exc, "lineno", None), f"not valid JSON: {getattr(exc, 'msg', exc)}")
        return None


def _paths(data, kind: str):
    """Every path-like string in a declaration, as (field, value, confined).

    A confined path must stay inside its own directory. A composition's members and loads may
    name siblings with ``..`` (docs/MODULES.md), so they are not confined by ``..``; every path,
    confined or not, must still resolve inside the scanned directory."""
    def walk(node, in_member: bool):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in PATH_KEYS and isinstance(value, str):
                    yield key, value, not (kind == "composition" and in_member and key == "path")
                elif key in LIST_KEYS and isinstance(value, list):
                    for item in value:
                        if isinstance(item, str):
                            yield key, item, kind != "composition"
                        else:
                            yield from walk(item, kind == "composition" and key == "modules")
                else:
                    yield from walk(value, False)
        elif isinstance(node, list):
            for item in node:
                yield from walk(item, in_member)
    yield from walk(data, False)


def _check_path(rows: Rows, rel: str, text: str, directory: Path, root: Path, field: str, value: str, confined: bool) -> None:
    line = _line_of(text, value)
    if not value.strip():
        rows.add("declaration-mismatch", rel, line, f"{field}: empty path")
        return
    if _absolute_or_drive(value):
        rows.add("path-escape", rel, line, f"{field}: absolute path or Windows drive {value!r}")
        return
    parts = _parts(value)
    if ".." in parts and confined:
        rows.add("path-escape", rel, line, f"{field}: parent segment in {value!r}")
        return
    if _global(value):
        rows.add("global-tooling", rel, line, f"{field}: {value!r} loads for every profile")
    if field == "target":
        return  # a zone target names a place inside the package, not a file on disk
    full = directory.joinpath(*parts) if parts else directory
    if not _inside(full, root):
        rows.add("path-escape", rel, line, f"{field}: {value!r} resolves outside the scanned directory; scan from the directory that holds every member")
        return
    if full.is_symlink():
        rows.add("path-escape", rel, line, f"{field}: {value!r} is a link")
    elif not full.exists():
        rows.add("declaration-mismatch", rel, line, f"{field}: {value!r} is missing on disk")


def _check_source(rows: Rows, rel: str, text: str, source, expected: dict) -> None:
    """``source`` must be an object whose present fields have the documented form; only then are
    they compared with the listing's values. A number or a list where a string belongs is a
    mismatch, whether or not ``--repository`` / ``--commit`` were given."""
    if not isinstance(source, dict):
        rows.add("declaration-mismatch", rel, _line_of(text, "source"), f"source is not an object: {source!r}")
        return
    forms = (("repository", lambda v: isinstance(v, str) and v.startswith("https://") and len(v) <= 512, "an https URL"),
             ("commit", lambda v: isinstance(v, str) and bool(COMMIT.match(v)), "a 40-character lowercase hex commit id"))
    valid = {}
    for key, ok, what in forms:
        if key not in source:
            continue
        value = source[key]
        if not ok(value):
            rows.add("declaration-mismatch", rel, _line_of(text, value) if isinstance(value, str) else _line_of(text, key),
                     f"source.{key} is not {what}: {value!r}")
            continue
        valid[key] = value
    repository, commit = valid.get("repository"), valid.get("commit")
    if expected["repository"] and repository is not None and repository.rstrip("/").lower() != expected["repository"]:
        rows.add("declaration-mismatch", rel, _line_of(text, repository), f"source.repository {repository} differs from --repository {expected['repository']}")
    if expected["commit"] and commit is not None and commit != expected["commit"]:
        rows.add("declaration-mismatch", rel, _line_of(text, commit), f"source.commit {commit[:12]} differs from --commit {expected['commit'][:12]}")


def _check_declaration(rows: Rows, rel: str, kind: str, text: str, directory: Path, root: Path, expected: dict):
    data = _load_json(rows, rel, text)
    if data is None:
        return None
    if not isinstance(data, dict):
        rows.add("declaration-mismatch", rel, None, "expected a JSON object")
        return data
    if kind == "module":
        for key in ("bases", "maps"):
            if key in data and (not isinstance(data[key], list) or not data[key]):
                rows.add("declaration-mismatch", rel, _line_of(text, key), f"{key} is present but empty or not a list")
        if "resource_contract" not in data:
            rows.add("no-resource-contract", rel, None, "module.json declares no resource_contract (docs/MODULES.md)")
        if "source" in data:
            _check_source(rows, rel, text, data["source"], expected)
    for field, value, confined in _paths(data, kind):
        _check_path(rows, rel, text, directory, root, field, value, confined)
    return data


def _module_summary(rel: str, data) -> dict:
    if not isinstance(data, dict):
        return {"file": rel, "kind": "module", "valid": False}
    payload = "recipe" if "recipe" in data else "seed" if "seed" in data else None
    return {"file": rel, "kind": "module", "valid": True, "id": data.get("id"), "version": data.get("version"),
            "title": data.get("title"), "category": data.get("category"), "module_kind": data.get("kind"),
            "payload": payload, "payload_path": data.get(payload) if payload else None,
            "distribution": data.get("distribution", "seed" if payload == "seed" else "source"),
            "bases": data.get("bases"), "maps": data.get("maps"),
            "dependencies": data.get("dependencies", []), "conflicts": data.get("conflicts", []),
            "source": data.get("source"), "resource_contract": "resource_contract" in data}


def _composition_summary(rel: str, data, directory: Path, root: Path) -> dict:
    if not isinstance(data, dict):
        return {"file": rel, "kind": "composition", "valid": False}
    members = []
    items = data.get("modules") if isinstance(data.get("modules"), list) else []
    for item in items:
        if isinstance(item, str):
            row = {"path": item}
        elif isinstance(item, dict):
            row = {"path": item.get("path")} | {k: item[k] for k in ("name", "commit", "role") if k in item}
        else:
            row = {"path": None}
        path = row["path"]
        if isinstance(path, str) and path.strip() and not _absolute_or_drive(path):
            full = directory.joinpath(*_parts(path)) if _parts(path) else directory
            row["outside_scan_root"] = not _inside(full, root)
            if not row["outside_scan_root"]:  # nothing outside the tree is touched
                row["exists"] = full.is_dir() and not full.is_symlink()
                row["declares"] = next((n for n in ("module.json", "composition.json") if (full / n).is_file()), None) if row["exists"] else None
        members.append(row)
    loads = data.get("loads") if isinstance(data.get("loads"), list) else []
    return {"file": rel, "kind": "composition", "valid": True, "name": data.get("name"), "title": data.get("title"),
            "base": data.get("base"), "map": data.get("map"), "members": members,
            "loads": [x for x in loads if isinstance(x, str)], "budget": data.get("budget")}


# ----- the walk -------------------------------------------------------------------------

def _root(text: str, job: Job) -> Path:
    root = Path(text).expanduser().absolute()
    if not root.exists():
        raise Failure(INPUT_MISSING, f"Directory is missing: {root}")
    if not root.is_dir():
        raise Failure(INPUT_INVALID, f"Not a directory: {root}", "Give the module or composition directory, not a file in it.")
    root = root.resolve()
    if job.root.is_relative_to(root):
        raise Failure(INPUT_INVALID, "The output directory must be outside the directory being scanned",
                      "Choose an --output beside the tree, never inside it; the scan would otherwise read its own receipt.")
    return root


def _expected(args) -> dict:
    repository = getattr(args, "repository", None)
    commit = getattr(args, "commit", None)
    if repository is not None and (not isinstance(repository, str) or not repository.startswith("https://") or len(repository) > 512):
        raise Failure(INPUT_INVALID, "--repository is an https URL of at most 512 characters")
    if commit is not None and (not isinstance(commit, str) or not COMMIT.match(commit.lower())):
        raise Failure(INPUT_INVALID, "--commit is a 40-character hex commit id", "A short id, a tag or a branch name is not a pin.")
    return {"repository": repository.rstrip("/").lower() if repository else None, "commit": commit.lower() if commit else None}


def _lstat(entry: Path) -> os.stat_result:
    """The listing's view of an entry; patched in tests that simulate a tree changing under the scan."""
    return entry.lstat()


def _read(path: Path, info: os.stat_result, budget: int) -> tuple[str, bytes, int, bytes | None]:
    """sha256, the first bytes, the byte count, and the whole content when it is small enough to scan.

    The descriptor is opened without following links and without blocking; its ``fstat`` must
    describe a regular file and, on POSIX, the same inode the listing saw, otherwise the entry is
    ``Replaced`` and reported as unreadable. Bytes count against ``budget`` (the tree bound less
    what was already read) as they are read, so a file that grew after the listing cannot push the
    tree past the bound: exceeding it is ``input_limit``, like an oversized tree at the listing."""
    fd = os.open(path, OPEN_FLAGS)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise Replaced(None, "not a regular file when opened")
        if os.name != "nt" and (opened.st_ino, opened.st_dev) != (info.st_ino, info.st_dev):
            raise Replaced(None, "replaced between listing and reading")
    except BaseException:
        os.close(fd)
        raise
    digest = hashlib.sha256()
    total = 0

    def take(block: bytes) -> None:
        nonlocal total
        total += len(block)
        if total > budget:
            raise Failure(INPUT_LIMIT, f"The tree exceeds {MAX_BYTES} bytes; nothing was judged",
                          "A file grew while it was read; the bound applies to the bytes actually read.")
        digest.update(block)

    with os.fdopen(fd, "rb") as stream:
        if info.st_size <= MAX_TEXT:
            data = stream.read(MAX_TEXT + 1)
            take(data)
            if total <= MAX_TEXT:
                return digest.hexdigest(), data[:SNIFF], total, data
        else:
            data = stream.read(SNIFF)
            take(data)
        # Larger than the text bound (or grown since it was listed): hash the rest, scan nothing.
        while block := stream.read(CHUNK):
            take(block)
        return digest.hexdigest(), data[:SNIFF], total, None


def _is_link(entry: Path) -> bool:
    if entry.is_symlink():
        return True
    junction = getattr(entry, "is_junction", None)
    return bool(os.name == "nt" and junction and junction())


def execute(args, job: Job) -> dict:
    root = _root(args.directory, job)
    expected = _expected(args)
    rows = Rows()
    unreadable: list[dict] = []
    skipped: list[dict] = []
    digests: list[tuple[str, str]] = []
    counts = {"files": 0, "bytes": 0, "text_files": 0, "binary_files": 0}
    binary_total = 0
    declarations: list[tuple[str, str, Path, str]] = []  # rel, kind, directory, text
    errors: list[OSError] = []
    seen = 0

    def rel_of(path: Path) -> str:
        return path.relative_to(root).as_posix()

    for directory, dirs, files in os.walk(root, onerror=errors.append, followlinks=False):
        job.check_deadline()
        base = Path(directory)
        keep = []
        for name in sorted(dirs):
            entry = base / name
            rel = rel_of(entry)
            if name == ".git":
                skipped.append({"path": rel, "reason": "git metadata; never part of a snapshot, not scanned"})
            elif _is_link(entry):
                rows.add("path-escape", rel, None, "a link to a directory; not followed")
                skipped.append({"path": rel, "reason": "link; not followed"})
            else:
                keep.append(name)
        dirs[:] = keep
        for name in sorted(files):
            entry = base / name
            rel = rel_of(entry)
            seen += 1
            if seen % DEADLINE_EVERY == 0:
                job.check_deadline()
            if name == ".git":
                skipped.append({"path": rel, "reason": "git metadata; never part of a snapshot, not scanned"})
                continue
            try:
                info = _lstat(entry)
            except OSError as exc:
                unreadable.append({"path": rel, "reason": exc.strerror or str(exc)})
                continue
            if stat.S_ISLNK(info.st_mode) or _is_link(entry):
                rows.add("path-escape", rel, None, "a link; not followed")
                skipped.append({"path": rel, "reason": "link; not followed"})
                continue
            if not stat.S_ISREG(info.st_mode):
                unreadable.append({"path": rel, "reason": "not a regular file"})
                continue
            counts["files"] += 1
            if counts["files"] > MAX_FILES:
                raise Failure(INPUT_LIMIT, f"The tree holds more than {MAX_FILES} files; nothing was judged")
            if counts["bytes"] + info.st_size > MAX_BYTES:
                raise Failure(INPUT_LIMIT, f"The tree exceeds {MAX_BYTES} bytes; nothing was judged")
            try:
                digest, head, size, content = _read(entry, info, MAX_BYTES - counts["bytes"])
            except OSError as exc:
                counts["files"] -= 1
                unreadable.append({"path": rel, "reason": exc.strerror or str(exc)})
                continue
            counts["bytes"] += size
            digests.append((rel, digest))
            suffix = entry.suffix.lower()
            stem = entry.stem.lower()
            for magic, label in EXECUTABLE_MAGIC:
                if head.startswith(magic):
                    rows.add("native-plugin", rel, None, label)
                    break
            if stem.startswith(INSTALLER_STEMS) or suffix in INSTALLER_SUFFIXES:
                rows.add("installer", rel, None, f"file name {name!r}")
            if suffix in PACKAGE_SUFFIXES:
                rows.add("bundled-package", rel, None, f"{suffix} package, {size} bytes")
            if suffix == ".lua" or UI_DIRS & {part.lower() for part in Path(rel).parts[:-1]}:
                rows.add("lua-ui", rel, None, "Lua file or ui/ui_mp path")
            if b"\x00" in head:
                counts["binary_files"] += 1
                binary_total += size
                if name in DECLARATIONS:
                    rows.add("declaration-mismatch", rel, None, "declaration is not a text file")
                continue
            counts["text_files"] += 1
            if content is None:
                rows.add("large-text", rel, None, f"{size} bytes of text; larger than {MAX_TEXT} bytes, not pattern-scanned")
                if name in DECLARATIONS:
                    rows.add("declaration-mismatch", rel, None, f"declaration larger than {MAX_TEXT} bytes; not checked")
                continue
            text = content.decode("utf-8", errors="replace")
            _scan_text(rows, rel, suffix, text)
            if name in DECLARATIONS:
                declarations.append((rel, DECLARATIONS[name], base, text))
    for exc in errors:
        path = getattr(exc, "filename", None)
        rel = rel_of(Path(path)) if path and Path(path).is_relative_to(root) else str(path)
        unreadable.append({"path": rel, "reason": exc.strerror or str(exc)})
    if binary_total > ASSETS_THRESHOLD:
        rows.add("bundled-assets", ".", None, f"{counts['binary_files']} binary files, {binary_total} bytes in total (above {ASSETS_THRESHOLD})")

    summary = None
    nested = []
    for rel, kind, directory, text in declarations:
        data = _check_declaration(rows, rel, kind, text, directory, root, expected)
        if kind == "recipe":
            continue
        row = _module_summary(rel, data) if kind == "module" else _composition_summary(rel, data, directory, root)
        if directory == root and (kind == "module" or summary is None):
            summary = row
        else:
            nested.append(row)
        if directory == root:
            job.input(root / rel, limit=MAX_TEXT)  # the declaration's hash goes into the receipt
    if summary is None:
        # A root declaration that was binary, oversized or unreadable still names itself in the summary.
        for name, kind in (("module.json", "module"), ("composition.json", "composition")):
            if (root / name).is_file() and not (root / name).is_symlink():
                summary = {"file": name, "kind": kind, "valid": False}
                break
    nested.sort(key=lambda r: r["file"])

    unreadable.sort(key=lambda r: r["path"])
    skipped.sort(key=lambda r: r["path"])
    findings, capabilities, warnings = rows.sorted("finding"), rows.sorted("capability"), rows.sorted("warning")
    if unreadable:
        outcome = "incomplete"
    elif any(r["blocking"] for r in findings):
        outcome = "needs-fixes"
    elif findings or capabilities:
        outcome = "review-required"
    else:
        outcome = "passed"
    tree = hashlib.sha256()
    for rel, digest in sorted(digests):
        tree.update(f"{digest}  {rel}\n".encode("utf-8"))
    report = {
        "schema_version": 1, "policy_version": POLICY_VERSION, "enforcement": ENFORCEMENT, "blocking_ids": list(BLOCKING),
        "outcome": outcome, "blocked": outcome in ("needs-fixes", "incomplete"),
        "findings": findings, "capabilities": capabilities, "warnings": warnings, "truncated": rows.omitted(),
        "scanned": counts, "tree_sha256": tree.hexdigest(), "unreadable": unreadable, "skipped": skipped,
        "declaration": summary, "nested_declarations": nested,
        "expected": {"repository": expected["repository"], "commit": expected["commit"]},
        "bounds": {"max_files": MAX_FILES, "max_bytes": MAX_BYTES, "max_text_bytes": MAX_TEXT, "rows_per_file_and_rule": ROWS_PER_FILE_AND_RULE},
        "not_a_security_audit": True, "disclaimer": DISCLAIMER,
        "verification": "static read of every file under the directory; nothing executed, no backend, no network, no model",
    }
    (job.root / "baseline.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return {**report, "report": "baseline.json", "directory": str(root),
            "next": ["Read baseline.json: every row names the file, the line and the evidence; blocking rows must be fixed before listing.",
                     "Rerun into a new --output after a change; the same bytes always give the same report (compare tree_sha256).",
                     "A passed or review-required baseline says nothing about play: build, install and test are separate facts."]}
