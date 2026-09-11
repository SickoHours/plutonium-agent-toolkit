# Publish a module or pack

List a module or a composition so other people's agents can fetch it by name at an exact commit.
Words: `CONTEXT.md` (registry, entry, reference). Formats: `docs/MODULES.md`, `docs/REGISTRY.md`.

## Preconditions

- The module directory holds `module.json` beside its payload, or the pack directory holds
  `composition.json`, and it builds (`compose-a-pack.md` or `first-build.md`).
- The repository is public on GitHub under the owner whose name the entry will carry, and the
  commit to list is pushed.
- Every asset in the tree is one you have the right to publish. A seed whose package cannot be
  published stays out of the tree and the declaration says `distribution: private`.
- The declaration's `source.repository` is the repository URL and `source.commit` is the commit
  you are about to list, or `source` is absent. A mismatch is refused at fetch time.

## Steps

1. Make sure the snapshot is exactly what you tested: `git status` is clean and the commit is on
   the remote. Proof: `git rev-parse HEAD` equals the pushed commit.
2. Write or extend a registry file (`registry.json`) with one entry: `name` as
   `<github-owner>/<module id>`, `kind`, `repository`, `path`, `listed.commit` (40 hex), and the
   `declaration` summary copied from `module.json`. Proof: `pat registry add registry.json --json`
   returns `ok: true` with the entry count.
3. Fetch your own listing back the way a stranger would:
   ```sh
   pat module fetch <owner/id>@<commit> --output ../jobs/fetch-self-001 --json
   ```
   Proof: `ok: true`, `result.facts.id` equals your module id, `result.kind` is right, and no
   `declaration-mismatch` was raised.
4. Plan from the fetched copy, not from your working tree:
   ```sh
   pat module plan <a composition naming result.module_dir> --output ../jobs/plan-self-001 --json
   ```
   Proof: `ok: true`. If the module is `private`, the plan names the missing package; that is the
   expected outcome for a stranger.
5. Host the registry file where you like (the repository itself is fine), or submit the entry to
   the official registry when one exists, following its issue form. An agent fills the form and
   shows it to you; it files only on your explicit go.

## Do not

- List a branch name, a tag, or a short commit; only the 40-hex commit pins a snapshot.
- Commit game assets, recordings, logs, credentials or personal paths into the module.
- Call a listing verified, safe or trusted; a registry lists, receipts prove.
- Rewrite an earlier listing; append to `history` and change `listed`.

## Stop conditions

- Step 3 raises `declaration-mismatch`: fix `source` in the declaration, push, list the new commit.
- Step 4 refuses for a reason a stranger could not fix (a private dependency, an undeclared base):
  fix the declaration, or state the limit in the listing's title.
- Step 4 passes: the listing is complete. Nothing here says anything about play.

## Report

State: the entry name and commit; where the registry file is hosted; the fetch receipt of your
own listing; **offline verified** (the build receipt the listing points at, by hash); and that
installed, launched, playable and accepted are earned per user, per base and per map, never by
a listing.
