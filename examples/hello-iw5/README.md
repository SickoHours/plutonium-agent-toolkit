# hello-iw5

The IW5 (Modern Warfare 3) counterpart of `hello-zm`: the smallest multiplayer mod the toolkit
builds for game `iw5`. It prints one line to each player on spawn and depends on no assets.

```text
examples/hello-iw5/
├── project.json          build recipe (game iw5, mode mp) for `pat project plan|build`
├── module.json           declaration so it can be a composition member
├── scripts/hello.gsc     the script (packed as source at scripts/hello_iw5.gsc inside mod.ff)
└── README.md
```

On this title the source is the payload. Plutonium IW5 compiles GSC itself and runs no gsc-tool
bytecode, so `project build` runs `gsc check` (the compiler's dry run) as the syntax gate and packs
the text (`docs/knowledge/iw5.md`).

```sh
pat gsc check examples/hello-iw5/scripts/hello.gsc --game iw5 --output ../jobs/iw5-check-001 --json
pat project plan  examples/hello-iw5/project.json --output ../jobs/iw5-plan-001  --json
pat project build examples/hello-iw5/project.json --output ../jobs/iw5-build-001 --json
pat project verify ../jobs/iw5-build-001/receipt.json --inputs --output ../jobs/iw5-verify-001 --json
pat configure --plutonium-storage-iw5 <abs path to storage/iw5>
pat game install-mod ../jobs/iw5-build-001/packages/mod.ff hello_iw5 --json
```

Then, in the Plutonium IW5 console: `fs_game mods/hello_iw5` and start a private match. IW5 has
no Mods menu and no `pat game` route sends this line.

Scope: the build pipeline (check, link, read back, byte-compare) for IW5 has run with the pinned
gsc-tool 1.4.10 and OpenAssetTools 0.33.0 on Linux and Windows: the Linker wrote an `IWffu100`
fastfile and the Unlinker read it back as `Loaded zone "mod" (IW5)`. Whether this script prints
inside a running IW5 match has not been observed; the playbook
`docs/playbooks/build-an-iw5-mod.md` says how to record that first.
