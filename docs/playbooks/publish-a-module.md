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
- No file in the tree is a native executable or a link, and no script downloads and runs
  anything: those are the three findings the baseline in step 2 blocks on (`docs/REGISTRY.md`).

## Steps

1. Make sure the snapshot is exactly what you tested: `git status` is clean and the commit is on
   the remote. Proof: `git rev-parse HEAD` equals the pushed commit.
2. Run the baseline a registry will run, on the directory the entry will point at, with the
   repository and commit the listing will name:
   ```sh
   pat registry baseline <module or pack directory> --repository <https url> --commit <40 hex> --output ../jobs/baseline-001 --json
   ```
   Proof: `ok: true` and `result.outcome` is `passed` or `review-required`; `result.blocked` is
   false. Fix every row with `blocking: true` (`native-plugin`, `download-and-execute`,
   `path-escape`) and every `unreadable` entry, commit, and rerun into a new output. Read the
   `capabilities` rows: they are what a reviewer will ask about, so the listing's description
   should already say why each one is there. A baseline is a static check of files, not a
   security audit; it says nothing about play.
3. Write or extend a registry file (`registry.json`) with one entry: `name` as
   `<github-owner>/<module id>`, `kind`, `repository`, `path`, `listed.commit` (40 hex), and the
   `declaration` summary copied from `module.json`. Proof: `pat registry add registry.json --json`
   returns `ok: true` with the entry count.
4. Fetch your own listing back the way a stranger would:
   ```sh
   pat module fetch <owner/id>@<commit> --output ../jobs/fetch-self-001 --json
   ```
   Proof: `ok: true`, `result.facts.id` equals your module id, `result.kind` is right, and no
   `declaration-mismatch` was raised.
5. Plan from the fetched copy, not from your working tree:
   ```sh
   pat module plan <a composition naming result.module_dir> --output ../jobs/plan-self-001 --json
   ```
   Proof: `ok: true`. If the module is `private`, the plan names the missing package; that is the
   expected outcome for a stranger.
6. Host the registry file where you like (the repository itself is fine), or submit the entry to
   the official registry when one exists, following its issue form. An agent fills the form and
   shows it to you; it files only on your explicit go.

## Do not

- List a branch name, a tag, or a short commit; only the 40-hex commit pins a snapshot.
- Commit game assets, recordings, logs, credentials or personal paths into the module.
- Call a listing verified, safe or trusted; a registry lists, receipts prove. A passed baseline
  is a static check of files, not a security audit or an endorsement.
- Rewrite an earlier listing; append to `history` and change `listed`.
- Work around a blocking baseline row by renaming or hiding the file; fix the cause, or do not list.

## Stop conditions

- Step 2 returns `needs-fixes` or `incomplete`: fix the blocking rows or the unreadable entries,
  commit, and start again from step 1 with the new commit.
- Step 4 raises `declaration-mismatch`: fix `source` in the declaration, push, list the new commit.
- Step 5 refuses for a reason a stranger could not fix (a private dependency, an undeclared base):
  fix the declaration, or state the limit in the listing's title.
- Step 5 passes: the listing is complete. Nothing here says anything about play.

## Report

State: the entry name and commit; where the registry file is hosted; the baseline outcome with
its `tree_sha256` and every capability row it listed; the fetch receipt of your own listing;
**offline verified** (the build receipt the listing points at, by hash); and that installed,
launched, playable and accepted are earned per user, per base and per map, never by a listing.
