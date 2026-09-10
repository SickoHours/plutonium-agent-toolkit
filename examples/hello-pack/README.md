# hello-pack

The smallest composition the toolkit can plan and build: `hello-zm` and `hello-zm-two` on the
stock game for Green Run (`zm_transit`), as one `mod.ff`. Each module keeps its own
`project.json` recipe; its `module.json` declaration says which bases and maps it is built for,
what it depends on or conflicts with, and its resource contract. The composition recipe names the
base, the map, the module directories and a resource budget. The formats are specified in
[docs/MODULES.md](../../docs/MODULES.md).

```text
examples/hello-pack/
└── composition.json      base, map, module directories, budget
examples/hello-zm/module.json       declaration beside its recipe
examples/hello-zm-two/module.json   declaration beside its recipe
```

```sh
pat module plan  examples/hello-pack/composition.json --output ../jobs/pack-plan-001 --json
pat module build examples/hello-pack/composition.json --output ../jobs/pack-build-001 --json
pat project verify ../jobs/pack-build-001/receipt.json --inputs --output ../jobs/pack-verify-001 --json
pat game install-mod ../jobs/pack-build-001/packages/mod.ff stock_hello_pack --json
```

`plan` resolves the composition without running a backend: dependency order, declared conflicts,
whether every module declares the composition's base and map, whether two modules would ship the
same file, and whether the summed resource contracts fit the budget. `build` compiles both scripts,
links one `mod.ff`, reads it back and byte-compares both rawfiles. Loading the pack in the game
and seeing both lines on screen is a separate, human-authorized step on Windows.
