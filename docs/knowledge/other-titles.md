# Other Call of Duty titles

The toolkit targets **Plutonium T6 Zombies (Black Ops II)**. Other titles are out of scope: the
routes, pins, recipes and knowledge here are T6-specific unless a page says otherwise. This page
says what differs so you do not port a T6 assumption to another engine by accident.

| Title (Plutonium name) | Script | Fastfile tools | What differs for a mod |
| --- | --- | --- | --- |
| Black Ops II (T6) | GSC/CSC, compiled by gsc-tool for `t6` | OpenAssetTools links and reads back; `mod.ff` in `mods/<folder>` | This toolkit's target |
| Black Ops (T5) | GSC, a different VM; script compilation is not supported by the pinned tools | OpenAssetTools reads T5 fastfiles and can package precompiled assets | A T5 script cannot be compiled here; donor assets can be inspected and extracted |
| World at War (T4) | GSC, older VM | Different fastfile format; not covered by the pinned tools | Out of scope |
| Modern Warfare 3 (IW5) | GSC, IW engine | Different tools and formats | Out of scope; no Zombies |
| Black Ops III (T7) | GSC with a different compiler and asset model | Not a Plutonium title; separate modding tools | Used only as an asset *donor* for T6 ports; `pat weapon catalog` inventories a saved capture of BO3 weapon assets |

## Porting from a donor title

A donor asset is a lead, not a payload. Models, animations, textures and sounds extracted from
another title need conversion to T6 formats and conventions (bone hierarchies, animation
encoding, sound alias fields, material techniques) and then the same engine contracts as native
content (`zombies-contracts.md`). A script from another title is a reference for behaviour; its
builtins and helpers do not carry over.

## What "supported" means per title

Discovery (`pat manifest`) lists no routes for other titles, and no route here launches, queries
or changes a client other than T6 Zombies. If a user asks for another title, say what this
toolkit can do (inspect and extract with OpenAssetTools where the format is supported) and what it
cannot (compile, link, install, control), and do not improvise a route.
