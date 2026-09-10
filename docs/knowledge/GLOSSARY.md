# Glossary

One word per fact. The toolkit's documents, receipts and reports use these terms and no synonyms,
so an agent reading a report knows exactly how far a claim has been proven.

## The evidence ladder

Each rung is a separate fact. A later rung never implies an earlier one was skipped, and an
earlier rung never implies a later one.

| Term | Meaning | What proves it |
| --- | --- | --- |
| offline verified | The files were produced and checked without a game: compiled, linked, read back, byte-compared, unit-tested | A job `receipt.json` with `status: succeeded` and the checks it names |
| installed | The exact bytes are in the client's storage folder | A `game install-mod` receipt with the file hash; `game mods` lists the folder |
| launched | The Plutonium client process is running and its window exists | `game launch` or `game status` with a window |
| loaded | The running engine reports the expected mod and map | `game check-load` with `verified: true` and `state_matches: true` for the load ID |
| playable | A person or a vision-capable agent saw a spawned character that can move | Human observation, or an inspected frame; never the CLI alone |
| captured | Frames or a recording of the playable state exist and were inspected | A decoded, non-black frame someone looked at |
| accepted | The player recorded a verdict on a named behaviour in a named scope | The player's words, tied to the exact package hash and map |

Say the highest rung you reached and the first one you did not. "Offline verified; not
installed" and "loaded; playable not observed" are complete reports.

## Route vocabulary

- **route**: one `pat <group> <action>`; `pat manifest --json` lists them all.
- **status** (`available`, `implemented`, `planned`, `deferred`, `unsupported`): how far the
  *toolkit code* for a route has been proven. Defined in `docs/SUPPORT.md`. `available` means a
  native receipt exists; `implemented` means the code runs but no native receipt exists.
- **evidence level** (`contract`, `offline`, `native`, `game`, `accepted`): the row in
  `docs/SUPPORT.md` for a route. Do not mix it with the ladder above, which is about a *mod*.
- **receipt**: the `receipt.json` a job writes, plus the stdout JSON and exit status of the
  invocation. Together they are the fact; prose about them is not.
- **native**: ran on a real Windows or Linux host, not Wine, WSL or a CI runner.

## Mod vocabulary

- **backend**: an upstream program the toolkit runs (`docs/BACKENDS.md`).
- **fastfile** (`.ff`): the T6 archive the engine loads; a mod ships one named `mod.ff`.
- **zone**: the text list of assets that the linker packs into one fastfile.
- **rawfile**: an asset stored as bytes, such as a compiled script.
- **foundation**: the unmodified base a module is built and tested on (`foundations.md`).
- **module**: one feature with its own source, recipe and receipt.
- **composition**: a named set of modules on a named foundation, built as one package.
- **normal / PAP**: a weapon's base form and its Pack-a-Punch upgraded form. A weapon is one
  feature with two forms; "finished" means both.
- **load ID**: the token `game load-map`, `select-mod` and the restarts return; `check-load`
  verifies it against the same process.
- **delivery uncertain**: a game command may or may not have taken effect. Terminal for that
  invocation; inspect fresh state, never resend.
