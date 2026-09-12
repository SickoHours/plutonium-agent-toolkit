# IW5 (Modern Warfare 3) tools: what exists, what each does, how an agent drives it

There were never official Modern Warfare 3 mod tools. Everything below is community work. The
toolkit wraps the first two; the rest are driven directly from a shell when a task needs them,
with the receipt discipline in `CONTEXT.md` (new output directory, exact argv, the log kept).
Contract facts: `iw5.md`.

## The two the toolkit runs

**OpenAssetTools** (Laupetin, GPL-3.0, pinned 0.33.0, Windows and Linux). `Linker` builds an
IW5 zone from `zone_source/<zone>.zone` and `raw/`; `Unlinker --list` inventories any readable
fastfile and `Unlinker` dumps assets; `ImageConverter --iw5` converts DDS to IWI version 8 and
back. Routes: `pat ff inspect|extract|link`, `pat project build`, `pat module build|declare`,
`pat image convert --game iw5`. Direct use when a route has no flag you need:

```sh
Unlinker --no-color --list -l <game>/zone/english/common_mp.ff <file.ff>
Unlinker --no-color --output-folder <new dir> --include-assets weapon,attachment,menulist <file.ff>
Unlinker --no-color --gdt --output-folder <new dir> --include-assets weapon <file.ff>
Linker --no-color --base-folder <project> --output-folder <new dir> -l <game>/zone/english/common_mp.ff mod
```

IW5 asset tokens the zone file accepts, from the OpenAssetTools source: `physpreset`,
`physcollmap`, `xanim`, `xmodelsurfs`, `xmodel`, `material`, `pixelshader`, `vertexshader`,
`vertexdecl`, `techniqueset` (alias `techset`), `image`, `sound`, `soundcurve`, `loadedsound`,
`clipmap`, `comworld`, `glassworld`, `pathdata`, `vehicletrack`, `mapents`, `fxworld`, `gfxworld`,
`lightdef`, `font`, `menulist`, `menu`, `localize`, `attachment`, `weapon`, `fx`, `impactfx`,
`surfacefx`, `rawfile`, `scriptfile`, `stringtable`, `leaderboard`, `structureddatadef`,
`tracer`, `vehicle`, `addonmapents`.

| Built from a source file | Where the Linker looks (under `raw/` or an asset search path) |
| --- | --- |
| `rawfile` | the asset name as a path (`scripts/x.gsc`, `mp/recipes/x.recipe`) |
| `scriptfile` | `<name>.gscbin` from gsc-tool `-g iw5`; the stock engine's form, not what Plutonium runs |
| `stringtable` | the CSV at the asset name |
| `localize` | `english/localizedstrings/<name>.str` |
| `image` | `images/<name>.iwi` (version 8); DDS only for names starting with `*` |
| `material` | `materials/<name>.json` |
| `xmodel`, `xanim` | `xmodel/<name>.json`, `xanim/<name>` |
| `weapon` | `weapons/<name>` infostring (`WEAPONFILE`) or a `> gdt` entry; accuracy graphs under `accuracy/` |
| `attachment` | `attachment/<name>.json` |
| `menulist`, `menu` | the menu list file, then each `.menu` it names; `--menu-permissive` for unknown script commands |
| `font`, `leaderboard`, `tracer`, `vehicle`, `physpreset`, `soundcurve`, `lightdef`, shaders | JSON, infostring or GDT under their own folders |

Only by carrying from a loaded zone: `sound`, `loadedsound`, `techniqueset`, `fx`, `impactfx`,
`surfacefx`, `physcollmap`, `xmodelsurfs`, `structureddatadef`, and every world type. Custom
audio has no OpenAssetTools route on this title.

**gsc-tool** (xensik, GPL-3.0, pinned 1.4.10). `-g iw5 -s pc` (also `ps3`, `xb2`). `comp` writes
`<name>.gscbin`; `-z` writes ZoneTool's `.cgsc` plus `.cgsc.stack`; `decomp` reads either back to
source; `-y` dry-runs. Routes: `pat gsc check` (the IW5 syntax gate), `pat gsc compile` (only
for a `scriptfile` asset), `pat gsc decompile` (reading a stock script dumped by Unlinker).
Includes resolve against `-w <dir>` and expect the included file's compiled form, so a script
that includes stock helpers is checked with the stock tree dumped beside it or without the
include line during the check.

## Client and scripting ecosystem

