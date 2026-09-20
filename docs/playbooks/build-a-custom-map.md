# Build a custom map from a T6 map template

Build one of JezuzLizard's `t6-map-templates` maps (`zm_karma`, `zm_frontend`) into the seven
files a Plutonium mod folder needs, with the pinned OpenAssetTools, on Linux or Windows. Black Ops
II has no map compiler; a template takes a stock level Zombies never used, re-links its world by
reference, and puts Zombies on top. What you author is the entity text, the pathnodes, the map
scripts and the zone definitions; the rooms cannot change. The template's own `compile.py` is
Windows-only and its documentation is one line; this is the written form, measured on `zm_karma`
(release 2026-07-28) with OpenAssetTools 0.33.0 on Linux.

## Preconditions

- `pat doctor --json` shows the `oat` backend `present: true` (`first-build.md`).
- A checkout of `https://github.com/JezuzLizard/t6-map-templates` (no license file; ask before
  redistributing anything but your own build). `zm_templates/<map>/compile.py` names the map
  (`MAP_NAME`), the mod (`MOD_NAME`), the stock zones it loads (`REQUIRED_FILES`) and the files
  that go into `mod.iwd` (`create_mod_iwd`). Read it first; every number below comes from it.
- Every zone `REQUIRED_FILES` names, from your own game install's `zone/all/`. For `zm_karma`
  that is eleven: `karma`, `code_post_gfx`, `common`, `common_zm`, `zm_transit`,
  `zm_transit_patch`, `so_zsurvival_zm_transit`, `zm_buried`, `zm_buried_patch`,
  `so_zencounter_zm_buried`, `zm_tomb`. The `sound/` directory beside `zone/` (the `.sabs` and
  `.sabl` archives) for the soundbank audio.
- Plutonium r5140 or newer on the machine that will load it; older clients do not read the
  entity file from `mod.iwd`.
- Scratch directories outside the repository for outputs.

## Steps

1. Dump the soundbank audio the template's alias table names. The template's
   `mod/soundbank/<mod>.all.aliases.csv` lists every `FileSource`; none of those files exist on
   disk until a stock bank is dumped. Dump each required zone with the common zones loaded first:
   ```sh
   pat ff extract <zone_dir>/zm_buried.ff --types soundbank --game t6 \
     --load <zone_dir>/code_post_gfx.ff --load <zone_dir>/common_zm.ff --load <zone_dir>/zm_transit.ff \
     --output ../jobs/snd-zm_buried-001 --json
   ```
   Proof: the Unlinker log in the job has zero `WARN: Could not find data for sound` lines. A
   dump without the `--load` rows exits 0 and leaves most entries unresolved
   (`docs/knowledge/fastfiles-and-zones.md`, "Sound banks"). Merge every dump's `sound/` tree
   into one directory; two dumps naming one file carry identical bytes. Then check coverage:
   every `FileSource` in the alias table, with its leading `raw\` removed, must exist in the
   merged tree or under the template's `common/`. On `zm_karma` two did not, because their zones
   are not in `REQUIRED_FILES`: one multiplayer music loop (`code_post_gfx_mp.ff`) and the
   Sliquifier set (`zm_highrise.ff`). Dump the zone that owns a missing file; a search path does
   not find it.
2. Link the world zone: the stock level re-linked by reference with the template's scripts.
   ```sh
   pat ff link zm_templates/zm_karma --zone karma --load <zone_dir>/karma.ff \
     --assets zm_templates/zm_karma/karma --assets zm_templates/common --output ../jobs/karma-world-001 --json
   ```
   Proof: `ok: true`, `Finished with 0 warnings, 0 errors`, one `karma.ff` of about 51 MB in
   under 15 s. The zone source is `zm_templates/zm_karma/zone_source/karma.zone` plus
   `common/zone_source/`; pass both as source search paths if your `ff link` build needs them
   named (the standalone route's arguments are listed by `pat describe ff link --json`).
3. Link the tiny English zone the same way (`--zone en_karma`, no loads; one placeholder
   rawfile, 128 bytes).
4. Link the Zombies layer: `mod.ff` with the soundbank, against every other required zone.
   ```sh
   pat ff link zm_templates/zm_karma --zone mod --assets zm_templates/zm_karma/mod \
     --assets ../jobs/sound-merged --assets zm_templates/common \
     --load <zone_dir>/code_post_gfx.ff --load <zone_dir>/common.ff ... --load <zone_dir>/zm_tomb.ff \
     --output ../jobs/karma-mod-001 --json
   ```
   Proof: `0 errors`; `mod.ff` (about 26 MB), `<mod>.all.sabl` and `<mod>.all.sabs` written.
   Expected warnings on `zm_karma`: 25 `framerate should be 48000` on the template's bundled T5
   Thundergun and voice sounds, 2 `DEPRECATED: XModel … version 1` on its Thundergun models.
   Anything else is yours.
5. Pack `mod.iwd`: a zip (deflate) of every `create_mod_iwd` row, at its `inner_dir` path. The
   entity text (`<map>.d3dbsp`), the pathnodes (`.d3dbsp.paths`), the overridden stock scripts,
   the loose images, effects and animations. A row whose file is absent in the checkout is a
   template gap, not yours (`zm_karma` lacks `mod/weapons/ballista_zm`; the author's release lacks
   it too). Write text entries with CRLF if you want the archive to match the author's release
   entry by entry; the repository normalizes to LF on checkout.
6. Assemble the folder: the three fastfiles, the two sound archives, `mod.iwd`, and the
   template's `mod/mod.json`. Compare with the author's release if one exists: same asset names in
   each fastfile (`pat ff inspect`), `mod.iwd` entries identical, the `.sabs` identical. Fastfile
   bytes differ across linker versions; names are the check.
7. Install as `stock_<map>_usermap_test` (`package-and-install.md`); the map name to load is
   `MAP_NAME` (`karma`), and the template ships a `<mod>.cfg` that sets the game type and loads it.

## Do not

- Copy sound files from a Windows Sound Studio dump if you have the archives; the dump above is
  the same bytes and leaves a receipt.
- Skip the `--load` rows on a soundbank dump because it exited 0; read the warning count.
- Edit a `.d3dbsp` from this template as if it were binary; it is entity text, and the binary
  neighbour is `.paths`.
- Ship the stock level's fastfile or any dumped game asset; the template carries only what it
  authored, and so should your build.
- Treat a link as a load: pool counts, the image-header rule for base-owned names and Plutonium's
  reading of `mod.iwd` are only proven when the map loads.

## Stop conditions

- A required zone is missing: stop; the world link cannot proceed without the level's own zone
  and the Zombies link without the common ones.
- The soundbank dump leaves unresolved entries after the common zones are loaded: find the
  owning zone (step 1) before linking; the Linker refuses the bank on the first missing file
  (`Unable to find a compatible file for sound …`).
- A link reports `ERROR:` with exit 0: a failure (`docs/knowledge/fastfiles-and-zones.md`).
- Step 6 passes: **built**. Loading is a separate, authorized step.

## Report

The template and its commit, the linker version, the three link jobs with warning and error
counts, the `mod.iwd` entry count and any missing rows, the sha256 of every file in the folder,
and, if compared, what matched the author's release and what did not. State "offline verified;
not installed" unless an install receipt exists.
