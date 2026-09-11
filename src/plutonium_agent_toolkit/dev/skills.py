"""``dev install-skills``: put the toolkit's skills where the coding-agent harnesses on this
machine discover them, with a receipt, never overwriting a file this route did not write.

A skill is a directory holding ``SKILL.md`` (``skills/<name>/`` in the checkout). Every harness
below reads such directories from a user-level location; the paths are the ones each harness
documents. A harness is detected by its home directory existing; no harness executable is run.

    claude    ~/.claude/skills            Claude Code
    codex     ~/.codex/skills             Codex CLI
    gemini    ~/.gemini/skills            Gemini CLI
    opencode  ~/.config/opencode/skills   OpenCode
    cursor    ~/.cursor/skills            Cursor
    hermes    ~/.hermes/skills            Hermes Agent
    agents    ~/.agents/skills            the shared Agent Skills location several of the above also read

Each installed ``SKILL.md`` is the checkout's file plus one paragraph after its frontmatter that
names the checkout it came from, because the skills refer to ``docs/`` and ``CONTEXT.md`` by
paths relative to that checkout. ``<toolkit home>/skills/installed.json`` records every file this
route wrote with its hash. A later run rewrites a file only when its bytes still match that
record, refuses a file that differs (someone edited it) or that it never wrote, and writes a
receipt for every run under ``<toolkit home>/skills/receipts/``. The home directory is resolved
once (a home that is itself a link is used at its real location, and the result names both);
below it nothing is written through a link, and a path component that is not a directory
refuses the file. Refused files fail the invocation with ``output_exists`` after everything else
was written. Every file the route reads or hashes is bounded by ``MAX_SKILL_FILE_BYTES``.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

from .. import __version__
from ..core import config
from ..core.envelope import now
from ..core.errors import INPUT_INVALID, INPUT_LIMIT, INPUT_MISSING, OUTPUT_EXISTS, Failure

# id -> (label, home marker directory, skills directory), both relative to the user's home.
HARNESSES = {
    "claude": ("Claude Code", ".claude", ".claude/skills"),
    "codex": ("Codex CLI", ".codex", ".codex/skills"),
    "gemini": ("Gemini CLI", ".gemini", ".gemini/skills"),
    "opencode": ("OpenCode", ".config/opencode", ".config/opencode/skills"),
    "cursor": ("Cursor", ".cursor", ".cursor/skills"),
    "hermes": ("Hermes Agent", ".hermes", ".hermes/skills"),
    "agents": ("Agent Skills shared location", ".agents", ".agents/skills"),
}
MAX_SKILL_FILES = 64
MAX_SKILL_FILE_BYTES = 1024 * 1024
REPOSITORY = "https://github.com/SickoHours/plutonium-agent-toolkit"


# ----- source -----------------------------------------------------------------------------

def _is_checkout(path: Path) -> bool:
    return (path / "skills").is_dir() and (path / "AGENTS.md").is_file() and (path / "CONTEXT.md").is_file()


def source_root(explicit: str | None = None) -> Path:
    """The toolkit checkout whose ``skills/`` directory is installed: ``--source``, or the checkout this
    installation runs from (an editable install). A wheel carries no skills and no docs."""
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_absolute():
            raise Failure(INPUT_INVALID, "--source must be an absolute path to a toolkit checkout")
        p = p.resolve()
        if not _is_checkout(p):
            raise Failure(INPUT_MISSING, f"{p} is not a toolkit checkout (no skills/, AGENTS.md and CONTEXT.md)")
        return p
    candidate = Path(__file__).resolve().parents[3]
    if _is_checkout(candidate):
        return candidate
    raise Failure(INPUT_MISSING, "The skills are not beside this installation; pass --source <toolkit checkout>",
                  f"Skills live in the repository (skills/), not in the wheel: clone {REPOSITORY} and point --source at it.")


def skills_in(root: Path) -> list[dict]:
    """Every skill directory in the checkout with its regular files, bounded and link-free."""
    rows = []
    for d in sorted((root / "skills").iterdir()):
        if d.is_symlink() or not d.is_dir() or not (d / "SKILL.md").is_file():
            continue
        files = []
        for p in sorted(d.rglob("*")):
            if p.is_symlink():
                raise Failure(INPUT_INVALID, f"Skill {d.name} holds a link: {p.relative_to(d).as_posix()}")
            if p.is_dir():
                continue
            if not p.is_file():
                raise Failure(INPUT_INVALID, f"Skill {d.name} holds a special file: {p.relative_to(d).as_posix()}")
            if p.stat().st_size > MAX_SKILL_FILE_BYTES:
                raise Failure(INPUT_LIMIT, f"Skill file exceeds {MAX_SKILL_FILE_BYTES} bytes: {p}")
            files.append(p.relative_to(d).as_posix())
            if len(files) > MAX_SKILL_FILES:
                raise Failure(INPUT_LIMIT, f"Skill {d.name} holds more than {MAX_SKILL_FILES} files")
        rows.append({"name": d.name, "directory": d, "files": files})
    if not rows:
        raise Failure(INPUT_MISSING, f"No skill directories under {root / 'skills'}")
    return rows


def stamp(text: str, root: Path, name: str) -> str:
    """The installed SKILL.md: the checkout's file with one paragraph after the frontmatter naming the
    checkout. Line endings are normalised to LF first, so a checkout that converted them (Windows
    autocrlf) installs the same bytes as any other and the frontmatter is found either way."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise Failure(INPUT_INVALID, f"Skill {name}: SKILL.md must start with YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise Failure(INPUT_INVALID, f"Skill {name}: SKILL.md frontmatter is not closed")
    head, body = text[:end + 5], text[end + 5:]
    note = (f"> Installed by `pat dev install-skills` from the Plutonium Agent Toolkit checkout at `{root}`"
            f" (toolkit {__version__}). The `docs/`, `CONTEXT.md`, `examples/` and `skills/` paths in this skill"
            " are relative to that checkout. `pat` runs from any directory; `pat manifest --json` lists every route.\n\n")
    return head + "\n" + note + body.lstrip("\n")


