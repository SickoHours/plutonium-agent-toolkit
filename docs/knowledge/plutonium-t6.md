# Plutonium T6 Zombies: the client, its storage and its console

## Where things are

Plutonium keeps per-game data in a storage folder, `storage/t6` for Black Ops II (on Windows
`%LOCALAPPDATA%\Plutonium\storage\t6`; `pat configure --plutonium-storage-t6` records it).
Inside it:

| Path | What lives there |
| --- | --- |
| `mods/<folder>/` | One installed mod per folder. The engine loads `mod.ff` from here; some bases also ship `mod_load.ff` and `mod_load.ipak` |
| `main/console_zm.log` | The Zombies client's console log; every script error, load failure and shutdown reason is written here |
| `usermaps/<map>/` | Custom maps as their own fastfiles, when a base uses that layout |
| `raw/` | Loose files the client reads directly: global scripts under `raw/scripts/zm/`, UI Lua under `raw/ui_mp/` |
| `zone/` | Extra fastfiles some mod bases keep beside the mod folder |

`pat game mods --json` lists the mod folders and whether each is loadable (`mod.ff` or
`mod_load.ff` present, not an `mp_` folder). Presence is not compatibility: a folder that only
contains scripts cannot be loaded as a mod.

## How a mod is selected

The engine dvar `fs_game` names the selected mod as `mods/<folder>` or is empty for the base game.
The console verb `loadmod <folder>` selects a mod; `loadmod ""` unloads it. Selecting the folder
that is already selected does nothing: it does not reload changed files. Leaving a running match
first (`disconnect`) is required; the toolkit's `select-mod` and `reload-mod` do that sequence
and verify each step against fresh dvar state.

A T6 fastfile is bound to its file name: the zone name keys its compressed streams. `mod.ff`
built as zone `mod` loads; the same bytes renamed cannot be inflated and hang the client. Build
with `pat project build`, which links the zone as `mod`, and install with `pat game install-mod`,
which keeps the name.

## What changes need

| You changed | What makes the engine see it |
| --- | --- |
| A script inside `mod.ff` | Rebuild, reinstall, then `reload-mod` (or select another mod and back). `map_restart` reruns scripts already loaded; it does not reread the fastfile |
| A loose file under `raw/` | The next map load; global scripts are read at load |
| The map | `load-map` with the five UI dvars set; a DLC or custom map also needs its fastfile where the client looks (`usermaps/<map>/<map>.ff`, or the selected mod's `zone/<map>.ff` on older bases) |
| Nothing, but you want a clean state | `fast_restart` keeps the map loaded and restarts the round; `map_restart` reloads the map script state |

A folder version or an installed hash never proves which bytes the running engine holds. Only a
load ID checked against the same process does (`pat game check-load`).

## The console

The external console is a separate window. The toolkit reads its buffer and types one command at a
time when the prompt is idle; it never types over user text (`busy` instead). The verbs it uses
are `map`, `map_restart`, `fast_restart`, `disconnect`, `loadmod` and `quit`; the dvars it reads
are `fs_game`, `mapname`, `sv_running`, `sv_cheats` and `g_gametype`; the ones `load-map` sets
are `ui_mapname`, `ui_zm_mapstartlocation`, `ui_gametype`, `g_gametype` and
`ui_zm_gamemodegroup`. There is no arbitrary-string route and none should be added.

`sv_running` is `1` inside a local match and `0` in the menu. `mapname` is the engine's start
location, which differs from the menu name for some maps (`transit` for Tranzit and Bus Depot;
the mode dvar distinguishes them).

## Starting a match from the console

A match started by the console `map` verb from the main menu has been observed to load the level
and then drop back to the menu with `SV_Shutdown: hostquit`, while a match started from the menu
on the same install plays to completion. The working assumption is that `load-map` switches
content inside a running private match rather than cold-starting one. Until that is confirmed,
treat "start any match from the menu by hand, then `load-map`" as the tested path and a cold
start as unverified.

## Facts that are still open

- Whether the cold-start drop above is a scope rule or a fixable difference.
- Whether focus can be preserved on launch; today the game window takes focus a few seconds after
  the launcher starts it.
