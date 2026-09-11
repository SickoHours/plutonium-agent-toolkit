# Inspect a BO3 Workshop map, offline first and then one read-only capture

Learn what a Black Ops III Workshop map contains and how its features work before deciding what
to port, from the mod's own compiled data rather than from videos. Then, when a structured asset
is needed (a weapon definition, a rig, animation curves), read the loaded game once under a
contract that cannot change it. Formats: `docs/knowledge/bo3-workshop-formats.md`. Words:
`CONTEXT.md` (lead, donor, sealed donor). What comes after: `port-a-bo3-weapon.md`.

## Preconditions

- The Workshop item is on disk under the user's own Steam library, acquired by their own
  subscription. Nothing here downloads, logs in or bypasses anything (`find-prior-art.md`
  step 5 governs acquisition).
- Linux host with Python 3.11+, the community script decompiler the toolkit pins as its `gsc`
  backend (`pat dev setup --only gsc --json` installs it; `pat doctor --json` prints its path),
  and a scratch directory outside any source tree for everything recovered. `pat gsc decompile`
  itself is a T6 route and does not take a game flag, so step 3 runs the pinned binary directly
  with the T7 flags and records the exact command; a `pat gsc` T7 mode is not a route today.
- For the capture step only: the user runs BO3 under Proton themselves, has the map loaded to
  the point where the asset is in use, and has said this specific read may happen. No launch,
  no map change and no input is sent by the agent; the game is the user's. The host's ptrace
  attach check must already allow a same-user read of `/proc/<pid>/mem` (Yama `ptrace_scope` 0
  or 1); if it does not, the capture is unavailable on this host and that is reported, never
  worked around by changing the scope or the process.
- The private nature of the result is understood: everything recovered is study material on
  the user's machine, not a payload to publish.

## Steps

1. Identify the container versions before reading anything: the fastfile header magic, version
   word, compression algorithm and encryption flag; the sound-bank magic and version; the XPAK
   header version. Proof: a `containers.json` in the scratch directory naming each file, its
   size, SHA-256 and the header fields. An encryption flag set is a stop condition.
2. Decompress the fastfile with a bounded block reader that checks every block's offset,
   lengths and zlib end, and carve the compiled scripts by their serialized record pattern.
   Proof: a recovery manifest with the zone's size and hash, the block count, and one row per
   recovered script (name, kind, size, hash).
3. Decompile the recovered scripts by running the pinned `gsc` binary directly in T7 decompile
   mode (the same program `pat gsc` drives for T6: `<gsc-tool> -m decomp -g t7 -s pc <file>`),
   one file per invocation, into the scratch directory. Proof: the decompiled tree, the exact
   command line and the binary's SHA-256 recorded in the recovery manifest, plus the list of
   scripts that failed and their errors; a few failures on map-specific scripts are normal and
   are recorded, not hidden.
4. Read the roster from the zone and the language fastfile without decoding assets: weapon
   names, perk specialties, FX paths, rawfiles, localized strings, sound alias names. Proof:
   a `roster.json` with the counts and the lists.
5. Parse the XPAK index for every image and mesh name and, for images, format and dimensions.
   Proof: `xpak-index.json` and the two name lists; the origin prefixes on mesh names say which
   weapons were themselves ported and from where.
6. Read the sound banks' headers and name tables only. Proof: the entry counts per bank and
   the alias names; no audio is carved at this stage.
7. Write the feature inventory from steps 3 to 6: for each perk, power-up, enemy, weapon
   behaviour and system, what the script does (registration API used, numbers, triggers), which
   assets it names, and its T6 fit (a native T6 counterpart exists, a translation job, or art
   that needs a capture). Proof: the inventory document with a source line reference per claim.
8. Only if a port needs a structured asset, capture once from the running game, read-only:
   pin the process by PID and start ticks, probe the asset-pool table and string table and
   verify the layout by requiring the map pool to name exactly the loaded map, take the user's
   live lock if one exists, then read with byte and time budgets, saving every touched 4096 byte
   page with its hash, and re-check the map and the process identity after. Proof: a
   `bo3-page-capture-v1` manifest (`map_before`, `map_after`, `pid`, `start_ticks`,
   `captured_bytes`, `pages` with hashes, the records decoded) that `pat weapon catalog` can
   inventory later; the reader's own hash recorded in the manifest.
9. Seal what a port will consume: a hashed index over the recovered files and captured pages.
   Proof: the index file and its hash, the inputs a later prepare step refuses to run without.

## Do not

- Write to the Workshop directory, rename or copy the item elsewhere to "work on it"; read in
  place, write only into the scratch directory.
- Decode XPAK payloads or carve audio during inspection; the index and the name tables answer
  "what is here". Payload decoding is a port step with its own receipt.
- Attach a debugger, change ptrace scope, write to process memory, send input, or change the
  map to reach an asset. A read that needs any of those is not a read-only capture; report
  what would be needed and stop.
- Trust pool or string offsets from another executable build or another machine; probe and
  verify on this one, every time.
- Treat the map author's custom identifiers as unknowable: the readable strings, numbers and
  API calls around an `_id_` hash usually name the behaviour.
- Publish, list or commit anything recovered here. It is study material under the author's
  terms.

## Stop conditions

- The fastfile is encrypted, or its blocks fail the reader's checks: the offline route ends;
  report which check failed.
- The user has not said the capture may happen, the game is not the user's own process, or the
  map pool does not name the expected map: no capture.
- A byte or time budget is hit during capture: the manifest records the partial result as
  partial; do not raise the budget and rerun without saying why.
- The inventory (step 7) is written and no structured asset is needed yet: stop here, the port
  decision comes next with `pat-grill`.

## Report

Nothing here earns a build fact: **offline verified**, installed, launched, playable, captured
and accepted are each "no" until a later playbook says otherwise. State: the container versions and whether the offline route
applied; counts (scripts recovered and decompiled, weapons, perks, FX, images, meshes, sounds);
the feature inventory's location; whether a capture happened, its budgets, `map_before` and
`map_after`, and the manifest hash; the sealed index hash; and the terms under which all of it
stays private.
