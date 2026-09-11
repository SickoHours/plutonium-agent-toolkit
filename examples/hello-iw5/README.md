# hello-iw5

The IW5 (Modern Warfare 3) counterpart of `hello-zm`: the smallest mod the toolkit builds for
game `iw5`. It prints one line to each player on spawn and depends on no assets, so `gsc-tool -g
iw5` compiles it offline and OpenAssetTools links it into `mod.ff`.

```text
examples/hello-iw5/
├── project.json          build recipe (game iw5, mode mp) for `pat project plan|build`
├── module.json           declaration so it can be a composition member
├── scripts/hello.gsc     the script (target scripts/mp/hello_iw5.gsc inside mod.ff)
└── README.md
```

Build it exactly like hello-zm, with the recipe naming `iw5`:

```powershell
pat project plan  examples\hello-iw5\project.json --output ..\jobs\iw5-plan-001  --json
pat project build examples\hello-iw5\project.json --output ..\jobs\iw5-build-001 --json
pat project verify ..\jobs\iw5-build-001\receipt.json --inputs --output ..\jobs\iw5-verify-001 --json
```

`project init --game iw5` writes the same shape into a new directory.

Scope: this exercises the build pipeline (compile, link, read back, byte-compare) for IW5, and it
has passed natively on Windows 11 with the pinned gsc-tool 1.4.10 and OpenAssetTools 0.33.0: the
Linker wrote an `IWff` fastfile and the Unlinker read it back as `Loaded zone "mod" (IW5)`. Whether
the script hooks and prints inside a running IW5 match is a separate, human-authorized step, and
asset-rich IW5 builds (models, images, sound) are not yet exercised. See the IW5 note in
`docs/SUPPORT.md`.
