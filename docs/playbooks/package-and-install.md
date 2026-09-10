# Package and install a verified build

Copy a verified `mod.ff` into the client's storage folder under a named mod folder, without
touching a running game. Loading it is a separate, user-authorized step and is described at the
end.

## Preconditions

- A build receipt with `status: succeeded` and a `packages/mod.ff` output, verified with
  `pat project verify ... --inputs` (`first-build.md` or `add-a-script.md`).
- `pat configure --plutonium-storage-t6 <absolute path>` has been run on this machine, so the
  toolkit knows where `mods/` is. `pat doctor --json` shows `configuration.ok: true`.
- The destination folder name follows `<base>_<feature>_<stage>` (`docs/knowledge/foundations.md`)
  and is a valid folder ID (letters, digits, underscore, dot, dash).

## Steps

1. Check what is installed:
   ```sh
   pat game mods --json
   ```
   Proof: `result.mods[]`; note whether the destination folder already exists.
2. Install:
   ```sh
   pat game install-mod ../jobs/<mod>-build-NNN/packages/mod.ff <base>_<feature>_test --json
   ```
   Proof: `ok: true`, `result.sha256` equal to the build receipt's `outputs["packages/mod.ff"]`.
   If the folder exists the toolkit refuses; add `--replace` only when you intend to move the old
   folder aside (it is moved, not deleted), and say so in the report.
3. Confirm the inventory:
   ```sh
   pat game mods --json
   ```
   Proof: the folder is listed with `available: true`.
4. Hand off. Loading needs a running client on Windows and the user's go for each command:
   `pat game select-mod <folder> --json` then `pat game load-map <map> --json`, then
   `pat game check-load <load-id> --json` with the returned `load_id`. `docs/GAME-CONTROL.md`
   has the sequence and what each result proves. On Linux, or without authorization, the
   playbook ends at step 3.

## Do not

- Rename `mod.ff`; a T6 fastfile is bound to its name and a renamed one cannot be read.
- Edit an installed folder in place; rebuild and reinstall.
- Run `select-mod`, `load-map` or any restart without the user's explicit go for that command.
- Treat an installed hash as proof of what the running game has loaded; only a checked load ID is.
- Install into a folder named after a composition or a "latest" pointer.

## Stop conditions

- `config_missing`: run the `configure` the hint names, then continue.
- The install receipt's hash differs from the build's: stop; the file on disk is not the verified
  build.
- Step 3 passes: **installed**. Everything further is a game operation.

## Report

State: **offline verified** (build and verify receipts); **installed** (install receipt path,
folder ID, hash, whether an old folder was moved aside); **launched / loaded / playable /
accepted**: not done, or done with the load ID and check result and what a person observed.
