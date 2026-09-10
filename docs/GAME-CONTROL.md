# Game control on Windows

`pat game …` controls a running Plutonium T6 Zombies client through its **external console**
(the black window Plutonium opens beside the game). The toolkit attaches to that console, reads
its screen buffer and writes one command at a time as console input. It does not read game
memory, inject anything, focus the game or press player keys.

## Before any live command

- Configure storage: `pat configure --plutonium-storage-t6 "%LOCALAPPDATA%\Plutonium\storage\t6"`.
- For `launch`, also `--plutonium-launcher "C:\…\plutonium.exe"`.
- Run the agent from the same Windows user and interactive session as the game, without elevation.
- Keep the external console open and idle. The toolkit waits for an empty prompt and never types
  over the user's text; if the console is busy it reports `busy` and sends nothing.
- Every live route needs the user's go-ahead for that specific test. Discovery, `mods` and
  `status` need none.

## Routes

| Command | What it does | Result to keep |
| --- | --- | --- |
| `pat game status` | Lists visible T6 Zombies windows and the foreground window. No engine input. | `windows`, `foreground` |
| `pat game mods` | Disk inventory of `storage\t6\mods`; `available` needs `mod.ff` or `mod_load.ff` and not an `mp_` folder. | `mods[]` |
| `pat game info` | Fresh `fs_game`, `mapname`, `sv_running`, `sv_cheats`, `g_gametype`. | `state`, `process` |
| `pat game launch` | Issues the fixed `plutonium://play/t6zm` URI through the registered handler, then logs every foreground change until the game window has been visible for 3 s plus a 15 s settle window, or 90 s if it never appears. | `launch_requested`, `game_detected`, `focus_preserved`, `focus_scope`, `focus_events` |
| `pat game select-mod <id>` / `base` | Leaves the match if needed, unloads, loads. Each step is verified before the next. Selecting the current mod is a no-op. | `load_id`, `load_check.argv` |
| `pat game reload-mod` | Same transaction for the currently selected mod. | `load_id` |
| `pat game load-map <map-id>` | Writes and verifies the five UI/gametype dvars, then sends `map` once. DLC5 maps need a selected mod that ships `zone\<map>.ff`. | `load_id`, `load_check.argv` |
| `pat game fast-restart` / `map-restart` / `disconnect` | One verb, once, in a running local match. | `load_id` |
| `pat game check-load <load-id>` | Re-attaches to the *same* process (PID + creation time), compares fresh state to the expected state, counts new error lines in `console_zm.log`. Valid ten minutes. | `verified`, `state_matches`, `logs` |
| `pat game quit` | `quit` once, wait up to 20 s for the pinned process to exit. Never kills. | `stopped` |

Map IDs: `tranzit town farm bus-depot nuketown die-rise mob buried origins` (base) and
`nacht verruckt shi-no-numa der-riese kino five ascension shangri-la moon` (DLC5, mod required).
`tranzit` and `bus-depot` share the engine start location `transit`; the mode differs
(`zclassic` versus `zstandard`). There is no `busdepot` token in T6.

## Reading results

- `load_id` plus `load_check.argv` is the handoff. Run the check, then look at the actual game.
  `ready_for_handoff` is always `false` from the CLI because only a person or a vision-capable
  agent can confirm a menu or a playable spawn.
- `error_code: delivery_uncertain` means a command may or may not have taken effect. Run
  `pat game info`, look at the game, and decide. Never repeat the command blindly.
- `error_code: busy` means another toolkit operation holds the mutex or the console has typed
  text. Nothing was sent.
- `game_not_found` / `game_ambiguous`: zero or more than one T6 Zombies window. The launcher alone
  is not a game.
- Launch reports three facts separately: the URI was issued, a game window appeared, and whether
  the foreground window changed during the observed window (`focus_scope` says exactly how long).
  A launcher login or update prompt shows up as a foreground change and is never answered by the
  toolkit. Focus changes after the observation window are outside this claim.

## Deadlines

Each live command runs in one worker with a parent deadline sized to its longest legitimate path:
20 s for `status`, 30 s for `info`, 45 s for `quit`, 60 s for `check-load`, 120 s for restarts and
`disconnect`, 130 s for `launch`, 150 s for `load-map` and 200 s for `select-mod` and
`reload-mod`. A deadline hit means the worker was stopped mid-transaction and the result is
`delivery_uncertain`; the game itself is never touched by the timeout.

## Where state lives

`%LOCALAPPDATA%\PlutoniumAgentToolkit\game\`: `last-load.json`, `last-load-check.json`,
`last-launch.json`, `last-result.json`. They are latest-only and can be replaced by the next
command; keep the JSON your invocation printed.

## What is not here

No arbitrary console strings. No weapon grants, cheats or developer-menu commands. No native
player input. No mod installation (copy `mod.ff` yourself or through a future route). No
multiplayer, no other titles.

## Troubleshooting

| Result | What to do |
| --- | --- |
| `unsupported_platform` | Use a native Windows terminal. Wine, WSL and remote Linux shells are refused. |
| `config_missing` | Run the `pat configure …` command named in the hint. |
| `game_not_found` with the game visibly open | The window title must be exactly `Plutonium T6 Zombies` (optionally with a build in parentheses). Check the agent runs as the same user without elevation. |
| Cannot attach external console | The console must be the classic console host attached to the bootstrapper. See Microsoft's [AttachConsole](https://learn.microsoft.com/en-us/windows/console/attachconsole) notes. Do not change terminal defaults automatically. |
| `busy: console is busy or contains typed text` | Someone typed in the console. Let them finish; the toolkit preserved their text. |
| `check-load` reports `checked: false` for logs | The log was missing, rotated or grew past 4 MiB. State may still match; the log gate is simply unverified. |
| `check-load` reports `delivery_uncertain` right after `load-map` | The engine does not answer console queries while a map is loading. Let the load settle, then run the check once. Never replay a gameplay verb. |
| Launch took focus | Expected on Windows 11 with Plutonium r5346: the external console comes to the front within a second and the game window at about 5 s. The toolkit reports it (`focus_preserved`) and never fights it; see issue #9 for an opt-in restore. |
