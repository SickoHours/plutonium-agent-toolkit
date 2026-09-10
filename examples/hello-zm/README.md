# hello-zm

The smallest T6 Zombies mod the toolkit can build. Installing it into Plutonium storage and loading it in the game are separate routes that do not exist yet. It prints one line to each
player when they spawn and nothing else. It uses only engine builtins, so gsc-tool compiles it
offline without T6 include files. The qualification loop in `docs/SUPPORT.md` uses it
because success or failure is unambiguous and it depends on no assets.

```text
examples/hello-zm/
├── project.json          build recipe consumed by `pat project plan|build`
├── scripts/hello.gsc     the script (target scripts/zm/hello_zm.gsc inside mod.ff)
└── README.md
```

The build sequence is:

```powershell
pat project plan  examples\hello-zm\project.json --output ..\jobs\hello-plan-001 --json
pat project build examples\hello-zm\project.json --output ..\jobs\hello-build-001 --json
pat project verify ..\jobs\hello-build-001\receipt.json --inputs --output ..\jobs\hello-verify-001 --json
```

Build compiles `hello.gsc`, links `mod.ff`, reads it back and compares the raw file. That is
offline evidence, and in this version it has only been exercised against fake backends (see
`docs/SUPPORT.md`). Loading the mod in the game and seeing the line on screen is a separate step
that needs the user's go-ahead and a native Windows host.
