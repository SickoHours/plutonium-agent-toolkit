"""``game install-mod``: copy a built mod.ff into Plutonium storage under a new folder.

File-only. Refuses to overwrite an existing folder, hashes the source before
and the destination after, writes an install receipt into the toolkit home and
never touches the game. Loading the mod is a separate, authorized ``select-mod``.
"""
from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path

from ..core import config
from ..core.envelope import now
from ..core.errors import INPUT_INVALID, INPUT_MISSING, OUTPUT_EXISTS, Failure
from ..core.receipts import sha256_file
from .control import MOD_ID, _regular_child, state_dir


def install_mod(mod_ff: Path, folder: str, replace: bool = False) -> dict:
    src = Path(mod_ff).expanduser().resolve()
    if src.is_symlink() or not src.is_file():
        raise Failure(INPUT_MISSING, f"mod.ff not found: {src}")
    if src.name.lower() != "mod.ff":
        raise Failure(INPUT_INVALID, "Point install-mod at a file named mod.ff (the output of project build)")
    if not isinstance(folder, str) or not MOD_ID.match(folder) or folder in (".", "..") or folder.lower().startswith("mp_"):
        raise Failure(INPUT_INVALID, "Mod folder ID uses letters, digits, dot, underscore, dash; not mp_*")
    root = config.require("plutonium_storage_t6")
    if not root.is_dir():
        raise Failure(INPUT_MISSING, f"Configured storage does not exist: {root}")
    mods = root / "mods"
    mods.mkdir(exist_ok=True)
    dest_dir = _regular_child(mods, folder)
    backup = None
    if dest_dir.exists():
        if not replace:
            raise Failure(OUTPUT_EXISTS, f"mods/{folder} already exists; pass --replace to move it aside first",
                          "The toolkit never overwrites an installed mod silently.")
        backup = state_dir() / "mod-backups" / f"{folder}-{uuid.uuid4().hex}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dest_dir), str(backup))
    source_sha = sha256_file(src)
    dest_dir.mkdir()
    dest = dest_dir / "mod.ff"
    shutil.copyfile(src, dest)
    dest_sha = sha256_file(dest)
    if dest_sha != source_sha:
        raise Failure("hash_mismatch", "Installed mod.ff does not match the source after copy; inspect the storage volume")
    receipt = {"schema_version": 1, "at": now(), "folder": folder, "path": f"mods/{folder}/mod.ff", "sha256": dest_sha,
               "bytes": dest.stat().st_size, "source": str(src), "backup": str(backup) if backup else None,
               "game_touched": False}
    receipts = state_dir() / "installs"
    receipts.mkdir(parents=True, exist_ok=True)
    (receipts / f"{folder}-{uuid.uuid4().hex}.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return {**receipt, "next": ["pat game select-mod " + folder + "   (needs authorization; loads the mod in the running game)"]}
