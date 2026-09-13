# Foundations: build on a clean base

## The rule

A new feature is built and first tested on an **unmodified base**, never on top of an existing
composition. Base plus the one module plus its declared core dependencies is the whole test
package. Acceptance recorded there is the feature's acceptance and is tied to that base.

Why: a one-feature test built by copying a big installed mod carries every retained weapon, perk
and script of that mod. The package is huge, a crash cannot be attributed, and the player's
verdict covers more than the feature. The symptom is visible in a storage folder where several
mods differ by one feature and each carries the full pack.

## Bases are frozen and first-class

1. **A base is frozen.** A base is a named, versioned foundation exactly as shipped or as
   sealed, never edited. An upstream mod's release (a DLC-style mod that needs its own mod
   folder loaded first) is an ordinary base, not a special build path.
2. **Every base is first-class.** The stock game, an upstream mod release, a quality-of-life
   variant and a community-standard base all follow the same rules: a person picks a base,
   packs compose onto it, the base never changes. Prefer the stock game as the first base
   for a port; it needs no extra files and its verdict covers the most players.
3. **Multi-base support is several receipts.** A module may declare several bases. Each base
   gets its own build (one build links against one base), its own receipt and its own verdict;
   nothing transfers. `bases` in `module.json` grows only when a receipt on that base exists.
4. **Cards follow the receipts.** What a listing shows about a module (its bases, maps and
   the packs built on it) is read from declarations and receipts, never inferred from a
   composition that used it.

## Layers

| Layer | What it is | Changes how |
| --- | --- | --- |
| Foundation | The stock game or an upstream mod release, hash-verified | Never edited |
| Base | A foundation plus accepted quality-of-life fixes, no features | Only by a new sealed version |
| Core module | Shared runtime plumbing other modules depend on (an inventory arbiter, an item registry, a power-up runtime); itself a module with its own declaration | Versioned |
| Module | One feature: weapon family, perk, equipment, boss, companion; its own source, recipe, assets, tests and resource contract | Versioned |
| Composition | A named set of modules on a named base, with a sealed recipe and evidence record | Only by a new sealed build |
| Dependency pack | A composition whose members are the modules one feature needs to run (a GobbleGum system: the machine, each gum, the power-ups they pop, the shared runtime); the smallest installable form of that feature, with every member still installable alone | Only by a new sealed build |

A `pat project` recipe is a module. Its receipt records the inputs it was built from; record the
foundation's identity (release tag and the hashes of the base fastfiles you linked against) in
the same place. A `module.json` beside the recipe declares the bases and maps it was built for,
so `pat module plan` can refuse a composition on a base the module never saw (`docs/MODULES.md`).

## Titles and credits

A module's title names where the thing's identity comes from: "ICR-1 (Black Ops III)", never
the conversion pack it was taken from. `origin` in `module.json` drives the title and the
browse shelf; `donor` is the credit line for where the bytes came from (a conversion pack and
its author, a capture) and is preserved on every re-cut. Origin drives titles, donor drives
credit. An origin nobody has established stays `unverified` rather than borrowing the
donor's name (`docs/MODULES.md`).

## Naming

### Base tokens and foundation ids

| Token (declarations, compositions, profile names) | Foundation id (staging records, receipts) | What it is |
| --- | --- | --- |
| `stock` | `bo2-stock` | Unmodified Black Ops II Zombies, retail zones read in place |
| `b2` | `dlc5-beta2` | Zombies Declassified Beta 2, staged and hash-verified |

The table is the alias mapping between the two spellings; both name the same frozen base.
A new base adds a row; a row is never rewritten, so old receipts keep their meaning.


Test builds and installed folders are named `<base>_<feature>_<stage>`:

- base: a short token for the foundation (`stock` for the unmodified game, or the mod release's
  own short name);
- feature: the module;
- stage: `test` (one module on an unmodified base), `probe` (a self-driving state walk of one
  module that prints what it set; never a player candidate), `pack` (a named composition),
  `pub` (a release candidate).

`stock_hello_test` is a hello-world module on the stock game. A folder whose name or links do not
match the live base is a bug to report, not a template to copy.

## What is not a template

- An installed mod folder. Its composition is unknown until its recipe is read, and its acceptance
  was recorded for that composition.
- A "latest" folder or a shared last-result file. Which bytes are which is lost.
- A composition's acceptance on a previous base. It does not transfer to a new base; rebuild and
  retest.

## Sequence for new work

1. Choose the base from the map, not from where the tools live. A stock map needs no extra
   files; a mod base's map needs that base installed. Ask only if the base is genuinely
   ambiguous.
2. Build the module alone with `pat project build`; keep the receipt. A module never patches
   a map script, never carries another module's assets, and reaches a shared service (a
   power-up runtime, an inventory arbiter) only by naming it under `dependencies`.
3. Install it as `<base>_<feature>_test` with `pat game install-mod` and test there. Its
   verdict is earned alone; a pack never re-earns it and never substitutes for it.
4. Add the accepted module to a composition (`composition.json`, planned with `pat module
   plan` and built with `pat module build`), rebuild and test the composition for
   interactions only: every member registers, pool and slot counts, aggregate memory. A
   feature that is several modules ships as a dependency pack: each member declares what
   it calls under `dependencies`, the planner refuses a missing one, and the smallest
   useful subset ("the runtime plus one power-up") is a first-class pack of its own.
5. Never edit an installed folder in place; never carry acceptance across bases, maps or
   compositions.