| Tool | What it is | How to use it |
| --- | --- | --- |
| Plutonium IW5 client and docs (plutonium.pw) | The target; changelog and "Loading mods" page are the contract | Read once; `fs_game`, `loadmod`, `map_restart` from the console |
| `plutoniummod/iw5-scripts` | Every stock IW5 GSC file, decompiled | Reference for helpers, callbacks and map or gametype entry points; the include tree for `gsc check -w` |
| `diamante0018/PlutoIW5Arena` | A gametype mod built with OpenAssetTools and linked in CI | The reference project layout: `zone_source/arena.zone`, `maps/mp/gametypes/`, `mp/recipes/`, `english/localizedstrings/mod.str` |
| `ineedbots/iw5_bot_warfare` | The largest running IW5 script mod | Reference for `scripts/mp/` loose layout inside a mod folder and shipping source in an `.iwd`; its CI runs gsc-tool as a syntax check only |
| `alicealys/iw5-gsc-utils` (formerly fedddddd) | Plugin DLL adding GSC builtins: file IO under `storage/iw5`, HTTP, JSON, console commands, names and clantags | Drop in `plugins/`; call the functions from GSC; server side |
| `plutoniummod/plutonium-sdk` | The C++ SDK those plugins are built with | When a builtin the script needs does not exist |
| `alicealys/iw5-script` | Lua scripting plugin for IW5 (`scripts/<name>/__init__.lua`) | An alternative to GSC for server logic and chat handling |
| `Resxt/Plutonium-IW5-Scripts`, `LastDemon99/IW5-Sripts`, `whoismh11/plutoiw5-scripts` | Script collections that load from `storage/iw5/scripts` | Prior art for chat commands, killstreaks, class rules; read before designing |
| `LastDemon99/IW5-Documentation` | Community GSC guide for IW5 | The preprocessor limits and entry-point notes |
| `DoktorSAS/PlutoniumIW5Mapvote`, `LastDemon99/IW5-Survival-Reimagined`, `Joelrau/IW5p_DeathRun` | Running mods built with ZoneTool | Layouts with `mod.ff` plus `.iwd`, `.dsr` recipes, FastDL folders |

## Linkers, dumpers and extractors

| Tool | What it does | Maintained | Use |
| --- | --- | --- | --- |
| ZoneTool (`ZoneTool/zonetool`) | In-process IW5 fastfile linker and dumper run inside the game; links sound, loaded sound, technique sets, map data OpenAssetTools cannot; writes ZSTD zones | Last push 2021 | The route for custom audio and full weapon rebuilds; Windows, needs the game installed; `buildzone mod`, `dumpzone <zone>` |
| `Joelrau/zonetool`, `Joelrau/x64-zt` | ZoneTool forks that dump IW3 to IW5 for porting into newer IW titles | Active | Map and asset porting away from IW5, not into it |
| `iw4x/iw5x-port` | Converts IW5 maps to IW4 | Occasional | Porting away |
| Greyhound (`Scobalula/Greyhound`, now dest1yo) | Extracts models, animations, images and sounds from a running MW3 | Maintained | Donor asset extraction; pair with Cast for Blender |
| Wraith Archon (dtzxporter) | Greyhound's predecessor; MW3 xmodel, xanim, iwi | Archived | Fallback extractor |
| Husky, C2M, C2Mv3 | Map geometry and material export from a running game, MW3 included | C2Mv3 active | Map reference geometry |
| Cordycep (`Scobalula/Cordycep`) | Fastfile loader for newer titles | Active | Does not cover MW3 (2011); do not reach for it |
| Jekyll (`EthanC/Jekyll`) | Memory dumper for scripts, rawfiles, strings | 2022 | Script recovery when Unlinker cannot read a zone |
| Rottweiler (`Scobalula/Rottweiler`) | Fastfile sound exporter, MW3 zlib zones | Archived | Sound extraction |
| xensik/menu-tool | IW-engine menu parser | Low activity | Menu work outside OpenAssetTools |
| IWI converters (`img-format-helper`, OpenAssetTools ImageConverter) | IWI version 8 to DDS and back | Mixed | ImageConverter first |

## Other clients, for orientation only

AlterWare IW5-Mod is the singleplayer and co-op client, reads uncompiled GSC and CSV from
`.iwd`, keeps mods in the game directory, and cannot read ZoneTool's ZSTD zones; TeknoMW3 with
InfinityScript is a separate C# scripting ecosystem; open-iw5 is dead. None share Plutonium's
mod contract; a mod for one is a port for another.

## Survey provenance

Two research passes on 2026-09-11 (a DeepSeek V4.1 Flash run at maximum reasoning and two
Claude passes over the OpenAssetTools and gsc-tool sources), every claim checked against the
primary source before it entered this page. Community projects move; a tool's row is a lead to
re-read, not a promise it still builds.
