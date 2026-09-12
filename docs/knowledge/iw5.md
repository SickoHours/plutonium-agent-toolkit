# IW5 (Modern Warfare 3) under Plutonium: the contract a mod has to meet

Everything on this page was read from a primary source: the Plutonium documentation and
changelog, a Plutonium developer's statement on the gsc-tool tracker, the OpenAssetTools and
gsc-tool sources at the pinned versions, and mods that run on Plutonium IW5 today. No build from
this toolkit has run in an IW5 client yet; the last section says what is still unmeasured.
Tools: `iw5-tools.md`. Steps: `docs/playbooks/build-an-iw5-mod.md`.

## What Plutonium IW5 is

Multiplayer only (`iw5mp.exe`). Spec Ops, Survival and the campaign run on a separate binary
Plutonium does not ship or plan to; community "survival" mods for Plutonium are gametype scripts
on multiplayer maps. There is one script VM: server GSC, no `.csc` client scripts, no Zombies
`zm` mode. `mp` is the only mode a recipe can name.

## Where things are

Storage is `storage/iw5` (`%LOCALAPPDATA%\Plutonium\storage\iw5` on Windows;
`pat configure --plutonium-storage-iw5` records it).

| Path | What lives there |
| --- | --- |
| `mods/<folder>/mod.ff` | One installed mod per folder, its fastfile named `mod.ff`; `.iwd` archives beside it carry loose images, sounds and scripts |
| `scripts/*.gsc` | Loose global scripts the client autoloads for every match; `scripts/mp/<map>/` and `scripts/mp/<gametype>/` load only for that map or gametype and their entry points are not auto-called |
| `<engine path>` | A loose file at an engine path overrides the stock one (`maps/mp/gametypes/war.gsc`, `localizedstrings/*.str`, `images/*.iwi`); the same override works from inside an `.iwd` |
| `usermaps/<map>/` | Custom maps: `<map>.ff`, `<map>_load.ff`, `<map>.iwd`, `<map>.arena`. Never a mod |
| `zone/*.ff` | Fastfiles Plutonium itself ships and zone overrides; version 2000, unreadable by OpenAssetTools (below) |
| `plugins/*.dll` | Server plugins that add GSC builtins (`iw5-gsc-utils`, `iw5-script`) |

## How a mod is selected

There is no Mods menu. In the console: `fs_game mods/<folder>` then start a private match, or
`loadmod <folder>`. `fs_game` does not persist across launches. On a dedicated server
`seta fs_game "mods/<folder>"` in `server.cfg`, with `sv_wwwBaseURL` for clients to download the
folder. No `pat game` route sends these yet; `game install-mod` places the folder and prints the
console line.

## Scripts: source in, source out

Plutonium IW5 compiles GSC source itself. It never executes gsc-tool bytecode. The developer's
words on xensik/gsc-tool#20: "Plutonium IW5 can load GSC scripts on its own now ... add them as
rawfile assets (instead of scriptfile assets). Example: `rawfile,maps/mp/gametypes/war.gsc`".
Every mod that runs today ships `.gsc` text, in a fastfile rawfile, in an `.iwd`, or loose.

So on this title the toolkit packs the source as the rawfile and runs gsc-tool only as a syntax
gate (`pat gsc check`, the compiler's dry run). A build whose rawfile begins with `GSC\0` would
link, read back byte-identical, and do nothing in the game. That was the first mistake made here;
do not repeat it by "compiling for IW5" because T6 needs it.

Entry points: the client calls `main()` then, after the gametype starts, `init()` in each
autoloaded script. The T6 idioms work: `level waittill("connected", player)`,
`self waittill("spawned_player")`, `iprintln`, `#include maps\mp\_utility;`, and `replaceFunc`
for hooking a stock function without replacing its file. The preprocessor accepts `#define` and
`#undef`; conditional blocks are not supported by the client's compiler. gsc-tool's `-g iw5`
builtin tables are the best offline reference for what exists; the stock scripts are public in
`plutoniummod/iw5-scripts`.

What is autoloaded from where has receipts for loose files and `.iwd` files. A rawfile at
`scripts/<name>.gsc` inside `mod.ff` is the toolkit's default target, by analogy, without a
receipt. The proven fastfile route is overriding an engine path: a gametype at
`maps/mp/gametypes/<gt>.gsc` with its `<gt>.txt` strings and `mp/recipes/<gt>.recipe`, plus
`maps/mp/gametypes/_gametypes.txt` to register it.

## Fastfiles

OpenAssetTools writes `> game,IW5` zones as unsigned `IWffu100`, zone version 1, zlib deflate.
Plutonium loads them (the arena gametype mod is built exactly so). The zone is linked as `mod`
and installed as `mod.ff`; the name binding is the same as T6.

The fastfiles Plutonium itself ships under `storage/iw5/zone/` are `IWffu100` with zone version
2000. OpenAssetTools 0.33.0 accepts version 1 only and fails on them with "Could not create
factory". Load and inspect the game's own zones instead (`zone/english/common_mp.ff`,
`ui_mp.ff`, a map's `mp_<name>.ff`). OpenAssetTools' IW5 x64 loading was broken before v0.30.0;
the 0.33.0 pin is above that floor.

`-l <zone.ff>` makes a loaded zone's assets resolvable and lets a root named in the zone file be
copied with its dependency graph; a `weapon` root pulls its models, materials, images, shaders,
effects, tracer, physics preset and sounds. Localized strings come from
`english/localizedstrings/mod.str` named by `localize,mod`; the file format is the T6 one.

What OpenAssetTools can build from source for IW5, and what only comes out of a loaded zone, is
in `iw5-tools.md`. The short version: rawfile, scriptfile, stringtable, localize, image (IWI
version 8), material, xmodel, xanim, weapon, attachment, menu, font, leaderboard, tracer,
vehicle, physpreset, soundcurve from source; sound aliases, loaded sounds, technique sets,
effects and world data only by carrying. Custom sounds therefore need an `.iwd` or ZoneTool.

## What is measured and what is not

Measured here: an IW5 `mod.ff` links and reads back on Linux and Windows with the pinned
backends; a source rawfile survives the round trip; the Plutonium-shipped zones fail in
Unlinker; `IWffu100` version 1 is what the Linker writes.

Not measured: any IW5 build from this toolkit loading in a client, the autoload of a
`scripts/<name>.gsc` rawfile from `mod.ff`, engine limits for IW5 zones, and every `game`
route. The first person with a Windows host and the game closes those gaps with
`docs/playbooks/build-an-iw5-mod.md` and records the receipt; until then every IW5 claim ends
at offline verified.
