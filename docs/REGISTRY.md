# Registries: published modules and packs by name

A **registry** is a file anyone can host: `registry.json`, listing module and composition
repositories at exact commits. It holds no bytes. The toolkit reads registries you record,
searches them offline, and fetches one entry's repository snapshot at its listed commit into a
new output directory with a receipt. Words: `CONTEXT.md` (registry, catalog, entry, reference).
Formats for what a registry points at: `docs/MODULES.md`.

Nothing in the toolkit talks to the network except `dev setup` (pinned backends), `registry
add` with an https URL (one file) and `module fetch` (one exact-commit snapshot). All three say
so in `pat describe`. `registry baseline` (below) is the static check a registry runs on a
snapshot before listing it and a submitter runs first; it reads files and nothing else.

## The file

```json
{
  "schema": 1,
  "name": "plutonium-module-registry",
  "description": "Modules and packs for Plutonium T6 Zombies, listed at exact commits",
  "entries": [
    {
      "name": "sickohours/hello_zm",
      "kind": "module",
      "repository": "https://github.com/SickoHours/plutonium-agent-toolkit",
      "path": "examples/hello-zm",
      "listed": {"commit": "<40 hex>", "at": "2026-09-11", "branch": "main"},
      "distribution": "source",
      "declaration": {"id": "hello_zm", "version": "0.1.0", "title": "hello-zm", "category": "scripts",
                      "kind": "script", "tags": ["example"], "bases": ["stock"], "maps": ["*"]},
      "verification": {"snapshot_status": "unverified"},
      "history": []
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `name` (registry) | A lowercase identifier; the file is stored under it, and adding the same name again replaces the copy |
| `entries[].name` | `<github-owner>/<module id>`, lowercase. Ownership is proven by the repository living under that owner; an entry whose repository lives elsewhere is refused. `plutonium/`, `pat/` and `stock/` are reserved |
| `kind` | `module` (a directory with `module.json`) or `composition` (a directory with `composition.json`) |
| `repository`, `path` | The GitHub repository and the directory inside it. Only GitHub repositories are fetched in this version |
| `listed.commit` | The 40-hex commit the entry was listed at. Everything about the entry refers to that snapshot; a moved branch changes nothing here |
| `distribution` | `source`, `seed` or `private`, as in the declaration |
| `declaration` | A summary copied from the declaration at the listed commit, for search: id, version, title, category, kind, tags, bases, maps, provides. The fetched declaration is the fact; this is a projection |
| `verification` | What the registry's own checks say about the snapshot: `snapshot_status` of `unverified`, `snapshot verified` or `update unverified` (a later commit exists that nobody checked). Never a trust score |
| `history` | Earlier listings, appended, never rewritten |

The **catalog** is a generated, browseable projection of one or more registries (`catalog.json`
plus pages); it is not part of this release. The official registry repository, its issue forms
and its verification workflows are described in issue #23 and follow the same file.

## The registry that ships with the toolkit

One registry is always present without `registry add`: the toolkit's own, named
`plutonium-agent-toolkit-builtin` (`examples/registry.json` lists the same entries under an addable name). It lists the
modules and packs the release ships as **built-ins**, at the exact commit the release pins.
`pat dev builtin` fetches them onto the machine: one HTTPS snapshot per repository and commit,
hashed and extracted with the archive safety checks, laid out under
`<toolkit home>/modules/builtin/<owner>/<repository>/<commit>/<path>` so a pack's relative member
paths keep resolving, with a receipt per entry and pinned commit under `modules/builtin/receipts/` (a release that moves a
pin fetches the new snapshot beside the old one, which stays accounted for). A rerun re-hashes
every kept file and the recorded directories and answers `verified`; a tree with a changed, missing or added
file is refused with `artifact_changed` and never overwritten; `--plan` reports the state without touching the network. `registry list`, `search` and
`show` carry each registry's `origin` (`builtin` or `added`), `search --origin builtin` lists only
the built-ins, and a built-in hit carries `builtin_dir` once it is fetched. The name is reserved:
`registry add` refuses a file that claims it. An added registry that lists a built-in at the same
commit (the official registry does) adds its name under the hit's `also_listed_by` rather than a
second hit; a listing at another commit is its own hit.

Built-in, fetched and installed are three places (`CONTEXT.md`): the shelf under the toolkit home,
the `module fetch` job directories you chose, and the profiles under Plutonium's `mods`. A built-in
is planned and built like any other module (`pat module plan <builtin_dir>/composition.json --output
<new dir> --json`); nothing under `dev builtin` installs anything into the game.

## Routes

| Command | What it does | Result to keep |
| --- | --- | --- |
| `pat registry add <file or https URL>` | Validates the registry and copies it under the toolkit home (`registries/`). Re-adding a name replaces the copy | `name`, `entries`, `sha256` |
| `pat registry list` | The registries on this machine: the built-in one first, then the ones you added, each with its `origin` | `registries[]` |
| `pat registry search [words] [--category …] [--kind …] [--tag …] [--base …] [--map …] [--entry-kind module|composition] [--origin builtin|added]` | Matches the declaration summaries in the built-in and every recorded registry; offline | `hits[].name`, `hits[].commit`, `hits[].fetch`, `hits[].builtin_dir` |
| `pat dev builtin [--plan] [--only <owner/id>]…` | Fetches the built-in modules and packs at their pinned commits under the toolkit home with a receipt per entry; a rerun verifies, a changed tree is refused | `results[].module_dir`, `results[].action`, `downloads[]` |
| `pat registry show <owner/id>` | Every listing of one name, with its fetch command and snapshot URL | `listings[]` |
| `pat module fetch <owner/id@commit> --output <new dir>` | Resolves the name through the recorded registries (the commit must equal the listed one), downloads the exact-commit tarball over HTTPS, hashes it, extracts it with the archive safety checks, and confirms `module.json` or `composition.json` is at the entry's path. The fetched declaration must name the same repository and commit when it names any | `module_dir`, `commit`, `archive_sha256`, `facts` |
| `pat module fetch <https://github.com/owner/repo@commit> [--path <dir>] --output <new dir>` | The same for a repository no registry lists; say so in your report | same |
| `pat registry baseline <directory> [--repository <url>] [--commit <40 hex>] --output <new dir>` | A static, deterministic check of a module or composition directory (below). Reads every eligible file and nothing else (`.git`, links and unreadable entries are listed, not read); executes nothing, runs no backend, uses no model | `outcome`, `findings[]`, `capabilities[]`, `warnings[]`, `unreadable[]`, `baseline.json` |

