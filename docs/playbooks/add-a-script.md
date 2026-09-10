# Add or change a script in a mod

Add a server (`.gsc`) or client (`.csc`) script to a recipe-based mod, compile it alone first,
then rebuild the mod and prove the new bytes are in the package.

## Preconditions

- The mod has a `project.json` recipe (`pat project init --name <name> --output <dir>` makes
  one) and has built once (`first-build.md`).
- You have read `docs/knowledge/gsc.md`: which VM the script runs in, what it may call, what it
  must clean up.
- The script uses only engine builtins, or you have the include directory that defines the
  helpers it calls.

## Steps

1. Write the script under the mod's `scripts/` directory. Choose the side by suffix: `.gsc` for
   server logic, `.csc` for client effects and HUD fields.
2. Compile it alone before touching the recipe:
   ```sh
   pat gsc compile <mod>/scripts/<name>.<gsc|csc> [--includes <dir>] --output ../jobs/<name>-compile-001 --json
   ```
   Proof: `ok: true` and `result.files[]` lists one non-empty compiled file. A failure returns
   `backend_failed` with `details.first_error`: the compiler's own first error line. Fix and
   compile into a new output.
3. Add the script to the recipe's `scripts` array with its source path, its target inside the
   package (`scripts/zm/<name>.gsc` for a Zombies mod script) and, when the suffix does not say,
   its `instance`.
4. Plan, to validate the recipe without running a backend:
   ```sh
   pat project plan <mod>/project.json --output ../jobs/<mod>-plan-NNN --json
   ```
   Proof: `ok: true` and `result.scripts` increased by one. `input_invalid` names the recipe
   row that is wrong (target collision, bad instance, path escape).
5. Build and verify:
   ```sh
   pat project build <mod>/project.json --output ../jobs/<mod>-build-NNN --json
   pat project verify ../jobs/<mod>-build-NNN/receipt.json --inputs --output ../jobs/<mod>-verify-NNN --json
   ```
   Proof: build `result.rawfiles_verified` equals the number of scripts plus rawfile assets;
   the receipt's `inputs` include your script's path and hash.
6. Compare the receipt's `inputs` hashes with the previous build's to confirm exactly the
   intended files changed.

## Do not

- Rebuild after every edit without compiling alone first; a compile is faster and its error is
  more precise.
- Rebuild without a changed input; the receipt already records the hashes.
- Put the output inside the mod's source tree; the toolkit refuses it.
- Fix an "unresolved" helper by adding a wrapper with the same name; find the include the engine
  actually exports it from.
- Treat the build as a test of the script's behaviour. It proves the bytes compiled and packed.

## Stop conditions

- The compiler reports an error the script cannot avoid (a builtin that is not exposed on this
  side, a helper without a known include): stop and report which call, with the first error line.
- The build succeeds and verify passes: complete. Loading it is `package-and-install.md`; watching
  it run needs the game and the user's go.

## Report

State: **offline verified** (compile and build receipts, the package hash); which VM the script
targets; what the script does that no offline check can prove (its runtime behaviour, cleanup
under down/respawn/disconnect); and that it is **not installed** and **not loaded**.
