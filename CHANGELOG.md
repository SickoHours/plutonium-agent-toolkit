# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/) (tags) with the equivalent PEP 440 form in code.
Every entry states what shipped, on which platform it was verified, and what remains unverified.

## [Unreleased]

### Added

- Add inert `module inspect <module.json|composition.json> --json` with the versioned
  `pat.module-inspect/1` producer schema, exact-byte SHA-256 and JSON Pointer diagnostics.
  Inspect and plan/build share declaration metadata checks; inspection requires no payloads,
  job directory, backend or network. Plan/build metadata failures gain an additive
  `details.field` JSON Pointer. Route status remains implemented (offline tests only).

- **`probe` composition stage.** `<base>_<feature>_probe` names a self-driving state-walk
  profile (one module plus a script that prints what it set); `pat module plan` accepts it beside
  `test`, `pack` and `pub`.

- **Frozen, first-class bases; dependency packs; origin and donor; the probe stage.**
  `docs/knowledge/foundations.md` and `CONTEXT.md` now state the base policy an authoring
  workspace settled on: a base is frozen and first-class, a module that supports several
  bases has one receipt per base, cards read declarations and receipts only; a feature that
  is several modules ships as a dependency pack whose members declare what they call; a
  module's title names its origin game and `donor` carries the credit; `probe` is a stage
  beside `test`, `pack` and `pub`. `port-a-feature.md` and `attach-to-a-pack.md` carry the
  matching preconditions and do-nots. Documentation only; no route or check changed.

### Fixed

- `module inspect` accepts symlinked ancestor directories like plan/build while still refusing
  a linked declaration and checking regular-file identity. Its diagnostic field/message and
  envelope message/hint are limited to 2048 UTF-16 code units, with error codes limited to 200 units;
  explicit omission notices replace excessive detail, and overlong pointers become `/`.
  Plan/build metadata errors again include the member directory in schema/game/id context.
  Usage failures are documented as invocation errors outside the inspection protocol.
  UTF-16 unit counting matches JavaScript consumers for supplementary Unicode; lone surrogates
  count without encoding errors and are JSON-escaped on inspect stdout without changing values.

- `docs/MODULES.md` no longer says there is no official registry repository (there is one,
  `docs/REGISTRY.md`); `publish-a-module.md` points at it. `docs/SUPPORT.md` no longer lists the
  MCP wrapper and control plane as unpackaged while grading them. The umbrella skill separates
  route status from evidence level instead of mixing the two ladders in one sentence.
  `PILOT-USER.md` and `REVIEWING-QUALIFICATION.md` drop a stale beta reference and a literal
  version in a generic instruction.

- **Origin, donor and evidence state, so a card can say where a thing comes from.** `module.json`
  and `composition.json` accept `origin` (one lowercase word for the game or series the identity
  comes from, or `unverified`; it drives the title, and is never defaulted to the donor) and
  `donor` (one line of credit for where the bytes came from; it drives the credit line, never the
  title). Both are validated, carried into `plan.json` per module and for the pack, and drafted by
  `module declare` (`origin` as `unverified`, since a package says nothing about identity). A
  registry entry's `declaration` summary may carry both, the entry may carry `evidence_state`, the
  highest build-evidence fact of `CONTEXT.md` the registry's own record supports for the listed
  snapshot (`none` by default; never a trust score), and `registry search` matches the origin word
  and returns `module_origin`, `donor` and `evidence_state` on every hit. The control plane's
  library summary lists both fields. `docs/MODULES.md`, `docs/REGISTRY.md`. Formats and offline
  tests only (`tests/test_compositions.py`, `tests/test_registry.py`); no route, receipt or
  evidence level changed and nothing here proves a module loads or plays.

- **Base-owned collisions and larger packs.** A composition may name `base_owned` listings of the
  base zones it loads; a name collision whose asset the base already carries resolves as
  `base-owned` with no decision, since both seeds got the copy by linking against the base. This
  is what a pack of modules each built alone on the same base produces by the hundred. Packs and built-in packs
  may hold 128 members and 1024 recorded decisions (were 32 and 256); seeds no longer count
  against the 32-load cap. Reference rows in a listing (`type, ,name`) are not base-owned. `plan` and `build` report `base_owned_names`.

