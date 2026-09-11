# Registries: published modules and packs by name

A **registry** is a file anyone can host: `registry.json`, listing module and composition
repositories at exact commits. It holds no bytes. The toolkit reads registries you record,
searches them offline, and fetches one entry's repository snapshot at its listed commit into a
new output directory with a receipt. Words: `CONTEXT.md` (registry, catalog, entry, reference).
Formats for what a registry points at: `docs/MODULES.md`.

Nothing in the toolkit talks to the network except `dev setup` (pinned backends), `registry
add` with an https URL (one file) and `module fetch` (one exact-commit snapshot). All three say
so in `pat describe`.

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

A fetched module directory is named in a composition as a reference member, so the pack records
what it was built from:

```json
{"name": "sickohours/hello_zm", "commit": "<40 hex>", "path": "../jobs/fetch-001/repository/examples/hello-zm"}
```

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

- No catalog generation and no baseline scanner in this version; issue #23 tracks them. The
  official registry repository is `github.com/SickoHours/plutonium-module-registry`: add it with
  `pat registry add https://raw.githubusercontent.com/SickoHours/plutonium-module-registry/main/registry.json`
  and submit entries through its issue form.
- No non-GitHub hosts, no git protocol, no authentication: public repositories only.
- No version constraints, no automatic updates, no popularity signals.
