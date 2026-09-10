# Foundations: build on a clean base

## The rule

A new feature is built and first tested on an **unmodified base**, never on top of an existing
composition. Base plus the one module plus its declared core dependencies is the whole test
package. Acceptance recorded there is the feature's acceptance and is tied to that base.

Why: a one-feature test built by copying a big installed mod carries every retained weapon, perk
and script of that mod. The package is huge, a crash cannot be attributed, and the player's
verdict covers more than the feature. The symptom is visible in a storage folder where several
mods differ by one feature and each carries the full pack.

## Layers

| Layer | What it is | Changes how |
| --- | --- | --- |
| Foundation | The stock game or an upstream mod release, hash-verified | Never edited |
| Base | A foundation plus accepted quality-of-life fixes, no features | Only by a new sealed version |
| Core module | Shared runtime plumbing other modules depend on (an inventory arbiter, a menu adapter) | Versioned |
| Module | One feature: weapon family, perk, equipment, boss, companion; its own source, recipe, assets, tests and resource contract | Versioned |
| Composition | A named set of modules on a named base, with a sealed recipe and evidence record | Only by a new sealed build |

A `pat project` recipe is a module. Its receipt records the inputs it was built from; record the
foundation's identity (release tag and the hashes of the base fastfiles you linked against) in
the same place.

## Naming

Test builds and installed folders are named `<base>_<feature>_<stage>`:

- base: a short token for the foundation (`stock` for the unmodified game, or the mod release's
  own short name);
- feature: the module;
- stage: `test` (one module on an unmodified base), `pack` (a named composition), `pub` (a
  release candidate).

`stock_hello_test` is a hello-world module on the stock game. A folder whose name or links do not
match the live base is a bug to report, not a template to copy.

## What is not a template

- An installed mod folder. Its composition is unknown until its recipe is read, and its acceptance
  was recorded for that composition.
- A "latest" folder or a shared last-result file. Which bytes are which is lost.
- A composition's acceptance on a previous base. It does not transfer to a new base; rebuild and
  retest.

## Sequence for new work

1. Choose the foundation from the request. A stock map needs no extra files; a mod base's map
   needs that base installed. Ask only if the base is genuinely ambiguous.
2. Build the module alone with `pat project build`; keep the receipt.
3. Install it as `<base>_<feature>_test` with `pat game install-mod` and test there.
4. Add the accepted module to a composition by changing the composition's recipe, rebuild and
   test the composition for interactions, not the feature again.
5. Never edit an installed folder in place; never carry acceptance across bases.