A fetched module directory is named in a composition as a reference member, so the pack records
what it was built from:

```json
{"name": "sickohours/hello_zm", "commit": "<40 hex>", "path": "../jobs/fetch-001/repository/examples/hello-zm"}
```

## Baseline

A **baseline** is the static check a registry runs on a snapshot before it lists the entry, and
the check a submitter's agent runs offline first, on the same directory, so the listing holds no
surprise. `pat registry baseline <directory> --output <new dir> --json` reads every eligible
file under the directory and nothing else (`.git`, links and other skipped entries are recorded
without reading their contents or targets): it executes nothing in the tree, runs no backend,
uses no model and touches no network. The same bytes always give the same `baseline.json`; the report carries
the tree's hash (`tree_sha256`) so two scans can be compared. Give `--repository` and `--commit`
when the listing's values are known; the declaration's `source` is compared with them.

**A baseline is a static check of files; it is not a security audit, certification, warranty or
endorsement.** The report says so in its own `not_a_security_audit` field. It names what a read
of the files can see so a person can review it; it proves nothing about play, and a `passed`
baseline is not a claim that the module is safe.

Policy version `1`, enforcement `selective`: exactly three finding ids block a listing. Every
other finding, every capability and every warning is reported for a reviewer.

| Row | Kind | Blocks | What the files showed |
| --- | --- | --- | --- |
| `native-plugin` | finding | yes | A file whose first bytes are a PE (`MZ`), ELF or Mach-O executable (thin and universal headers, both byte orders), whatever its name; or text naming Plutonium's `plugins` folder or a `plugins/<name>.dll` path |
| `download-and-execute` | finding | yes | `iex (iwr ...)`, `Invoke-Expression`, `curl ... \| sh`, `wget ... \| sh` (also `bash`, `zsh`); or a file a script downloads (`-o`, `--output`, `-OutFile`, `-Destination`, or the URL's file name on a `curl`, `wget`, `Invoke-WebRequest`, `Start-BitsTransfer` or `DownloadFile` line) and later starts in the same file with `Start-Process`, `&` or a `./` / `.\` prefix |
| `path-escape` | finding | yes | A link anywhere in the tree; an absolute path or a Windows drive (`C:x`, `D:\x`, `\\server\x`) in any `source`, `target`, `recipe`, `seed`, `path`, `modules[]` or `loads[]` value of `module.json`, `project.json` or `composition.json`; a `..` segment in a path the formats confine to their own directory (`recipe`, `seed`, and a recipe's `source`, `target` and `loads`); and any declared directory or file that resolves outside the scanned directory. A composition names sibling directories with `..` by design (`docs/MODULES.md`), so a pack is scanned from the directory that holds the pack and every member it names (the repository root, or the directory holding the pack and its members); scanned from its own directory, its siblings are outside the snapshot and are reported. Members and loads inside the tree must exist and not be links |
| `unpinned-acquisition` | finding | no | An `http(s)` URL ending in `.zip`, `.tar.gz`, `.tgz`, `.7z`, `.rar`, `.ff`, `.ipak`, `.exe` or `.msi` with no 64-hex SHA-256 on the same line or the next five |
| `declaration-mismatch` | finding | no | `source` not an object, or `source.repository` / `source.commit` present but not an https URL / a 40-hex commit (a number, a list, a short id); either present, well-formed and different from `--repository` / `--commit`; a `recipe`, `seed` or member path missing on disk; `bases` or `maps` present but empty or not a list; a declaration that is not valid JSON, not text, or above the text bound. Without the options the form and on-disk checks still apply, only the comparison is skipped |
| `installer` | capability | no | A file named `install*`, `setup*` or `uninstall*` (any extension), or any `.bat`, `.cmd`, `.ps1`, `.sh`, `.exe` or `.msi` |
| `bundled-package` | capability | no | A `.ff`, `.ipak`, `.sabl` or `.sabs` file, with its size. Seeds are legitimate; the reviewer sees them |
| `lua-ui` | capability | no | A `.lua` file, or a path through a `ui/` or `ui_mp/` directory |
| `file-io` | capability | no | A GSC/CSC script calling `fs_fopen`, `fs_write`, `fs_writeline`, `fs_read`, `fs_readline`, `fs_remove`, `fs_listfiles` or `fs_fclose` |
| `client-dvar` | capability | no | A GSC/CSC script calling `setClientDvar` or `setClientDvars` |
| `function-replacement` | capability | no | A GSC/CSC script calling `replaceFunc` |
| `command-hook` | capability | no | A GSC/CSC script calling `notifyOnPlayerCommand` |
| `global-tooling` | capability | no | A recipe `target`, or any declared path, that begins with `raw/scripts/`: Plutonium loads it for every profile |
| `bundled-assets` | capability | no | Binary files (a null byte in the first 8 KiB) totalling more than 8 MiB, with the total |
| `large-text` | capability | no | A text file above 4 MiB: hashed and counted, not pattern-scanned |
| `no-resource-contract` | warning | no | `module.json` declares no `resource_contract` (`docs/MODULES.md`) |

Outcomes: `passed` (no finding and no capability; warnings may be present), `review-required`
(a non-blocking finding or a capability to look at), `needs-fixes` (a blocking finding) and
`incomplete` (a file or directory could not be read; listed under `unreadable` and treated like
`needs-fixes`, so the scan fails closed). `blocked` is true for the last two. Every row has the
same shape: `id`, `kind` (`finding`, `capability`, `warning`), `blocking`, `file` (relative,
forward slashes), `line` (or null) and a short `evidence` excerpt of at most 160 characters.
Rows are sorted by file, line and id. Findings keep at most 20 rows per file and rule and count
the rest under `truncated`; nothing is skipped silently: links, `.git` and unreadable entries
are all listed. Bounds: 20 000 files and 2 GiB per tree (`input_limit` above them, counted from
the bytes actually read, so a file that grows during the scan cannot slip past; directory
entries of every kind, links included, and the scanned directory itself count as they are
listed; the same 20 000 is the job's cap on recorded inputs, so a tree the scan admits is never
refused at the receipt), 4 MiB of text per file, 64 directory levels, 64 levels of nesting
inside a declaration (deeper paths are reported as not checked; a declaration the parser
cannot follow is `declaration-mismatch`, never a toolkit defect). The directory given must be
a real directory, not a link (`input_invalid`).
On POSIX every directory and file is opened relative to its
parent's descriptor, without following links and without blocking, and the open descriptor must
be the regular file or directory the listing saw; Windows has no descriptor-relative opens, so
every path component is re-checked for reparse points by name just before each open. An entry
replaced under the scan (by a link, a pipe, another file, or a swapped ancestor directory) is
`unreadable` and the outcome `incomplete`. Every file read and every directory listing is an
input of the job: the receipt lists their hashes (`inputs`, `input_listings`; a listing is every
entry's name and kind) and the job re-hashes and re-lists them before succeeding, so a file
changed, added, removed or swapped for a link of the same name after the scan is
`input_changed`, never a report for an older tree. The job deadline (`--timeout`) is checked
between chunks of every read. File names that are not UTF-8 are hashed as their bytes and
shown with backslash escapes. The result and
`baseline.json` carry `policy_version`, `enforcement`, `outcome`, the three row lists,
`scanned` (files, bytes, text and binary counts), `unreadable`, `skipped`, a `declaration`
summary when `module.json` or `composition.json` is at the root, and `nested_declarations` for
every module or pack below it (a repository scanned from its root lists them all).

Before listing, a submitter runs the baseline on the directory the entry will point at, at the
commit it will name, and fixes every blocking row; `docs/playbooks/publish-a-module.md` is the
sequence. A registry that runs the same policy version on the same commit gets the same report,
which is what makes `snapshot_status` reproducible.

## What a listing is, and is not

- A listing is what a registry claimed at that commit. Fetch, plan and build; the receipts are
  the facts. `snapshot_status` describes the registry's own static checks on that snapshot,
  never gameplay, and never a security audit, certification, warranty or endorsement.
- A `private` module is listed with its declaration and manifest so others can plan around it;
  fetching it yields no package, and `module plan` says which file is missing.
- Version strings are recorded, not compared. A composition pins commits.

## Publishing

Put `module.json` beside your payload (`docs/MODULES.md`), fill `source.repository` and
`source.commit`, and list the entry in a registry file you host, or submit it to the official
registry when that exists. Ship only what you have the right to publish; a seed whose package
cannot be published is `distribution: private`.

## What is not here

- No catalog generation in this version; issue #23 tracks it. The official registry repository
  is `github.com/SickoHours/plutonium-module-registry`: add it with
  `pat registry add https://raw.githubusercontent.com/SickoHours/plutonium-module-registry/main/registry.json`
  and submit entries through its issue form. The baseline above is the static check such a
  registry runs on a submission; the toolkit does not run it automatically on anything.
- The baseline reads bytes and patterns, not behaviour: an obfuscated script, a payload inside
  a fastfile, or a GSC feature outside the listed builtins is not seen. It is not a security
  audit.
- No non-GitHub hosts, no git protocol, no authentication: public repositories only.
- No version constraints, no automatic updates, no popularity signals.
