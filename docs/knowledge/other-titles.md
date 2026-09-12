# Other Call of Duty titles

The toolkit's development routes accept two titles: **Plutonium T6 Zombies (Black Ops II)**, the
original target with every receipt, and **Plutonium IW5 (Modern Warfare 3)** multiplayer, added
later with offline receipts only (`iw5.md`, `iw5-tools.md`). Everything else is out of scope. This
page says what differs so a T6 assumption is not carried to another engine by accident.

| Title (Plutonium name) | Script | Fastfile tools | What differs for a mod |
| --- | --- | --- | --- |
| Black Ops II (T6) | GSC/CSC, compiled by gsc-tool for `t6`; the client runs the bytecode | OpenAssetTools links and reads back; `mod.ff` in `mods/<folder>`, selected from the Mods menu or `loadmod` | The original target; Zombies only |
| Modern Warfare 3 (IW5) | GSC source; the client compiles it and runs no gsc-tool bytecode; one server VM, no `.csc` | OpenAssetTools links `IWffu100` zones and reads the game's own zones, not the ones Plutonium ships; `mod.ff` in `mods/<folder>`, selected with `fs_game` or `loadmod` from the console | Multiplayer only; custom sounds need ZoneTool or an `.iwd`; no `game` route |
| Black Ops (T5) | GSC, a different VM; script compilation is not supported by the pinned tools | OpenAssetTools reads T5 fastfiles and can package precompiled assets | A T5 script cannot be compiled here; donor assets can be inspected and extracted |
| World at War (T4) | GSC, older VM | Different fastfile format; not covered by the pinned tools | Out of scope |
| Black Ops III (T7) | GSC with a different compiler and asset model | Not a Plutonium title; separate modding tools | Used only as an asset *donor* for T6 ports; a Workshop map reads offline per `bo3-workshop-formats.md`, a running BO3 under Proton is read once read-only per `docs/playbooks/inspect-a-bo3-map.md`, and `pat weapon catalog` inventories the saved capture |

## Porting from a donor title

A donor asset is a lead, not a payload. Models, animations, textures and sounds extracted from
another title need conversion to the target's formats and conventions (bone hierarchies,
animation encoding, sound alias fields, material techniques) and then the same engine contracts
as native content (`zombies-contracts.md` for T6). A script from another title is a reference for
behaviour; its builtins and helpers do not carry over, and a T6 script is not an IW5 script.

## What "supported" means per title

`pat manifest` lists routes, not titles; `docs/SUPPORT.md` grades each route per title. No route
launches, queries or changes a client other than T6 Zombies. If a user asks for T4 or T5, say
what this toolkit can do (inspect and extract with OpenAssetTools where the format is supported)
and what it cannot (compile, link, install, control), and do not improvise a route.