- **IW5 (Modern Warfare 3) as a second title for the development tools.** `dev/titles.py` holds
  the per-title facts (gsc-tool token, script form, instances, modes, zone header, fastfile
  magic, storage key, browse taxonomy) so one code path serves both games. `gsc compile|check|
  decompile`, `project init`, `image convert` and `module declare` take `--game`; recipes,
  `module.json` and `composition.json` accept `game` (default `t6`); a composition refuses mixed
  titles and validates `kind` per title. **Scripts ship as source on IW5**: Plutonium IW5
  compiles GSC itself and runs no gsc-tool bytecode, so `project build` and `module build` pack
  the text and run the new `gsc check` (the compiler's dry run) as the gate; T6 is unchanged. IW5
  is `mp` and `server` only. `game install-mod` reads the fastfile magic (`TAff`, `IWffu100`) and
  routes to `plutonium_storage_t6` or the new `plutonium_storage_iw5`, printing the IW5 console
  line since that title has no Mods menu. `ff inspect` reports the game OpenAssetTools read and
  names the zone-version-2000 trap for the Plutonium-shipped IW5 zones. New pages
  `docs/knowledge/iw5.md` (the loading contract from primary sources), `docs/knowledge/iw5-tools.md`
  (every IW5 tool, what OpenAssetTools builds from source, how an agent drives the rest) and
  `docs/playbooks/build-an-iw5-mod.md`; `examples/hello-iw5`; `tests/test_iw5.py`. Verified
  offline on Linux and Windows with the pinned backends (`IWffu100` linked, read back as
  `Loaded zone "mod" (IW5)`, source rawfile byte-identical); nothing has run in an IW5 client and
  `docs/SUPPORT.md` grades every IW5 row `implemented`. Started from a community pull request
  (#40) whose compiled-script route was replaced.

- **Weapon-camo, weapon-aim, attachment and BO3 audio knowledge.** Four pages distilled from an
  authoring workspace's T6 port cycle. `docs/knowledge/weapon-camo.md` records how a `weaponCamo`
  asset renders (`materialOverrides`, per-gun `shaderConsts[0..1]` UV tiling scaled by measured UV
  density, `useColorMap`, animated technique sets), why runtime camo switching cleared a held gun,
  the one-weapon-per-camo design that avoided the unresolved option-index rule, and the four ways
  a ported gun gets the camo wrong with the player symptom and the offline check for each.
  `docs/knowledge/weapon-aim.md` records that donor `ads*` tuning does not transfer, that a native
  template of the right class can still be an outlier (the M1911's aim depth of field and its zoom
  field of view equal to the default), the rule to diff an inherited field block against the
  field's distribution across same-class weapons, the `tag_sights` against viewhands `tag_ads`
  geometry failure, and the rule not to derive the view model camera offline.
  `docs/knowledge/weapon-attachments.md` records that a BO3 weapon's sights or optic can be a
  separate runtime-mounted attachment model, how to list it from the WeaponDef/attachment rows
  and the name convention, how to capture it with the weapon held and fuse it at the donor bone's
  bind transform weighted to the gun root, and the native reticle and lens substitutions.
  `docs/knowledge/bo3-sab-audio.md` records the SAB v15 name table (`count`, `name_size`,
  `name_offset`), the `fLaC` carve at each entry's offset, the zone's sound-alias namespace and
  secondary chain, and the native-prototype-row fallback with the rule that a prototype row is a
  recorded adaptation rather than donor data. `docs/knowledge/README.md` indexes the four pages
  and `docs/playbooks/port-a-bo3-weapon.md` names the step each one gates. Docs only; no route,
  receipt or evidence level changed.
- **`pat workspace init <dir>`.** The missing half of the environment scaffold: a modding workspace of
  the person's own, outside the toolkit checkout, holding an `AGENTS.md` that tells any coding agent
  how to work there and names the checkout the skills refer to, `CLAUDE.md`, a README, an ignore file
  for packages and job outputs, the `modules/`, `compositions/`, `jobs/`, `receipts/`, `registries/`
  and `donors/` directories, and a hashed `workspace.json` record. Refuses a non-empty directory and
  any location inside the checkout; copies, downloads, launches and installs nothing. `SETUP-PROMPT.md`
  and `docs/GETTING-STARTED.md` make it the step after the skills. Status `implemented`
  (`docs/SUPPORT.md`).

- **The routes as MCP tools in any harness.** `pat mcp serve --library <dir> --jobs <dir>` speaks
  Model Context Protocol on stdin and stdout, exposing the control plane's typed actions as tools
  with JSON Schemas generated from their parameters, plus two local reads (`library`, `runs`). It is
  the plane's second transport, not a second runtime: the same validation by kind, the same
  structured `{"root", "path"}` for every path on this machine (`module fetch`'s `path` is not one
  of those: it names a directory inside the repository being fetched, and stays a relative string),
  the same refusal of an action this host cannot run,
  the same `confirmed: true` gate on a state-changing action, the same one-at-a-time `pat` child
  with its own receipt under the jobs directory. There is no tool that takes argv, a shell string or
  an absolute path. `pat mcp tools --json` prints the definitions and serves nothing. stdout carries
  only the protocol (everything else goes to stderr) and the invocation's own JSON document is the
  last line after the client disconnects; a reader thread keeps `--seconds` reachable while a
  harness is idle, a call still running at the deadline stops waiting, and a termination signal
  still stops the child and records it. The transport is bounded in both directions: a message is
  measured in encoded bytes against the 4 MiB it advertises, the reader holds one message at a time
  so a client that keeps sending waits in the pipe instead of in memory, a result too large to
  carry back is refused while it is being encoded rather than after, and a client that stops
  reading stdout blocks the writer thread instead of the loop -- the session then ends with the
  child stopped, no message still in hand is run, and the invocation's own document goes to stderr
  rather than blocking on the same full pipe. New effect `serves-stdio`; `docs/MCP.md` has
  the harness configuration, the tool table and the stdio contract. A call in progress keeps
  reading its client, so `notifications/cancelled` stops the child at once instead of after the
  route's own timeout, a second call is refused with `busy` while the first is still running
  rather than waiting unseen for its turn, a termination signal stops a running child instead of
  waiting for the route's timeout, and a string parameter's schema carries the pattern and the
  length its validator enforces (a prompt's is `MAX_PROMPT`, not the parameter default). Stdin
  closing deliberately does not stop a running call: a batch pipeline is exactly that shape.

- **Black Ops III Workshop maps as donors.** `docs/knowledge/bo3-workshop-formats.md` records
  what a Workshop item's fastfile, XPAK and sound banks are and how much of each reads offline on
  Linux (an unencrypted fastfile's scripts, asset names and strings; the XPAK index; bank name
  tables), what only the running game holds, and the sizes to expect. Two playbooks:
  `inspect-a-bo3-map.md` (containers first, bounded decompression and script recovery, the roster
  and feature inventory from the mod's own data, then at most one read-only capture of the user's
  running BO3 under a pinned, budgeted, hashed contract that sends nothing to the game) and
  `port-a-bo3-weapon.md` (native templates from the target map's own zone listings, per-kind
  conversion with readback equality, a loose registration script, a build that refuses on any
  unresolved reference, install and load evidence). Distilled from a port that reached a playable
  spawn on a stock map on its first load; `prior-art.md`, `other-titles.md`, `port-a-feature.md`,
  the `pat-port` and `pat-help` skills and the history page point at them.

### Fixed

- **Control plane: one run can be stopped without closing the plane.** `Plane.stop_run(run_id)`
  interrupts and kills that run's child, waits for its record and marks it `stopped`, while
  `shutdown` keeps meaning "stop everything and refuse what comes next". A stop that lands in the
  window between `start` returning and the worker spawning still takes effect, because the worker
  reads the request under the same lock it spawns under; and a stopped run is recorded as
  `stopped` whatever its exit code, since a child that handles the interrupt cleanly exits 0 and
  `finished` would read as if it had done the work. The MCP bridge uses it for a withdrawn
  request; the page's own shutdown path is unchanged.
- **Control plane: `module fetch` confirms.** It reaches the network and writes a snapshot of
  someone else's repository into the library, which is exactly the kind of step the page and the
  bridge gate behind the person's confirmation, and `docs/MCP.md` already said it was gated -- but
  the action was not marked `confirm`, so a harness could fetch without one. It is marked now, and
  the rule the action table is tested against covers every network effect rather than only the
  game, the agent host and the configuration.
- **Control plane: a stopped child's Job Object handle is closed once.** On Windows the thread
  running a child and the shutdown stopping it both terminated and closed the same Job Object
  handle. Windows recycles handle values, so the second close destroyed whatever kernel object had
  taken the value over in between: on the 3.13 runner that was a thread's semaphore, and the
  interpreter died with `_PySemaphore_Wakeup: ReleaseSemaphore failed` rather than the run ending.
  The handle now has one owner that terminates and closes it exactly once, and a handle that is
  created but never assigned to a child is closed instead of leaked. Found by the new MCP test that
  stops a child the moment it starts, which is the only path that reached for the handle twice.
- **The control plane's status colours barely showed on a light background.** Every badge was a
  tint at 13% alpha over whatever the browser happened to paint, so on a light scheme the
  difference between a result, a warning and a failure came out as three near-identical pale
  boxes, and the page relied on the user agent for its own background and text. The stylesheet
  now carries an explicit palette per colour scheme, every foreground and background pair at
  WCAG AA or better (body text 7:1 or above, badges and secondary text 4.5:1 or above), the page
  paints its own surfaces, and nothing that carries meaning is drawn with opacity or an alpha
  channel. `tests/test_plane.py` computes the ratios from the stylesheet, so a regression fails
  without a browser.
- **Control plane: the over-capacity 503 reaches the client on Windows.** Past the connection
  bound the server sent a 503 and closed the socket while the request bytes were still unread,
  which makes the kernel reset the connection; on Windows the client saw the connection aborted
  instead of the reply (the unit test for this bound failed intermittently on the Windows
  runners). The server now answers at once and hands the orderly close (stop sending, drain under a
  total deadline, close) to a short-lived thread, so neither the accept loop nor a worker waits on
  an over-capacity client.
- **`provides.rawfiles` is a declared kind.** `module declare` writes a `rawfiles` list into a seed
  manifest for every rawfile the package embeds, and `module plan` merges it into the module's
  provides, but `docs/MODULES.md` and the declaration validator did not know the kind, so a
  declaration that narrowed `provides` by copying its manifest block (the documented way) was
  refused with `provides maps kinds [...]`. `rawfiles` is now in the list, and the per-kind name
  limit is 4096 instead of 512, because a whole pack declared as one seed embeds several hundred
  models and weapons and a copied block was close to the old ceiling. Found while declaring ten
  pack-sized seeds with the route. Two rules tightened with it: for the kinds a manifest derives
  (weapons, localize, soundbanks, rawfiles, models, effects) a non-private seed's declaration may
  only narrow the manifest's list, and a name it does not list is refused even when the manifest
  lists none of that kind; and a provided rawfile is never a second, `rawfiles:` name collision
  beside the file collision the build resolves.

### Added

- **T6 facts as data, shipped in the package, with three lookups.** `src/plutonium_agent_toolkit/knowledge/`
  carries `builtins.json` (878 server and 297 client names with the argument counts, receiver and forms
  seen at native call sites across the shipped Zombies zones, 1,737 compiled scripts, plus the Plutonium
  client's and t6-gsc-utils' extensions from a reviewed seed), `engine-limits.json` (the limits page as
  rows, each naming the occupancy field that counts against it), `occupancy.json` (per map, what the
  zones the engine loads already carry against each limit; counts only) and `crash-signatures.json`
  (18 console-log regexes with class, cause and fix). New inert routes `pat knowledge builtin <name>
  [--vm server|client]`, `pat knowledge signature --log <file>|--text <line>` and `pat knowledge limits [--map <zm_map>]`; each takes an optional `--output <new dir>` that also records the answer with a receipt.
  A name with no witness answers `not-witnessed`, not `unknown`, and carries a `caution` saying that
  absence of a witness is not evidence of absence and naming the VM it is witnessed on, because a
  caller branches on the verdict and skips the note. The projectile-effect limit row says in the data
  that its per-map count is a foundation baseline a composition adds to, not spare capacity;
  `gsc.md`, `engine-limits.md`, `crashes.md`, the scripts preflight and the crash playbook point at
  them. The data is generated by the maintainer from bytes on disk and regenerated upstream, never
  edited here. Two benchmark tasks that need it: `bench-05` (a server script whose one call exists only
  on the client VM) and `bench-06` (classify a `Client Field Set actor is out of space` slice, then fix
  the script), both scored from the compile receipt and the compiled artifact through the new
  `artifact_contains`/`artifact_excludes` checks, because a compiler accepts both fixtures unchanged.
- **Control plane.** `pat plane serve --library <dir> --jobs <dir>` serves a page on 127.0.0.1 with a
  per-start token whose every control is one registered route with typed parameters: Library (declarations
  and compositions read from their files, declare a seed), Pack (`module plan|build`, `project verify`),
  Install (`game mods`, `game install-mod`, the Windows-only game routes shown and disabled elsewhere),
  Agent (`agent probe|hosts|models|dispatch|status|send|interrupt`, with the instance, model and reasoning
  choice always the person's), Registry (`registry list|search|show|add`, `module fetch`) and Runs (every
  action's argv, exit status and JSON, every receipt under the jobs directory). The server validates each
  parameter (files confined to the named roots and file names, ids by the routes' own patterns), adds
  `--output` for job routes, runs `pat` as a child process, one at a time, and records each run; it never
  builds argv, names an output directory, picks a model or reads the bearer. `pat plane actions` prints the
  table. New effect `serves-local`. Twenty-nine tests drive the server against the fake backends.
  `docs/CONTROL-PLANE.md`; glossary term control plane.
- **Skills installed where the harnesses look.** `pat dev install-skills [--plan] [--only …] [--home …]
  [--source …]` copies the seven skills under `skills/` into the user-level skills directory of every
  coding-agent harness whose home directory exists (Claude Code, Codex CLI, Gemini CLI, OpenCode,
  Cursor, Hermes Agent, and the shared `~/.agents/skills` location), each `SKILL.md` stamped with the
  checkout its relative paths refer to. It writes absent files and files it wrote before, refuses any
  other existing file, any link below the resolved home and any oversized file (`output_exists`,
  after writing the rest), launches no harness, and records every file with its hash under `<toolkit home>/skills/` plus a
  receipt per run; `doctor` reports per harness how many skills are current, stale, foreign or
  missing. `SETUP-PROMPT.md`, `docs/GETTING-STARTED.md` and `docs/FOR-AGENTS.md` carry the step; the
  Linux Tier 1 receipt exercises it against a scratch home (issue #22).
- **Built-in modules and packs, and where every registry comes from.** The toolkit ships its own
  registry (`plutonium-agent-toolkit-builtin`; `examples/registry.json` lists the same entries under an addable name) and lists it
  without `registry add`; `registry list`, `search` and `show` carry each registry's `origin`
  (`builtin` or `added`), `search --origin builtin` lists only the built-ins, and the built-in name is
  reserved. New route `pat dev builtin [--plan] [--only …]` fetches the built-in modules and packs at
  their pinned commits under `<toolkit home>/modules/builtin/<owner>/<repository>/<commit>/<path>`
  (one HTTPS snapshot per repository and commit, hashed, extracted with the archive safety checks,
  a pack laid out with the members and loads its recipe names) with a receipt per entry; a rerun
  re-hashes every file and directory and verifies, a tree with a changed, missing or added file is refused
  with `artifact_changed` and never overwritten, a pack records the member entries it laid out,
  `--plan` touches no network, and `doctor` reports which built-ins are present. Glossary term
  built-in. The Linux Tier 2 receipt fetches the three built-ins from GitHub and plans the built-in
  pack from the shelf, so the route is `available` on Linux. Built-in, fetched and installed are
  three different places; nothing here touches the game.

- **Registry baseline.** New route `registry baseline <directory> [--repository <url>]
  [--commit <40 hex>] --output <new dir>`: the deterministic, static check a registry runs on a
  snapshot before listing it and a submitter's agent runs offline first. It reads every eligible
  file under the directory and nothing else; `.git`, links and other skipped entries are recorded
  without reading their contents or targets: nothing in the tree is executed, no backend runs, no
  model and no network are used, and the same bytes always give the same `baseline.json`
  (`tree_sha256`, over every file's bytes and every directory's name, compares two scans). Policy
  version `1`, enforcement `selective`: exactly three
  finding ids block (`native-plugin`: PE, ELF or Mach-O headers under any name, or text naming
  Plutonium's plugins folder; `download-and-execute`: `iex (iwr ...)`, `Invoke-Expression`,
  `curl`/`wget ... | sh`, or a downloaded file started later in the same script; `path-escape`:
  a link anywhere in the tree, an absolute path or Windows drive, a `..` segment in a confined
  declared path, or a member or load resolving outside the scanned directory; a pack is scanned
  from the directory that holds it and every member it names). Every declared path is read one
  component at a time without following anything, so a path under a link is reported and never
  read through, and a component the filesystem refuses to describe is `unreadable` rather than
  an answer; the report is written either way.
  Non-blocking findings `unpinned-acquisition` (a `.zip`, `.tar.gz`/`.tgz`, `.tar.xz`/`.txz`,
  `.tar.bz2`/`.tbz2`, `.7z`, `.rar`, `.ff`, `.ipak`, `.exe` or `.msi` URL without a SHA-256 nearby) and `declaration-mismatch` (repository or commit different from the listing,
  a declared path missing, `bases`/`maps` empty, invalid JSON); capabilities `installer`,
  `bundled-package`, `lua-ui`, `file-io`, `client-dvar`, `function-replacement`, `command-hook`,
  `global-tooling`, `bundled-assets` (binary total above 8 MiB) and `large-text`; warning
  `no-resource-contract`. Outcomes `passed`, `review-required`, `needs-fixes` and `incomplete`
  (an unreadable file fails closed); every skipped or unreadable entry is listed. Bounds: 20 000
  files, 2 GiB, 4 MiB of text per file, 20 rows per file and rule (matches past that are counted,
  never kept, and a match is located only while its rule can still report one, with the line it
  sits on searched at most one block each way); each declaration is checked as the walk reads it,
  so only the summary the report carries is held, and that summary is bounded too (a value longer
  than 512 characters, or a list or object of more than 256 entries, is a marker; a composition's
  members are listed to that bound beside the number declared); the job's
  deadline is checked while the scan reads and
  again while the receipt re-hashes the recorded tree, so a scan cannot succeed late. The report and the result carry
  `not_a_security_audit: true` with the sentence that a baseline is a static check of files, not
  a security audit, certification, warranty or endorsement. `docs/REGISTRY.md` has the rule
  table; `publish-a-module.md` runs the baseline before listing; glossary term baseline. Tier 1
  of `tools/qualify.py` runs the baseline on `examples/hello-zm` and checks the outcome is
  `passed`; the regenerated Arch Linux (Omarchy 4.0.3) Tier 1 receipt carries both steps (22
  steps; the previous receipts are kept as superseded files), so the route is `available` on
  Linux. No Windows receipt yet; expected to pass there. Not measured: real community
  repositories. On POSIX every directory and file is opened relative to its parent's descriptor
  without following links and without blocking, and the descriptor must be what the listing saw;
  Windows re-checks every path component for reparse points before each open. Bytes count
  against the tree bound as they are read and directory entries of every kind against the file
  bound as they are listed, the directory given must not be a link, every file read and every
  directory listing (names and kinds) is an input of the job, re-hashed and re-listed at the
  receipt through no-follow descriptors whose identity must match the walk on POSIX, each file
  opened relative to its recorded ancestors so no swapped ancestor can redirect the re-hash
  outside the tree (a change,
  an addition, an entry swapped for a link of the same name or a directory replaced by a link
  to a look-alike after the scan is `input_changed`), the deadline is
  checked between chunks of every read, and file names that are not UTF-8 are hashed as bytes
  and shown escaped. The file bound is the job's own cap on recorded inputs (20 000), and a
  declaration nested past the parser or past 64 levels is a `declaration-mismatch`, never
  `operation_failed`; so is a declaration that is not UTF-8 or carries `1e9999` or `NaN`. A link
  named `.git` blocks like any link; the root is opened without following links after its
  by-name check. Verified by 70 unit tests on synthetic trees on Linux; CI runs them on
  Windows.
- **Registries and fetch by name.** `docs/REGISTRY.md` specifies `registry.json`: a file anyone can
  host that lists module and composition repositories at exact commits and holds no bytes; entries
  are `<github-owner>/<id>` and ownership is the repository living under that owner. New routes
  `registry add` (a local file or an https URL, validated and copied under the toolkit home),
  `registry list`, `registry search` (words, category, kind, tag, base, map, entry kind; offline)
  and `registry show`; and `module fetch <owner/id@commit>` (or `https://github.com/<owner>/<repo>@commit`
  with `--path`), which downloads the exact-commit tarball over HTTPS without git or a token, hashes it,
  extracts it with the archive safety checks, confirms the declaration is at the entry's path and names
  the same repository and commit, and writes a receipt; the result is named as a reference member of a
  composition. `examples/registry.json` lists the bundled examples. A `private` module may commit its
  seed manifest without the package; plans name the missing file. Glossary terms registry, entry,
  reference and catalog; playbook `publish-a-module.md`; a new `downloads-source` effect. No catalog,
  official registry repository, submission workflow or baseline scanner yet (issue #23).
- **Agent hosts: T3 Code as a thread dispatcher.** New route group `agent` (`probe`, `hosts`,
  `models`, `dispatch`, `status`, `send`, `interrupt`) drives a running T3 Code server on
  orchestration protocol 1 (the nightly and stable releases) over its authenticated HTTP API:
  `dispatch` creates a thread in a project and starts its first turn with the prompt, provider
  instance, model slug and option choices the caller names (no default model; `models` lists what
  the machine's T3 Code offers, with each model's reasoning choices), `status` reads the turn and
  session state with recent messages, `send` adds a turn (refusing with `busy` while one runs
  unless `--queue`), `interrupt` stops one. The bearer token is issued by the user's own `t3 auth
  session issue` and stored under the new `t3_bearer_token` configuration key, redacted by
  `doctor`. An Orchestrator V2 host (protocol 2) is reported by `probe` and refused by every other
  route with `not_implemented`. `docs/AGENT-HOSTS.md`; glossary terms agent host and dispatch;
  fourteen tests against an in-process fake server. `tools/qualify.py --tier agent` drives the
  user's running T3 Code with their configured token and choices, creates one proof thread and
  writes `<platform>-tier4-agent.json` with every UUID, path and listing row redacted; the Linux
  receipt against a real `0.0.41-nightly` server makes the group `available` on Linux.
- **Seeds, base packs and collisions as decisions.** A module's payload may now be a **seed**: an
  already-linked `mod.ff` with its soundbanks and a hashed `seed.json` manifest (embedded,
  referenced and root assets, provides, localized strings). New route `module declare <mod.ff>`
  writes the manifest and a draft declaration from any T6 mod package with OpenAssetTools, so a
  community pack becomes composable without its author doing anything. `module build` links a
  pack against every seed and load, names every seed root in the zone, merges the seeds' strings
  into the pack's string table, copies the soundbanks beside the package and checks every root is
  in the result. Compositions gain members that are other compositions (flattened; same base and
  map; bounded nesting), one member with `role: base` (the pack everything else attaches to,
  staged first), pinned references (`name` plus `commit` beside the fetched `path`), `loads`
  that may live beside the pack, `zone_header` lines for bases that need linker metadata, a
  `title` and `tags`. Collisions are no longer refusals: `module plan` lists every shared file,
  provided name or seed asset under `undecided` with the modules and the way to record an owner,
  identical bytes dedupe with no decision, and `module build` refuses while any remains; the
  composition's `decisions` list is part of the plan. Declarations gain `kind` (a fixed list per
  category), `tags`, `provides` and `distribution` (`source`, `seed`, `private`). `docs/MODULES.md`
  is rewritten; `docs/playbooks/attach-to-a-pack.md` is new; glossary terms seed, base pack and
  decision. The Linux Tier 2 receipt now declares the hello-zm package as a seed and composes it
  as a base member with the second example, so `module declare` is `available` on Linux.
- **Modules and compositions.** `docs/MODULES.md` specifies two files: a `module.json`
  declaration beside a mod's `project.json` (id, version, the bases and maps it was built for,
  dependencies, conflicts, resource contract, menu route, source repository and commit) and a
  `composition.json` naming a base, one map, module directories and an optional resource
  budget. New routes `module plan` (resolves dependency order, refuses missing dependencies,
  declared conflicts, cycles, a module not declared for the base or map, two modules producing
  the same file and an exceeded budget; hashes every declaration, recipe and input; runs no
  backend) and `module build` (compiles every module's scripts, stages assets, links one `mod.ff`
  as zone `mod`, reads it back and byte-compares every rawfile, as `project build` does).
  `examples/hello-pack` composes the two example mods; both gain a declaration. Playbook
  `docs/playbooks/compose-a-pack.md`; glossary terms declaration and composition recipe; the
  build skill and router point at it. `tools/qualify.py` Tier 2 plans and builds the pack and
  inspects the result; the regenerated Arch Linux (Omarchy) receipt carries those steps, so both
  routes are `available` on Linux (no Windows receipt yet). Not in this version: a module registry
  or download, version constraints, and detection of conflicts only the engine shows.
- **Prior art before building from nothing.** `docs/playbooks/find-prior-art.md`: when the user
  names a feature and no donor is on disk, search in tiers (the T6 community, ports to other
  engines, the origin title's own tools), acquire only public bytes with hashes, inspect before
  trusting, decline hateful or unlicensed content, seal the donor, then port.
  `docs/knowledge/prior-art.md` records where ports usually live by origin and container.
  `CONTEXT.md` gains **Prior art** and **Lead**; `pat-help`, `pat-grill` and `pat-port` route to
  the playbook; `AGENTS.md`, `docs/FOR-AGENTS.md` and `docs/history/README.md` carry the
  behaviour and the case it came from. Docs only; no route, receipt or evidence level changed.
- **Track record.** `docs/TRACK-RECORD.md`, generated by `tools/track_record_doc.py` from
  `docs/track-record.json`, an export of the authoring workspace's module registry and reviewed
  acceptance records: accepted modules by category, eight representative milestones with the scope
  of each verdict, and the workflows completed without a packaged route (live BO3 donor capture,
  a Linux IPAK adapter, Husky/C2M map capture). `README.md` leads with it. `docs/SUPPORT.md` is
  retitled "Packaged route qualification", states that it is not a ceiling, and its former
  out-of-scope list now names the agent path for each item. `docs/history/README.md` gains the
  practices that worked beside the failures. Two new glossary terms: packaged route, track record.
  `tests/test_track_record.py` keeps page, data and framing consistent. No route, evidence level
  or receipt changed.
- **`docs/playbooks/qualify-on-this-host.md`** and a "Receipts are per host; the routes are not"
  section in `docs/SUPPORT.md`: a route with no receipt for the agent's OS is unmeasured, not
  unsupported. The playbook runs `tools/qualify.py`, keeps the redaction gate, and ends in a pull
  request that extends the matrix. `AGENTS.md`, `docs/FOR-AGENTS.md` and the skills route to it;
  every "not run natively" row in the matrix now names that next action, and a test keeps it so.
- `tools/qualify.py` covers more routes: Tier 1 runs `project init` and plans the result; Tier 2
  decompiles the script it compiled; `--media` generates a two-bone rigged, skinned, animated
  `.blend` with the installed Blender and runs `model rename-bones`, `retime` (the 1..10 frame range
  verified to become 2..20), `transform` and `preview` on it. It refuses hosted CI runners (`CI`,
  `GITHUB_ACTIONS` and similar) like Wine and WSL. The Linux receipts are regenerated (15 and 23
  steps) and `gsc decompile`, `project init` and the four remaining `model` actions move to
  `available` on Linux; their Windows run is the playbook's job.

- **Linux backend pins.** `dev setup` now downloads and verifies gsc-tool 1.4.10, OpenAssetTools
  0.33.0, FFmpeg 9.0 (BtbN gpl linux64) and Blender 5.2.1 on Linux x64, from the same upstream
  releases as the Windows pins, under `downloads.linux` in `backends.json`. Hashes were computed
  from the downloaded archives on 2026-09-10; Blender's matches the `blender-5.2.1.sha256` file
  on three official mirrors. CoDLuaDecompiler, Greyhound, Husky and C2M stay Windows-only.
- **Tar extraction with the zip safety checks.** `.tar.gz`, `.tgz` and `.tar.xz` archives go
  through the same plan as zips: entry and size bounds, no absolute paths, no `..`, no reserved
  Windows names, no case collisions, single root under `strip_root`, declared sizes enforced
  while copying, file modes preserved on POSIX. Links are refused unless a pin says
  `"links": "copy"`, which writes in-archive relative symlinks as copies of their target (needed
  for Blender's `lib/` on Linux; about 490 MiB extra). Binaries that upstream ships as 0644
  (gsc-tool, OpenAssetTools) are marked executable by setup, recorded in the install receipt.
  Download-cache files keep their real suffix.
- **`tools/qualify.py`** runs the offline and backend tiers on Windows or Linux and writes
  `<platform>-tier<N>-*.json`. The receipt names the OS (`os`, `platform_token`, `native_linux`,
  `compatibility_layer` detects Wine and WSL) and redacts `/home/<name>` for any account.
  `--media` extends Tier 2 with FFmpeg, Blender and Cast and runs `audio inspect|convert` and
  `model inspect|convert` on synthetic inputs. `tools/qualify_windows.py` is a shim over it.
- `tests/test_docs_consistency.py` fails on any "any OS" or macOS claim that is not qualified as
  untested, and checks that `docs/SUPPORT.md` names both verified hosts and links only receipts
  that exist.

- **Native Arch Linux (Omarchy) receipts**: `docs/receipts/0.1.0b1/linux-tier1-offline.json` and
  `linux-tier2-backends.json`, produced by `tools/qualify.py` on Omarchy 4.0.2 with Python 3.14.7.
  Tier 2 downloaded and verified the four Linux pins plus Cast, built `examples/hello-zm` with the
  real gsc-tool and OpenAssetTools (the `mod.ff` SHA-256 equals the Windows receipt's), and ran
  `audio inspect|convert` on a generated tone and `model inspect|convert` on an OBJ cube through
  real FFmpeg and Blender. `audio inspect`, `audio convert`, `model inspect` and `model convert`
  move to `available`; their Windows native run is still owed.

- **`docs/BACKENDS.md`**, generated by `tools/backends_doc.py` from the pins and a new
  `dev/backend_usage.py` table: for every backend, the upstream project, version, license, pinned
  platforms, binaries and their `PAT_BACKEND_` names, and the exact command line each route runs
  it with and what the toolkit checks afterwards. Manual GUIs and the Cast add-on are listed
  separately. Tests fail if the page is stale or the usage table names a binary the code does not
  resolve. Names and links only; logos are a later per-project follow-up.

- **`CONTEXT.md`** at the repository root: the project vocabulary, one definition per term with
  the synonyms to avoid, covering both evidence ladders (route status and route evidence level),
  the build facts (offline verified, installed, launched, loaded, playable, captured, accepted),
  receipts, readback, foundations, preflight and red loop.
- **`docs/knowledge/`**: eight short pages of T6 and Plutonium facts for agents (client storage
  and console, fastfiles and zones, GSC/CSC and their traps, the engine contracts a Zombies
  feature must meet, foundations, crash classes with the signature table of failures seen after
  clean readbacks, engine limits observed, other titles), each under 150 lines, facts only, no
  private material.
- **`docs/playbooks/`**: nine finite recipes with the same five sections (preconditions, steps
  with the proving receipt field, do-not list, stop conditions, report): first build, add a
  script, port a feature, diagnose a crash, package and install, and four preflight gate lists
  (scripts, weapon rig, HUD text, audio memory), each gate a failure that reached a player after
  a clean conversion and a passing suite. Tests enforce the sections, that every `pat` route
  named is registered, and that the indexes match the files.
- **Skills**: `skills/` grows from one skill to seven. `pat-help` is a user-invoked router;
  `pat-grill`, `pat-build`, `pat-port`, `pat-diagnose` and `pat-review` are model-invoked with
  trigger descriptions; the umbrella skill points at the layers. Three adapt Matt Pocock's
  `grilling`, `diagnosing-bugs` and `code-review` (MIT); the unmodified upstream files are
  vendored under `vendor/matt-pocock/` at a pinned commit with a SHA-256 manifest and credited in
  `NOTICE`. `tests/test_agent_knowledge.py` checks the glossary shape, skill frontmatter and
  provenance, and that vendored bytes match their recorded hashes.
- **"Work efficiently"** section in `AGENTS.md` and matching guidance in the skill and
  `docs/FOR-AGENTS.md`: manifest once per session, a succeeded receipt is the fact, rebuild only
  on a changed input hash, never replay `delivery_uncertain`, read the playbook first, state
  unverified facts instead of inventing checks.

- **Offline benchmark** (`docs/BENCHMARK.md`, `tools/benchmark.py`, `tools/benchmark/`): four
  repeatable tasks (compile a broken script, build hello-zm, extract rawfiles, port a feature)
  scored only from receipts and the files they inventory: required routes in order, final status
  and error code, outputs present, readback contents, invocation count against a budget, wall
  time. `examples/hello-zm-two` (a round announcer) is the port task's source. A baseline row from
  the authoring agent on Linux is recorded; the benchmark gates nothing.

### Changed

- The composition examples in `docs/MODULES.md` and `docs/playbooks/attach-to-a-pack.md` name a neutral `my_base_pack` base member instead of a private pack's repository name.

- **Receipts are per host; the routes are not.** `docs/SUPPORT.md` no longer tags rows
  "Unverified on Windows" or "Linux only". A row states which host its receipt came from, and the
  section above the table states the expectation and its asymmetry: one code path on both OSes,
  upstream programs built for Windows first, so Linux is the harder host and a Linux receipt is
  strong evidence for Windows. An agent on a host with no receipt runs the route, fixes the
  adapter on the spot if the real program differs, and records the receipt with the playbook when
  it is worth having. `AGENTS.md`, `docs/FOR-AGENTS.md`, both skills and the playbook say the
  same; a test bans the old tags.

### Fixed

- `ff link` and `project build` now fail when OpenAssetTools Linker prints an `ERROR` line and
  exits zero, as the Unlinker readback already did; the fake Linker reproduces the case.

### Changed

- **Platform claims corrected.** The development tools are supported on Windows and Linux; the
  verified hosts are Windows 11 x64 and Arch Linux (Omarchy). macOS is untested, has no pinned
  backends and is not claimed: `doctor` and `dev setup` say so in a `note` on darwin, the PyPI
  classifier is removed, and every user-facing document is reworded. 0.1.0b1's release notes and
  pull request #13 said "any OS" and "Windows, Linux and macOS"; that was never backed by a pin or
  a receipt.
- `pat version`, `manifest` and `doctor` now report `platform.dev_tools_supported` (Windows and
  Linux, not under Wine) separately from `platform.game_control_supported` (native Windows);
  `supported` keeps meaning game control, which is what discovery's `available_here` used it for.
- `tools/qualify.py` uses a fresh temporary toolkit home when `PAT_HOME` is unset, so the offline
  tier's `configure` step cannot write a fake storage path into the user's real `config.json`;
  and a Tier 3 receipt is not `passed` until the four required human observations are `true`.
- `tools/private_scan.py` no longer matches the distribution name of the authoring machine, only
  its compositor: a native Linux receipt must name the OS it ran on, exactly as the Windows
  receipts name the Windows build. The scanner still blocks home and profile paths, private
  thread and run identifiers, tokens and keys; usernames and hostnames are removed from receipts
  by `tools/qualify.py`'s redactor, not by the scanner, and reviewers read every receipt before
  it is committed.

- **The development (file) tools now run on any OS, not Windows only.** `dev`, `gsc`, `ff`,
  `project`, `model`, `audio`, `image`, `lua` and `weapon` are no longer platform-gated: they
  drive the pinned upstream backends as ordinary subprocesses wherever the backend runs. Backend
  resolution is per-OS (the `.exe` suffix is dropped off Windows) and `doctor` now counts
  `PAT_BACKEND_<NAME>` overrides. `dev setup` runs on any platform: where a platform has no
  pinned download it reports the backend as `override-required` with how to supply it, instead
  of refusing with `unsupported_platform`. Game control and capture stay native-Windows-only
  (Win32 console transport). Verified by building `examples/hello-zm` natively on Linux with the
  real gsc-tool and OpenAssetTools: a `mod.ff` was linked and byte-compared on read-back. A
  committed native-Linux qualification receipt is a tracked follow-up.

## [0.1.0b1] - 2026-09-10

First public beta. Scope is the **development toolchain**, verified on a native Windows 11 host:
`dev setup`, `gsc compile`, `ff inspect|extract`, `project plan|build|verify`, and
discovery/`configure`/`doctor` are `available` with receipts under `docs/receipts/`. You can build
and package a T6 Zombies mod with the real tools. **Game control ships but is not qualified**: a
console-started match is dropped by the client right after it loads
([issue #8](https://github.com/SickoHours/plutonium-agent-toolkit/issues/8)), so no `game` route
has earned level `game`. Screen recording and the autonomous test runner are deferred. See
`docs/SUPPORT.md` for the exact per-route evidence.

### Changed

- `pyproject.toml` development-status classifier moved from Pre-Alpha to Beta for the 0.1.0b1
  release, so package indexes label it correctly.
- Documentation aligned around the agent-native, malleable-by-default premise: every doc is written
  for the agent that operates the toolkit, and states plainly that it is meant to be configured and
  edited to fit whatever machine and harness the user has. Rewrote `AGENTS.md`, made `CLAUDE.md` an
  intelligent Claude-Code pointer that imports it, added `docs/FOR-AGENTS.md` (how to adapt, debug
  and extend on the user's machine, plus modding behaviours: foundation-first modular building and
  mod organization), and refreshed `README.md`, `docs/GETTING-STARTED.md`, `SETUP-PROMPT.md` and the
  installable skill.
- `docs/SUPPORT.md` release bars split into a development-tools beta (met now) and a later
  game-control beta gated on issue #8; the first line tracks the current version.
- Added `tests/test_docs_consistency.py`: the credentials prohibition, the route-status
  vocabulary matching the code, and SUPPORT.md staying canonical for evidence levels are now
  enforced by tests, not review alone.


### Added

- Release automation: `tools/bump_version.py` (moves the version everywhere and promotes the
  `Unreleased` section), `tools/release_notes.py` (changelog section as release notes), and
  `.github/workflows/release.yml` (tag push verifies, tests on Windows, builds, publishes a
  GitHub Release with checksums; pre-release tags flagged automatically).
- Pilot acceptance journeys: `docs/PILOT-USER.md` and `docs/PILOT-CONTRIBUTOR.md`.
- Maintainer checklist for the Windows qualification pull request:
  `docs/contributors/REVIEWING-QUALIFICATION.md`.
- Windows qualification procedure: `WINDOWS-QUALIFY-PROMPT.md` for the agent on the Windows PC,
  `docs/WINDOWS-QUALIFICATION.md` (three tiers, human-authorized game tier),
  `tools/qualify_windows.py` producing redacted receipts under `docs/receipts/<version>/`.
- Windows-gated development routes implemented: `gsc compile|decompile`,
  `ff inspect|link|extract`, `project init|plan|build|verify`, `model
  inspect|convert|transform|rename-bones|retime|preview` (background Blender with the bundled
  worker and pinned Cast add-on), `audio inspect|convert`, `image convert`, `lua decompile`.
  Jobs run backends inside a Windows Job Object (process group elsewhere for tests), bound log
  and output size, and write `receipt.json` on every exit path.
- `weapon catalog|plan` implemented (any platform): sealed BO3 donor verification and recipe
  planning; `docs/WEAPONS.md`.
- `game` group implemented behind the Windows gate: `status`, `mods`, `info`, `launch`,
  `select-mod`, `reload-mod`, `load-map`, `fast-restart`, `map-restart`, `disconnect`,
  `check-load`, `quit`. Native Win32 console transport (attach, screen read, one bounded input
  write), marker-bracketed engine queries, verified map settings before `map`, DLC5 zone guard,
  ordered mod transactions, receipt-bound `check-load` with log error counts only, `quit`
  without force-kill. Launch goes through the fixed `plutonium://play/t6zm` URI and reports
  request, detection and focus preservation as separate facts. One bounded worker per command
  under a named mutex; uncertain outcomes are never replayed. `docs/GAME-CONTROL.md`.
- `game install-mod <mod.ff> <folder>`: file-only install into storage with hash verification;
  refuses to overwrite without `--replace`, which moves the old folder aside.
- `core/jobs.py` job runner, `PAT_BACKEND_<NAME>` override for tests and pre-installed tools,
  `implemented` and `deferred` route statuses alongside `planned` and `available`.
- Fake gsc-tool, Linker, Unlinker, ffmpeg/ffprobe, ImageConverter, CoDLuaDecompiler and Blender
  under `tests/fakes/` so every adapter is unit-tested offline, including compiler errors reported
  with exit zero, backend crashes, tampered outputs and recipe path escapes.
- C2Mv3 3.0.5 hash pinned (optional, never redistributed).

### Changed

- `capture` and `test` routes are `deferred` (product decision 2026-09-10): registered, refuse
  with `not_implemented`, and excluded from the beta and 1.0 bars in `docs/SUPPORT.md`.
- Repository made public on 2026-09-10 at 0.1.0a1 so the program can use branch rulesets,
  secret scanning and private vulnerability reporting. Readiness is unchanged: see docs/SUPPORT.md.
- CI uses actions/checkout v7, setup-python v7 and upload-artifact v7 (Node 24 runtime).

### Fixed

- Findings of the first native Windows run (Windows 11 25H2 build 26200, Python 3.12.0), Tier 1 of
  `docs/WINDOWS-QUALIFICATION.md`:
  - The documented `PAT_HOME` at `<repo>/.qualify-home` was not ignored by git, so `configure` put
    the user's absolute storage path where `tools/private_scan.py` lists untracked files and the
    Tier 1 private scan failed. `.gitignore` ignores it; `tests/test_release_tools.py` checks that
    the documented location stays ignored.
  - `src/plutonium_agent_toolkit.egg-info/` was tracked, so `pip install -e .` dirtied the tree and
    every receipt recorded `git_dirty: true`. Untracked and ignored, with a test that refuses
    tracked egg-info.
  - Windows job runner: a backend tree terminated through the Job Object (timeout, output bound,
    cancellation) kept its inherited handle to the step log for up to a scheduler tick after
    `process.wait()` returned, so deleting the job directory immediately failed with
    `ERROR_SHARING_VIOLATION` about one time in ten and made `test_finish_rechecks_output_bound`
    flaky. `_run_windows` now waits, bounded, for the log to be released after closing its own
    handle and records `log_still_open` on the step if it is not. `tests/test_jobs_windows.py`
    (native Windows only) covers the wait and the timeout path.
  - `tools/qualify_windows.py` overwrote an earlier receipt on rerun. It now moves the previous
    file to `<name>.superseded-<utc stamp>.json` and notes it, so a failed attempt survives the fix
    as `docs/contributors/RECORDING-A-RECEIPT.md` requires.
  - The tier commands said `--output docs/receipts/qualify`, contradicting `docs/receipts/README.md`
    and this changelog; they say `--output docs/receipts` now.

- Maintainer review of the Tier 1 and 2 receipts: the failed first-attempt receipt embedded
  `private_scan`'s own hit excerpt, a truncated `C:\Users\m`, which the redactor missed because it only
  knew the exact `USERPROFILE`; other accounts' and other drives' `Users` paths would also have
  survived. `tools/qualify_windows.py` now replaces any drive-letter `Users` path for any account,
  in either slash style, including account names that contain spaces, before the account-specific
  patterns; strips `excerpt` from embedded scan hits; and gains `--redact-existing <file>`, which
  reapplies the current rules to a committed receipt in place, is idempotent, notes the rewrite and runs on any platform. The affected receipt
  was re-redacted with it, not hand-edited. `redactor()` is unit-tested directly with the
  reviewer's five inputs plus the JSON-escaped form.
- Windows job runner: when the step log is still held after the bounded wait, the step records
  `log_release_wait_seconds` next to `log_still_open`.
- `tools/qualify_windows.py --tier game --begin`, exactly as `docs/WINDOWS-QUALIFICATION.md` writes it
  (no `--output`), was refused by argparse because `--output` was unconditionally required, so the
  Tier 3 marker could never be written as documented. `--output` is now required only when a
  receipt is written, and only for `--tier game`: `--tier offline --begin` or `--tier backends --begin`
  without `--output` is refused up front instead of running the whole tier and crashing at the end.
  Found on the first native Tier 3 attempt; regression tests added.
- `game check-load` capped the new console output it would inspect at 128 KiB and reported the log
  gate `checked: false` above that. A single native Town load emits far more (about 4000 lines:
  fastfile, ipak and per-weapon lines), so `check-load` could never verify a real `load-map`. The
  bound is now 4 MiB, matching a job's backend log; regression test with a map-load-sized log.
  Found on the first native Tier 3 attempt.

- `project build` linked the mod zone under the recipe name (`> name,hello_zm`), so the real Linker
  emitted `packages/hello_zm.ff`, and the qualification staging (and the old `install_hint`) renamed it
  to `mod.ff`. A T6 fastfile is bound to its file name: the zone name keys its compressed streams, so
  the renamed copy cannot be inflated (OpenAssetTools Unlinker: `inflate of stream 0 failed`, exit -1;
  a known-good `mod.ff` fails the same way when renamed) and the Plutonium r5346 client hung loading it
  (busy, no log output, no dialog). The zone is now always linked as `mod`, so the build emits a real
  `packages/mod.ff`; `tools/qualify_windows.py` stages it only under that name and fails the tier
  otherwise; the fake Linker names its output from `> name,` and the fake Unlinker refuses a renamed
  file, so the offline round-trip test now catches this (it previously passed for the wrong reason).
  Found on the first native Tier 3 attempt with `hello_zm`; Tier 2 re-run with the corrected build.

### Verified

- Native Windows Tier 1 (offline) receipt `docs/receipts/0.1.0a1/tier1-offline.json`: Windows 11
  25H2 build 26200, Python 3.12.0, clean tree. 13/13 steps: unit tests, `version`, `manifest`,
  `describe`, `doctor`, `configure`, `game mods` on an empty storage, `dev setup --plan`,
  `project plan` of `examples/hello-zm`, the `output_exists` refusal, the deferred-route refusal,
  private scan and release check. `version`, `manifest`, `describe`, `doctor` and `configure`
  move to level `native` in `docs/SUPPORT.md`. The failed first attempt is kept alongside as
  `tier1-offline.superseded-*.json`.

- Native Windows Tier 2 (backends) receipt `docs/receipts/0.1.0a1/tier2-backends.json`: same host,
  clean tree, 10/10 steps on the first attempt, then re-run at 11/11 after the mod-zone naming fix
  (the build now emits `packages/mod.ff`, staged for Tier 3 without renaming; the earlier receipt is
  kept as superseded). gsc-tool 1.4.10 and OpenAssetTools 0.33.0
  downloaded, SHA-256 verified and re-verified on rerun; `examples/hello-zm` compiled, linked,
  read back, byte-compared and verified with `--inputs` (`mod.ff` 384 bytes, SHA-256 in the
  receipt); `ff inspect` and `ff extract` on the result; a broken script fails with
  `backend_failed`; a minimal script compiles. `gsc compile`, `ff inspect`, `ff extract` and
  `project plan|build|verify` become `available` and move to level `native`; `dev setup` moves to
  `native` for `gsc` and `oat`.

- Native Windows Tier 3 (running game) attempted, receipt `docs/receipts/0.1.0a1/tier3-game.json`
  (3/5 collector checks): `game launch` started T6 Zombies through the `plutonium://play/t6zm`
  handler with no launcher prompt (`focus_preserved` false, ~5 s); `game status` and `game info`
  attached to the live external console and returned correct window and dvar state. `load-map town`
  set the dvars and sent `map` but did not start a survival match, so `check-load` could not verify.
  `select-mod zm_gobblegums`, `select-mod base` (verified `fs_game` changes) and `quit` (stopped through
  the engine) ran natively. No `game` route earned level `game`; all stay `offline`.

### Not verified

- No `game` route qualifies at level `game`. `load-map` starts the match but the client then drops it.
  Console-log diff on this install: every toolkit-started load reaches `Initializing game`, loads the
  Town gump, and ends within seconds with `SV_Shutdown: hostquit` and `Dropping client num 0:
  EXE_DISCONNECTED`, returning to the menu; the two menu-started matches play to completion and end
  with `EXE_MATCHENDED`. The gametype settings configs (`zm/gamesettings_*.cfg`) exec at frontend init
  in both paths, and the `Could not load weapon` and `ipak file not found: common_zm` lines appear
  identically in the playable session, so neither the config nor the base assets is the cause (the
  `zm_transit` zone set is complete and unchanged since 2025-10). The console `map` path connects
  the local client through the mod-download check (`Searching for files required to download mod`),
  which the menu's party-lobby path does not. Root cause remains open in issue #8; no command
  allowlist change was made. `reload-mod`, restarts, `disconnect` and `install-mod` in game were not
  exercised. Issue #9 tracks the opt-in focus restore after launch.
- `gsc decompile`, `project init` and the standalone `ff link` route did not run natively and stay
  `implemented`. The seven other pinned backends were not downloaded.

## [0.1.0a1] - 2026-09-09

First private foundation commit. Nothing in this version has run on a native Windows host.

### Added

- `pat` command with `version`, `manifest`, `describe`, `doctor`, `configure`, `dev backends` and
  `dev setup`. One JSON document per invocation; exit statuses 0/1/2/130; stable `error_code` values.
- Core contracts: `Failure` with stable codes, result envelope with `schema_version` and
  `request_id`, per-user configuration under `PAT_HOME` or `%LOCALAPPDATA%\PlutoniumAgentToolkit`,
  receipts with input/output hashes, platform gate that refuses backend and game operations off
  Windows and detects Wine.
- Pinned backend catalogue with licenses: OpenAssetTools 0.33.0, gsc-tool 1.4.10, CoDLuaDecompiler
  2.4.2, FFmpeg 9.0 (BtbN build), Blender 5.2.1, Cast 2.00, Greyhound 1.46.3.2, Husky 0.8.0.0.
  C2Mv3 listed as optional and unpinned. Setup verifies SHA-256, extracts with path-safety checks,
  refuses to overwrite a changed tree and runs no vendor installer.
- Route contracts for every planned capability across `gsc`, `ff`, `project`, `model`, `audio`,
  `image`, `lua`, `weapon`, `game`, `capture` and `test`. Planned routes answer `not_implemented`
  and execute nothing.
- Contributor foundation: `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `SECURITY.md`,
  `CODE_OF_CONDUCT.md`, `NOTICE`, `PROVENANCE.md`, issue and pull request templates, CODEOWNERS.
- `tools/private_scan.py` blocks personal paths, private identifiers, tokens and old internal
  command names. `tools/release_check.py` verifies that the package version, `pyproject.toml`,
  the top changelog entry, `docs/SUPPORT.md` and the tag agree.
- GitHub Actions workflow running the unit tests, both tools and a packaging build on
  `windows-latest`.
- `docs/SUPPORT.md` qualification matrix, `docs/GETTING-STARTED.md`, contributor guides and the
  first engineering-history note.
- `examples/hello-zm`: the first-run mod used by the qualification loop.
- Installable agent skill and `SETUP-PROMPT.md`.

### Verified

- Unit tests, private scan and release check pass on the Linux authoring host.

### Not verified

- Anything on native Windows. Backend downloads, game control and capture have no receipts yet.
