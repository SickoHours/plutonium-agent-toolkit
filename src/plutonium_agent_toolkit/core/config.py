"""User configuration and state locations. No home-directory or workspace assumptions.

Resolution order for the toolkit home:
    1. ``PAT_HOME`` environment variable (absolute path)
    2. ``%LOCALAPPDATA%\\PlutoniumAgentToolkit`` on Windows
    3. ``~/.local/state/plutonium-agent-toolkit`` elsewhere (Linux)

``config.json`` holds only absolute paths the user or agent configured
explicitly. Unknown keys are rejected so typos surface immediately.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from .errors import CONFIG_INVALID, CONFIG_MISSING, Failure

KNOWN_KEYS = {
    "plutonium_storage_t6": "Plutonium storage\\t6 directory containing mods and main",
    "plutonium_launcher": "Official plutonium.exe launcher path (optional)",
    "backends_dir": "Directory where pinned backend programs are installed (default: <home>\\backends)",
    "evidence_dir": "Directory for private run evidence (default: <home>\\evidence)",
    "t3_bearer_token": "Bearer token for a T3 Code server, issued by the user with `t3 auth session issue` (agent routes)",
}
MAX_CONFIG_BYTES = 65536
# Keys whose value is an opaque string rather than an absolute path.
SECRET_KEYS = {"t3_bearer_token"}


def home() -> Path:
    override = os.environ.get("PAT_HOME")
    if override:
        p = Path(override)
        if not p.is_absolute():
            raise Failure(CONFIG_INVALID, "PAT_HOME must be an absolute path")
        return p
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            raise Failure(CONFIG_INVALID, "LOCALAPPDATA is unavailable; use a native Windows terminal")
        return Path(base) / "PlutoniumAgentToolkit"
    return Path.home() / ".local" / "state" / "plutonium-agent-toolkit"


def config_path() -> Path:
    return home() / "config.json"


def _read_small_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise Failure(CONFIG_INVALID, f"Expected a regular file: {path}")
    raw = path.read_bytes()
    if len(raw) > MAX_CONFIG_BYTES:
        raise Failure(CONFIG_INVALID, f"Configuration exceeds {MAX_CONFIG_BYTES} bytes")
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise Failure(CONFIG_INVALID, f"Invalid JSON in {path}") from exc
    if not isinstance(value, dict):
        raise Failure(CONFIG_INVALID, "Configuration must be a JSON object")
    return value


def load() -> dict:
    path = config_path()
    value = _read_small_json(path) if path.exists() else {}
    unknown = set(value) - set(KNOWN_KEYS)
    if unknown:
        raise Failure(CONFIG_INVALID, f"Unknown configuration keys: {sorted(unknown)}",
                      f"Known keys: {sorted(KNOWN_KEYS)}")
    for key, item in value.items():
        if not isinstance(item, str) or not item:
            raise Failure(CONFIG_INVALID, f"Configuration values must be non-empty strings: {key}")
        if key not in SECRET_KEYS and not Path(item).is_absolute():
            raise Failure(CONFIG_INVALID, f"Configuration paths must be absolute strings: {key}")
    root = home()
    value.setdefault("backends_dir", str(root / "backends"))
    value.setdefault("evidence_dir", str(root / "evidence"))
    return value


def require(key: str) -> Path:
    value = load().get(key)
    if not value:
        raise Failure(CONFIG_MISSING, f"Configuration key '{key}' is not set",
                      f"Run: pat configure --{key.replace('_', '-')} <absolute path>")
    return Path(value)


def save(values: dict) -> Path:
    unknown = set(values) - set(KNOWN_KEYS)
    if unknown:
        raise Failure(CONFIG_INVALID, f"Unknown configuration keys: {sorted(unknown)}")
    for key, item in values.items():
        if not isinstance(item, str) or not item or (key not in SECRET_KEYS and not Path(item).is_absolute()):
            raise Failure(CONFIG_INVALID, f"Use absolute paths: {key}")
        if key in SECRET_KEYS and (len(item) > 4096 or any(c.isspace() for c in item)):
            raise Failure(CONFIG_INVALID, f"{key} must be a single token without whitespace")
    current = {}
    path = config_path()
    if path.exists():
        current = _read_small_json(path)
    current.update(values)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    # The file may hold a bearer token: create it owner-only before any byte is written.
    tmp.touch(mode=0o600)
    if os.name != "nt":
        os.chmod(tmp, 0o600)
    tmp.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path
