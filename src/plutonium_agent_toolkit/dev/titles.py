"""Per-title facts, the single seam that lets one code path serve more than one game.

The toolkit was built for T6 (Black Ops II) Zombies. IW5 (Modern Warfare 3) support threads a
title id through the same routes rather than forking them. A title names:

* ``gsc_game`` - the gsc-tool ``-g`` token, and the script instances the compiler recognises.
* ``script_form`` - what the client executes. T6 runs the bytecode gsc-tool emits, so the
  compiled file is packed as the rawfile. Plutonium IW5 compiles GSC source itself and runs no
  gsc-tool bytecode (its developer on xensik/gsc-tool#20: add scripts "as rawfile assets, not
  scriptfile assets"), so the source is packed and gsc-tool runs only as a dry-run syntax gate.
* ``zone`` - what the OAT Linker stamps into the zone header (``> game,<token>``), the mode word
  the plan records, the zone/package name the fastfile is bound to, the localized-strings
  language folder, the fastfile magic ``game install-mod`` sniffs, and the storage config key.
* ``categories`` / ``kinds`` - the browse taxonomy a declaration is validated against. These do
  not affect resolution; they are the shelves a human reads. T6 is Zombies-flavoured
  (perks, gobblegums, powerups); IW5 is MW3-flavoured (attachments, killstreaks).

The fastfile-universal kinds (what a manifest derives and a module provides) are shared across
titles and live in ``compositions.py``; being permissive there is harmless because a seed only
derives the kinds its package actually contains.

Nothing here downloads or runs a backend; it is inert data plus small lookups. A title entry only
makes the routes *accept* the title. ``docs/SUPPORT.md`` still grades each route per title; the IW5
facts below come from OpenAssetTools and gsc-tool sources, the Plutonium documentation and working
community mods (``docs/knowledge/iw5.md``), and no IW5 build here has run in a client yet.
"""
from __future__ import annotations

from ..core.errors import INPUT_INVALID, Failure

TITLES = {
    "t6": {
        "label": "Black Ops II (T6) Zombies",
        "gsc_game": "t6",
        "systems": ("pc",),
        "instances": ("server", "client"),
        "script_form": "compiled",
        "zone": {"game_token": "T6", "mode": "zm", "name": "mod", "language": "english",
                 "magic": (b"TAff",), "storage_key": "plutonium_storage_t6"},
        "modes": ("zm",),
        "categories": ("weapons", "perks", "gobblegums", "powerups", "equipment", "bosses", "companions",
                       "maps", "ui", "core", "scripts", "audio", "tooling", "pack", "module"),
        "kinds": {"weapons": ("wonder", "firearm", "melee", "launcher", "special"), "perks": ("perk", "machine"),
                  "gobblegums": ("gum", "machine"), "powerups": ("powerup",),
                  "equipment": ("tactical", "lethal", "buildable", "shield"),
                  "bosses": ("boss", "special-round"), "companions": ("companion",), "maps": ("map", "patch"),
                  "ui": ("hud", "menu"), "core": ("inventory", "registry", "adapter"), "scripts": ("script",),
                  "audio": ("bank", "music"), "tooling": ("tool",), "pack": ("pack",), "module": ()},
    },
    "iw5": {
        "label": "Modern Warfare 3 (IW5)",
        "gsc_game": "iw5",
        "systems": ("pc",),
        # Plutonium IW5 is multiplayer only (no Spec Ops, Survival or campaign) and has one script
        # VM: there is no client-side .csc on this title.
        "instances": ("server",),
        "script_form": "source",
        # OAT stamps `> game,IW5` and writes the unsigned magic `IWffu100`; Plutonium IW5 loads
        # `mods/<folder>/mod.ff` selected with `fs_game mods/<folder>` or `loadmod <folder>`.
        "zone": {"game_token": "IW5", "mode": "mp", "name": "mod", "language": "english",
                 "magic": (b"IWffu100", b"IWff0100"), "storage_key": "plutonium_storage_iw5"},
        "modes": ("mp",),
        # OAT cannot build IW5 sound aliases or loaded sounds from source, so there is no audio
        # shelf until a route can fill it; killstreaks and gametypes are scripts on this title.
        "categories": ("weapons", "attachments", "killstreaks", "gametypes", "perks", "maps", "ui", "core",
                       "scripts", "tooling", "pack", "module"),
        "kinds": {"weapons": ("primary", "secondary", "launcher", "melee", "special"),
                  "attachments": ("optic", "barrel", "underbarrel", "perk"),
                  "killstreaks": ("assault", "support", "specialist"), "gametypes": ("gametype", "recipe"),
                  "perks": ("perk", "deathstreak"),
                  "maps": ("map", "patch"), "ui": ("hud", "menu"),
                  "core": ("inventory", "registry", "adapter"), "scripts": ("script",),
                  "tooling": ("tool",), "pack": ("pack",), "module": ()},
    },
}

# T6 is the default so recipes and routes written before titles existed keep their behaviour.
DEFAULT_TITLE = "t6"


def names() -> tuple[str, ...]:
    return tuple(TITLES)


def get(title: str) -> dict:
    try:
        return TITLES[title]
    except KeyError:
        raise Failure(INPUT_INVALID, f"Unknown title {title!r}; known titles: {', '.join(TITLES)}")


def gsc_game(title: str) -> str:
    return get(title)["gsc_game"]


def instances(title: str) -> tuple[str, ...]:
    return get(title)["instances"]


def script_target(title: str, name: str) -> str:
    """Where a global server script goes inside the package for this title.

    T6 autoloads ``scripts/zm/<name>.gsc`` from a mod's fastfile. Plutonium IW5 autoloads the flat
    ``scripts/<name>.gsc`` namespace (``storage/iw5/scripts`` on disk; ``scripts/mp/<map>/`` and
    ``scripts/mp/<gametype>/`` are scoped folders whose entry points are not auto-called).
    Whether a rawfile at that path inside ``mod.ff`` is autoloaded has no receipt yet; the
    documented alternative is overriding an engine script path such as
    ``maps/mp/gametypes/<gametype>.gsc`` (``docs/knowledge/iw5.md``)."""
    return {"t6": f"scripts/zm/{name}.gsc", "iw5": f"scripts/{name}.gsc"}[title]


def script_form(title: str) -> str:
    """``compiled``: the gsc-tool output is packed. ``source``: the source is packed, gsc-tool only checks it."""
    return get(title)["script_form"]


def title_of_magic(head: bytes) -> str | None:
    """The title whose fastfile magic the first bytes carry, or None."""
    for name, row in TITLES.items():
        if any(head.startswith(m) for m in row["zone"]["magic"]):
            return name
    return None


def zone(title: str) -> dict:
    return get(title)["zone"]


def modes(title: str) -> tuple[str, ...]:
    return get(title)["modes"]


def categories(title: str) -> tuple[str, ...]:
    return get(title)["categories"]


def kinds(title: str) -> dict:
    return get(title)["kinds"]
