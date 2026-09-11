"""Per-title facts, the single seam that lets one code path serve more than one game.

The toolkit was built for T6 (Black Ops II) Zombies. IW5 (Modern Warfare 3) support threads a
title id through the same routes rather than forking them. A title names:

* ``gsc_game`` - the gsc-tool ``-g`` token, and the script instances the compiler recognises.
* ``zone`` - what the OAT Linker stamps into the zone header (``> game,<token>``), the mode word
  the plan records, the zone/package name the fastfile is bound to, and the localized-strings
  language folder.
* ``categories`` / ``kinds`` - the browse taxonomy a declaration is validated against. These do
  not affect resolution; they are the shelves a human reads. T6 is Zombies-flavoured
  (perks, gobblegums, powerups); IW5 is MW3-flavoured (attachments, killstreaks).

The fastfile-universal kinds (what a manifest derives and a module provides) are shared across
titles and live in ``compositions.py``; being permissive there is harmless because a seed only
derives the kinds its package actually contains.

Nothing here downloads or runs a backend; it is inert data plus small lookups. A title entry only
makes the routes *accept* the title. ``docs/SUPPORT.md`` still grades each route per title, and the
IW5 zone details below are inferred from OpenAssetTools and gsc-tool support, not yet qualified
against a real IW5 build (see the IW5 rows there).
"""
from __future__ import annotations

from ..core.errors import INPUT_INVALID, Failure

TITLES = {
    "t6": {
        "label": "Black Ops II (T6) Zombies",
        "gsc_game": "t6",
        "systems": ("pc",),
        "instances": ("server", "client"),
        "zone": {"game_token": "T6", "mode": "zm", "name": "mod", "language": "english"},
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
        "instances": ("server", "client"),
        # OAT stamps `> game,IW5`; IW5 Plutonium loads a `mod.ff` from the mods folder, so the zone
        # name binding is the same as T6. `mp` is the MW3 zone family (multiplayer/survival).
        "zone": {"game_token": "IW5", "mode": "mp", "name": "mod", "language": "english"},
        "modes": ("mp", "sp"),
        "categories": ("weapons", "attachments", "killstreaks", "perks", "maps", "ui", "core",
                       "scripts", "audio", "tooling", "pack", "module"),
        "kinds": {"weapons": ("primary", "secondary", "launcher", "melee", "special"),
                  "attachments": ("optic", "barrel", "underbarrel", "perk"),
                  "killstreaks": ("assault", "support", "specialist"), "perks": ("perk", "perkbit"),
                  "maps": ("map", "patch"), "ui": ("hud", "menu"),
                  "core": ("inventory", "registry", "adapter"), "scripts": ("script",),
                  "audio": ("alias", "stream"), "tooling": ("tool",), "pack": ("pack",), "module": ()},
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


def zone(title: str) -> dict:
    return get(title)["zone"]


def modes(title: str) -> tuple[str, ...]:
    return get(title)["modes"]


def categories(title: str) -> tuple[str, ...]:
    return get(title)["categories"]


def kinds(title: str) -> dict:
    return get(title)["kinds"]
