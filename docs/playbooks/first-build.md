# First build on this machine

Build the bundled `examples/hello-zm` with the real tools and prove it read back. This is the
smallest complete run of the development toolchain and the fixture every other playbook assumes.

## Preconditions

- `pat version --json` returns `ok: true` (the toolkit is installed for this user).
- One `pat doctor --json`: `backends.backends[]` shows `gsc` and `oat` with `present: true`, or
  `download_available: true` so setup can fetch them. On a platform with a `note` saying it is
  untested, stop and relay the note.
- A scratch directory outside the repository for outputs, for example `../jobs`.

## Steps

1. Install the two required backends if `doctor` showed them missing:
   ```sh
   pat dev setup --only gsc oat --json
   ```
   Proof: each row in `result.results[]` has `action: installed` or `verified`.
2. Plan the example without running a backend:
   ```sh
   pat project plan examples/hello-zm/project.json --output ../jobs/hello-plan-001 --json
   ```
   Proof: `ok: true`, `result.backends_available: true`, `result.scripts: 1`.
3. Build it:
   ```sh
   pat project build examples/hello-zm/project.json --output ../jobs/hello-build-001 --json
   ```
   Proof: `ok: true`, `result.mod_ff` equals `packages/mod.ff`, `result.rawfiles_verified: 1`;
   the receipt at `../jobs/hello-build-001/receipt.json` has `status: succeeded` and three
   `steps` (Linker, Unlinker list, Unlinker readback) with `exit_code: 0`.
4. Verify the receipt against the inputs:
   ```sh
   pat project verify ../jobs/hello-build-001/receipt.json --inputs --output ../jobs/hello-verify-001 --json
   ```
   Proof: `ok: true`.
5. Record the package hash from `receipt.json` `outputs["packages/mod.ff"]`. On the two hosts the
   toolkit is qualified on, this hello-zm build produces byte-identical `mod.ff` files; a
   different hash means a different tool version or a changed script, both worth noting.

## Do not

- Run `pat manifest` or `pat doctor` again between steps; nothing changed.
- Rebuild into the same `--output`; the toolkit refuses, and deleting the directory to retry
  discards the receipt. Use a new name.
- Run `pat dev setup` without `--only` for a first build; it installs every required backend and
  the media backends are large.
- Touch the game. Nothing in this playbook needs it.

## Stop conditions

- Any step returns `ok: false`: stop, read `error_code` and `hint`, open the step log the receipt
  names, and fix the cause. `backend_unavailable` names the `dev setup` to run;
  `hash_mismatch` on setup means the download did not match the pin (keep the file, open an
  issue with the URL and hash; never edit the pin).
- `doctor` carries a `note` naming the platform untested: stop and relay.
- The build succeeds: the playbook is complete. Installing and loading are
  `package-and-install.md`, and need the user's go for the game steps.

## Report

State separately: **offline verified** (the build and verify receipts, the `mod.ff` hash);
**installed** (not done here); **launched / loaded / playable** (not done here). Name the
backend versions from `pat dev backends --json` and the host OS.