def rendered(skill: dict, root: Path) -> dict[str, bytes]:
    """Relative path -> bytes as they would be installed."""
    out = {}
    for rel in skill["files"]:
        data = (skill["directory"] / rel).read_bytes()
        if rel == "SKILL.md":
            data = stamp(data.decode("utf-8"), root, skill["name"]).encode("utf-8")
        if len(data) > MAX_SKILL_FILE_BYTES:
            raise Failure(INPUT_LIMIT, f"Skill file exceeds {MAX_SKILL_FILE_BYTES} bytes as installed: {skill['name']}/{rel}",
                          "The installed copy carries a short note after the frontmatter; keep the source below the limit.")
        out[rel] = data
    return out


# ----- state under the toolkit home ------------------------------------------------------------

MAX_RECORD_BYTES = 8 * 1024 * 1024


def state_dir(create: bool = False) -> Path:
    """``<toolkit home>/skills``. Created only when something is about to be written there, so a
    plan or a status read leaves a fresh (or read-only) home untouched."""
    p = config.home() / "skills"
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def _manifest_path() -> Path:
    return state_dir() / "installed.json"


def read_manifest() -> dict:
    path = _manifest_path()
    if path.is_symlink() or not path.is_file():
        return {"schema": 1, "files": {}}
    if path.stat().st_size > MAX_RECORD_BYTES:
        raise Failure(INPUT_LIMIT, f"Skill install record exceeds {MAX_RECORD_BYTES} bytes and was not read: {path}",
                      "Move the record aside; the next install writes a fresh one and refuses files it cannot account for.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise Failure(INPUT_INVALID, f"Skill install record is not valid JSON: {path}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise Failure(INPUT_INVALID, f"Skill install record is malformed: {path}")
    for target, entry in data["files"].items():
        if (not isinstance(target, str) or not isinstance(entry, dict) or not isinstance(entry.get("sha256"), str)
                or len(entry["sha256"]) != 64):
            raise Failure(INPUT_INVALID, f"Skill install record has a malformed entry for {target!r}: {path}",
                          "Move the record aside; the next install writes a fresh one and refuses files it cannot account for.")
    return data


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ----- detection and decisions -------------------------------------------------------------------

def _home(explicit: str | None) -> tuple[Path, Path]:
    """(home as given, home resolved). Detection and every write use the resolved path, so a home
    that is itself a link is used at its real location and no link above it is walked again."""
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_absolute():
            raise Failure(INPUT_INVALID, "--home must be an absolute path")
    else:
        p = Path.home()
    if not p.is_dir():
        raise Failure(INPUT_MISSING, f"Home is not a directory: {p}")
    return p, p.resolve()


def detect(home: Path, only: list[str] | None = None) -> list[dict]:
    """One row per harness: found (its home marker directory exists and is not a link) and the skills directory."""
    if only:
        unknown = sorted(set(only) - set(HARNESSES))
        if unknown:
            raise Failure(INPUT_INVALID, f"Unknown harness ids: {unknown}", f"Known: {sorted(HARNESSES)}")
    rows = []
    for hid, (label, marker, skills_rel) in HARNESSES.items():
        if only and hid not in only:
            continue
        marker_path = home / marker
        found = marker_path.is_dir() and not marker_path.is_symlink()
        row = {"id": hid, "label": label, "found": found, "marker": str(marker_path), "directory": str(home / skills_rel)}
        if not found and only:
            raise Failure(INPUT_MISSING, f"{hid}: {marker_path} is not present (or is a link), so {label} is not set up here",
                          "Create the directory if you want the skills there anyway, or name another harness.")
        if not found:
            row["reason"] = "home directory absent" if not marker_path.exists() else "home directory is a link"
        rows.append(row)
    return rows


def _blocked(target: Path, home: Path) -> str:
    """Why nothing may be written at target: a link at any component from the resolved home down,
    or a component that exists and is not a directory. Empty when the path is writable."""
    parts = target.relative_to(home).parts
    current = home
    for index, part in enumerate(parts):
        current = current / part
        if current.is_symlink():
            return "the destination or one of its directories is a link"
        last = index == len(parts) - 1
        if not last and current.exists() and not current.is_dir():
            return "a directory on the destination path is a file"
    return ""


def _decision(target: Path, data: bytes, recorded: dict, home: Path) -> tuple[str, str]:
    blocked = _blocked(target, home)
    if blocked:
        return "refused", blocked
    if not target.exists():
        return "write", ""
    if not target.is_file():
        return "refused", "the destination exists and is not a regular file"
    if target.stat().st_size > MAX_SKILL_FILE_BYTES:
        return "refused", f"the destination is larger than any skill file ({MAX_SKILL_FILE_BYTES} bytes) and was not read"
    current = _sha(target.read_bytes())
    if current == _sha(data):
        return "unchanged", ""
    if recorded.get(str(target), {}).get("sha256") == current:
        return "update", "bytes still match what this route wrote earlier"
    return "refused", "exists with different content that this route did not write"


_OPEN_NEW = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)


