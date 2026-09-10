# Fastfiles, zones, Linker and Unlinker

## What a fastfile is

A `.ff` is the compressed archive T6 loads. It is produced by a linker from a **zone file**: a
text list of the assets to pack. The toolkit uses OpenAssetTools (`Linker`, `Unlinker`) for both
directions; `docs/BACKENDS.md` has the exact command lines.

A zone file the toolkit writes looks like this:

```text
// Call Of Duty: Black Ops II
>game,T6

rawfile,scripts/zm/hello_zm.gsc
```

Header comment, a `>game` line, then one `type,name` row per asset. The name is the path the
engine will ask for. The zone's own name becomes the fastfile's name, and the engine binds the
two: `mod.ff` must have been linked as zone `mod`.

## What Linker needs

- `--base-folder <project>` with `zone_source/<zone>.zone` and the assets under `raw/` (or other
  search paths added with `--add-asset-search-path`).
- `-l <other.ff>` for each fastfile whose assets this zone references but does not contain.
  Scripts that reference assets from the map or the base need those loads to resolve.
- `--output-folder` where `<zone>.ff` lands.

The toolkit stages compiled scripts and declared assets into `raw/`, writes the zone, links, and
reads back. The readback is deliberate: it is the only way to know what the linker actually packed.

## The exit-zero trap

Linker and Unlinker can print `ERROR:` lines and still exit 0. A process returning zero does not
override an error diagnostic. The toolkit's adapters read the log and fail the job on a load
failure; when you run the tools by hand, read the log yourself. The same rule holds for
gsc-tool: an error line in its output is a failure whatever the exit status.

## Readback

`pat ff inspect <file.ff>` lists a fastfile's assets with `Unlinker --list`. `pat ff extract`
writes selected asset types out (`--types rawfile,image`, model and image formats selectable).
`pat project build` extracts every rawfile it packed and byte-compares it with the source, so a
green build means the script bytes in the package equal the compiled bytes on disk.

What readback proves: the asset is in the package under that name with those bytes. What it does
not prove: that the engine will accept it. Registration limits, pool sizes, animation-tree
references and field budgets are engine facts checked only at load (`zombies-contracts.md`).

## Reading a base or map fastfile

The same `ff inspect` and `ff extract` work on any T6 fastfile you have on disk, which is how to
learn what a map ships, which weapon definitions exist, or what a mod base already contains. Some
asset kinds extract to editable text (weapon and sound alias definitions), some to models or
images in the format you choose, and some only to a listing. Keep extracted game assets private;
the toolkit never commits them and neither should you.

## Sizes and pools

A fastfile's compressed size on disk, its uncompressed asset bytes, the engine's fixed asset
pools and the process's memory are four different numbers. A successful link proves none of the
last three. The most common load-time surprises are pool counts (weapon definitions, sound
aliases, effects, network fields) and the memory reserved by sound banks, not archive size.
