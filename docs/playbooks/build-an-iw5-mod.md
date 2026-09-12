# Build an IW5 (Modern Warfare 3) mod and put it where Plutonium looks

Build a multiplayer mod for Plutonium IW5 from a recipe, prove the package offline, install it
under the IW5 storage, and hand the console line to the person. Facts: `docs/knowledge/iw5.md`;
tools: `docs/knowledge/iw5-tools.md`. Nothing here loads the game.

## Preconditions

- `pat dev setup` has installed `gsc` and `oat` (`pat dev backends --json` lists both present).
- The recipe names `"game": "iw5"` and `"mode": "mp"`; every script row is a server `.gsc`.
- Any `#include` line names a file that exists beside the script, or is left out during the
  check; Plutonium resolves stock includes itself at load.
- If the mod carries stock assets, the game's own fastfiles are on disk
  (`<game>/zone/english/common_mp.ff`, `ui_mp.ff`), not the ones under `storage/iw5/zone`.

## Steps

1. Start from the example or a fresh recipe.
   ```sh
   pat project init --name <name> --game iw5 --output <new dir> --json
   ```
   Proof: `ok: true`; `project.json` reads `"game": "iw5"`, `"mode": "mp"` and the script target
   `scripts/<name>.gsc`.
2. Check every script alone before the recipe. This is the compiler's dry run; it writes nothing.
   ```sh
   pat gsc check <dir>/scripts/<name>.gsc --game iw5 --output <new dir> --json
   ```
   Proof: `ok: true` and `result.checked` names the file. `backend_failed` with
   `details.first_error` is gsc-tool's own line: fix the script. A missing include is reported as
   `couldn't open file .../<include>.gscbin`; drop the include for the check or dump the stock
   tree beside the script with `-w`.
3. Plan the recipe.
   ```sh
   pat project plan <dir>/project.json --output <new dir> --json
   ```
   Proof: `ok: true`, `result.game` is `iw5`, `result.mode` is `mp`. A `client` instance or a
   `.csc` target is refused with `input_invalid`: IW5 has one server VM.
4. Build. The source is packed as the rawfile; gsc-tool runs only as the gate.
   ```sh
   pat project build <dir>/project.json --output <new dir> --json
   ```
   Proof: `ok: true`, `result.script_form` is `source`, `result.rawfiles_verified` counts every
   script, the zone header in `project/zone_source/mod.zone` begins `> game,IW5`, and the
   packed `mod.ff` starts with the bytes `IWffu100`. Read the rawfile back from
   `readback/scripts/<name>.gsc`: it must be your text, not bytes beginning `GSC`.
5. Carry stock assets when the mod needs them. Name each root in the recipe's `assets` with its
   OpenAssetTools type and add the stock zone to `loads`; a weapon root pulls its models,
   materials, images, effects and sounds with it.
   Proof: `pat ff inspect <build>/packages/mod.ff --load <game>/zone/english/common_mp.ff
   --output <new dir> --json` lists the root and its dependencies with `game` reading `IW5`.
   `backend_failed` with the hint about zone version 2000 means a Plutonium-shipped zone was
   loaded instead of the game's.
6. Verify when the build will be reused.
   ```sh
   pat project verify <build>/receipt.json --inputs --output <new dir> --json
   ```
   Proof: `result.outputs.verified` and `result.inputs.verified` are `true`.
7. Install into the IW5 storage. The fastfile magic selects the storage key.
   ```sh
   pat configure --plutonium-storage-iw5 <abs path to storage/iw5>
   pat game install-mod <build>/packages/mod.ff <folder> --json
   ```
   Proof: `result.game` is `iw5`, `result.path` is `mods/<folder>/mod.ff`, `result.next` carries
   the console line. Loose images or sounds the mod needs go into a zip named `<anything>.iwd`
   beside `mod.ff`, paths as the engine asks for them.
8. Hand over. Give the person `fs_game mods/<folder>` for the console (or `loadmod <folder>`),
   and say a private match must be started after it. Proof: the message names the folder that
   was installed and says the build is offline verified, not loaded.

## Do not

- `pat gsc compile --game iw5` for a recipe script: the bytecode is not what Plutonium runs.
- Load or inspect `storage/iw5/zone/*.ff`: version 2000, unreadable by the pinned backend.
- Put a map under `mods/`: custom maps live in `usermaps/<map>/`.
- Promise custom sounds from a recipe: OpenAssetTools has no IW5 sound source loader.
- `pat game select-mod` or any live route for IW5: none exists; the console line is the handoff.

## Stop conditions

- `gsc check` fails on a stock include: stop and decide with the person whether to dump the stock
  scripts beside the mod or drop the include for the gate.
- The readback rawfile is not the source text: the title seam is broken; do not install.
- No IW5 storage is configured and the person cannot say where it is.
- A dependency only exists in a zone the backend cannot read.

## Report

Offline verified: the `mod.ff` hash, `script_form: source`, the zone header, the readback.
Installed: the folder and storage path from the install receipt. Launched, loaded and playable,
captured, accepted: each a separate no; IW5 has no receipt past installed from this toolkit. Name
the platform and backend pins from the receipt, and say that the first in-client result on a
Windows host with the game should be recorded with `qualify-on-this-host.md`.
