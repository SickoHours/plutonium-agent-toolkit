# hello-zm

The smallest T6 Zombies mod the toolkit can build, install and load. It prints a message to the
console when the map starts and nothing else. The qualification loop in `docs/SUPPORT.md` uses it
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
offline evidence. Loading the mod in the game and seeing the console line is a separate step that
needs the user's go-ahead.
