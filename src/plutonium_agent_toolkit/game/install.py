"""``game install-mod``: copy a built mod.ff into Plutonium storage under a new folder.

File-only. Refuses to overwrite an existing folder, hashes the source before
and the destination after, writes an install receipt into the toolkit home and
never touches the game. The fastfile's magic says which title it is for
(``TAff`` T6, ``IWffu100`` IW5) and selects the storage key, so an IW5 package
never lands under ``storage/t6``. Loading the mod is a separate step: on T6 the
authorized ``select-mod``; on IW5 the console ``fs_game mods/<folder>`` or
``loadmod <folder>``, which no route sends yet.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path

from ..core import config
from ..core.envelope import now
from ..core.errors import INPUT_INVALID, INPUT_MISSING, OUTPUT_EXISTS, Failure
from ..core.receipts import sha256_file
from ..dev import titles
from .control import MOD_ID, _regular_child, state_dir


def install_mod(mod_ff: Path, folder: str, replace: bool = False) -> dict:
    src = Path(mod_ff).expanduser().resolve()
    if src.is_symlink() or not src.is_file():
        raise Failure(INPUT_MISSING, f"mod.ff not found: {src}")
    if src.name.lower() != "mod.ff":
        raise Failure(INPUT_INVALID, "Point install-mod at a file named mod.ff (the output of project build)")
    if not isinstance(folder, str) or not MOD_ID.match(folder) or folder in (".", "..") or folder.lower().startswith("mp_"):
        raise Failure(INPUT_INVALID, "Mod folder ID uses letters, digits, dot, underscore, dash; not mp_*")
    with src.open("rb") as fh:
        head = fh.read(8)
    game = titles.title_of_magic(head)
    if game is None:
        # No known magic: the file is not one OpenAssetTools wrote for T6 or IW5. Accept it as T6
        # only while no IW5 storage is configured, so a machine with both never guesses.
        if config.load().get(titles.zone("iw5")["storage_key"]):
            raise Failure(INPUT_INVALID, f"mod.ff does not start with a known fastfile magic ({head!r}); expected TAff (T6) or IWffu100 (IW5)",
                          "Both storages are configured, so the title must come from the file; point install-mod at the mod.ff a pat build produced.")
        game = titles.DEFAULT_TITLE
    zone = titles.zone(game)
    root = config.require(zone["storage_key"])
    if not root.is_dir():
        raise Failure(INPUT_MISSING, f"Configured storage does not exist: {root}")
    mods = root / "mods"
    mods.mkdir(exist_ok=True)
    dest_dir = _regular_child(mods, folder)
    # Read and hash the source before anything moves: the source may live inside the
    # very folder --replace is about to move aside.
    source_bytes = src.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    backup = None
    if dest_dir.exists():
        if not replace:
            raise Failure(OUTPUT_EXISTS, f"mods/{folder} already exists; pass --replace to move it aside first",
                          "The toolkit never overwrites an installed mod silently.")
        backup = state_dir() / "mod-backups" / f"{folder}-{uuid.uuid4().hex}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dest_dir), str(backup))
    dest = dest_dir / "mod.ff"
    try:
        dest_dir.mkdir()
        dest.write_bytes(source_bytes)
        dest_sha = sha256_file(dest)
        if dest_sha != source_sha:
            raise Failure("hash_mismatch", "Installed mod.ff does not match the source after copy; inspect the storage volume")
    except (OSError, Failure):
        # Put the previous installation back so --replace never leaves the user with nothing.
        shutil.rmtree(dest_dir, ignore_errors=True)
        if backup is not None:
            shutil.move(str(backup), str(dest_dir))
            backup = None
        raise
    receipt = {"schema_version": 1, "at": now(), "game": game, "storage": str(root), "folder": folder,
               "path": f"mods/{folder}/mod.ff", "sha256": dest_sha,
               "bytes": dest.stat().st_size, "source": str(src), "backup": str(backup) if backup else None,
               "game_touched": False}
    receipts = state_dir() / "installs"
    receipts.mkdir(parents=True, exist_ok=True)
    (receipts / f"{folder}-{uuid.uuid4().hex}.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    if game == "t6":
        nxt = ["pat game select-mod " + folder + "   (needs authorization; loads the mod in the running game)"]
    else:
        nxt = [f"In the Plutonium IW5 console: fs_game mods/{folder}  (or: loadmod {folder}); then start a private match. "
               "No pat route sends this yet; IW5 has no Mods menu (docs/knowledge/iw5.md)"]
    return {**receipt, "next": nxt}
