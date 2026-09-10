# Recording a qualification receipt

A receipt is what lets the next person believe a capability works. Keep it boring and exact.

1. Run the route on a native Windows 11 x64 host. Record `pat version --json`,
   `winver` build number, Plutonium client version if the game was involved, GPU vendor for capture.
2. Keep the full stdout JSON and exit status of every invocation in the sequence.
3. Sanitize: replace your username in paths with `<user>`, remove machine names, remove any run or
   request IDs you consider private, never include console logs or recordings. `tools/private_scan.py`
   must stay clean after you add the file.
4. Save under `docs/receipts/<version>/<route>-<date>.json` with a short `README.md` describing
   scope: which map, which mod, how many times, what was **not** covered.
5. Link it from the route's row in `docs/SUPPORT.md` and set the level honestly:
   `native` for tool execution, `game` only with a fresh engine reply and, for visual routes, a
   decoded non-black frame you inspected.

If something failed along the way, keep that receipt too and say so. A later success does not
erase an earlier failure in the same scope.