def _apply(target: Path, data: bytes, home: Path, expected_sha: str | None) -> str:
    """Write target. A new file (``expected_sha`` None) is created exclusively at its final path, so
    a file another process puts there first makes the create fail and nothing is overwritten; on a
    failed write the partial file this call created is removed. An update (``expected_sha`` is the
    hash this route recorded) goes through a temporary file and replaces the target only if the
    target still hashes to that value at the last check. The path is checked for links again after
    the directories exist and before the rename. Descriptor-relative operations would close the
    remaining windows entirely; they are not available on Windows, so the checks are repeated
    instead. Returns a reason when refused."""
    target.parent.mkdir(parents=True, exist_ok=True)
    blocked = _blocked(target, home)
    if blocked:
        return blocked
    if expected_sha is None:
        try:
            fd = os.open(target, _OPEN_NEW, 0o644)
        except FileExistsError:
            return "a file appeared at the destination while installing; it was not overwritten"
        except OSError as exc:
            return f"the destination could not be created: {exc.strerror or exc}"
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
        except OSError as exc:
            target.unlink(missing_ok=True)
            return f"the destination could not be written: {exc.strerror or exc}"
        return ""
    tmp = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
    fd = os.open(tmp, _OPEN_NEW, 0o644)
    renamed = False
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        blocked = _blocked(target, home)
        if blocked:
            return blocked
        if target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_SKILL_FILE_BYTES \
                or _sha(target.read_bytes()) != expected_sha:
            return "the destination changed while installing; it was not overwritten"
        os.replace(tmp, target)
        renamed = True
        return ""
    finally:
        if not renamed:
            tmp.unlink(missing_ok=True)


