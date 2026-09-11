A T6 Zombies mod passed compile, link and readback and then failed at map load. The console
slice of that load is `<FIXTURE>/console_slice.log` and the mod's only script is
`<FIXTURE>/riser_glow.gsc`. Classify the failure with the toolkit before you change anything.
Then correct a copy of the script (same file name) so the same failure cannot recur: the loaded
set has no headroom in that pool, so the script must not register into it; keep
`riser_glow_think` and its message. Compile the corrected copy with the toolkit into a new
directory under `<RUN>/bench-06-classify-then-fix/`. Report the signature's class and cause, the
fix, and what the compile receipt proves and does not prove.
Run the lookup with `--output` so it leaves a receipt: `pat knowledge signature --log <FIXTURE>/console_slice.log --output <RUN>/bench-06-classify-then-fix/lookup --json`.
The score reads that receipt; a fix found by guessing leaves no such receipt.