def install(*, plan: bool = False, only: list[str] | None = None, home: str | None = None, source: str | None = None) -> dict:
    root = source_root(source)
    skills = skills_in(root)
    given_home, user_home = _home(home)
    manifest = read_manifest()
    recorded = manifest["files"]
    harnesses = detect(user_home, only)
    counts = {"found": 0, "written": 0, "updated": 0, "unchanged": 0, "refused": 0}
    rendered_by_skill = {s["name"]: rendered(s, root) for s in skills}
    for row in harnesses:
        row["files"] = []
        if not row["found"]:
            continue
        counts["found"] += 1
        skills_dir = Path(row["directory"])
        for skill in skills:
            for rel, data in rendered_by_skill[skill["name"]].items():
                target = skills_dir / skill["name"] / rel
                action, reason = _decision(target, data, recorded, user_home)
                entry = {"skill": skill["name"], "path": str(target), "action": action, "sha256": _sha(data)}
                if reason:
                    entry["reason"] = reason
                if not plan and action in ("write", "update"):
                    reason = _apply(target, data, user_home, None if action == "write" else recorded[str(target)]["sha256"])
                    if reason:
                        action = "refused"
                        entry["action"] = action
                        entry["reason"] = reason
                    else:
                        recorded[str(target)] = {"sha256": entry["sha256"], "harness": row["id"], "skill": skill["name"],
                                                 "source_root": str(root), "toolkit_version": __version__, "installed_at": now()}
                        action = "written" if action == "write" else "updated"
                        entry["action"] = action
                key = {"write": "written", "written": "written", "update": "updated", "updated": "updated",
                       "unchanged": "unchanged", "refused": "refused"}[action]
                counts[key] += 1
                row["files"].append(entry)
    receipt_path = None
    if not plan:
        state_dir(create=True)
        _write_json(_manifest_path(), {"schema": 1, "updated": now(), "files": recorded})
        receipts = state_dir() / "receipts"
        receipts.mkdir(exist_ok=True)
        receipt_path = receipts / f"{now().replace(':', '').replace('-', '')}-{uuid.uuid4().hex[:8]}.json"
        _write_json(receipt_path, {"schema_version": 1, "command": "dev install-skills", "at": now(), "source_root": str(root),
                                   "toolkit_version": __version__, "home": str(user_home), "harnesses": harnesses,
                                   "summary": counts, "game_touched": False})
    result = {"plan": plan, "source": str(root), "toolkit_version": __version__, "home": str(given_home),
              "home_resolved": str(user_home), "skills": [s["name"] for s in skills], "harnesses": harnesses, "summary": counts,
              "receipt": str(receipt_path) if receipt_path else None, "record": str(_manifest_path()),
              "game_touched": False,
              "verification": "files compared by hash and written under the user's home; no harness was launched, so each "
                              "harness's own listing (for example /skills in a new session) is the check that it sees them"}
    if not counts["found"]:
        result["hint"] = ("No harness home directory was found under " + str(user_home) +
                          ". Create ~/.agents/skills (the shared Agent Skills location) or pass --home.")
    if counts["refused"] and not plan:
        raise Failure(OUTPUT_EXISTS, f"{counts['refused']} file(s) already exist with other content and were left alone; "
                      f"{counts['written']} written, {counts['updated']} updated",
                      "Move the named files aside if you want this route's copies; it never overwrites what it did not write.",
                      **result)
    return result


def status(home: str | None = None, source: str | None = None) -> dict:
    """For doctor: per detected harness, how many skills are current, stale, foreign or missing,
    judged over every file a skill installs. Never raises for a missing checkout."""
    try:
        root = source_root(source)
    except Failure as exc:
        return {"source": None, "note": exc.message, "harnesses": []}
    try:
        skills = skills_in(root)
        _, user_home = _home(home)
        recorded = read_manifest()["files"]
    except Failure as exc:
        return {"source": str(root), "note": exc.message, "harnesses": []}
    rows = []
    for row in detect(user_home):
        if not row["found"]:
            continue
        skills_dir = Path(row["directory"])
        summary = {"current": 0, "stale": 0, "foreign": 0, "missing": 0}
        for skill in skills:
            actions = []
            for rel, data in rendered(skill, root).items():
                action, _ = _decision(skills_dir / skill["name"] / rel, data, recorded, user_home)
                actions.append(action)
            # One state per skill: the worst of its files (a foreign file beats a stale one beats a missing one).
            state = next((candidate for candidate in ("refused", "update", "write") if candidate in actions), "unchanged")
            summary[{"unchanged": "current", "update": "stale", "refused": "foreign", "write": "missing"}[state]] += 1
        rows.append({"id": row["id"], "label": row["label"], "directory": row["directory"], **summary,
                     "ok": summary["current"] == len(skills)})
    return {"source": str(root), "skills": len(skills), "harnesses": rows,
            "install": "pat dev install-skills --json" if any(not r["ok"] for r in rows) else None}
