# Receipts

Sanitized evidence that a route ran on a native Windows host. One directory per toolkit
version; files are produced by `tools/qualify_windows.py`, never hand-written. Usernames,
machine names, user-profile paths and request/load/job IDs are redacted before writing.

| File | Produced by | Level it can prove |
| --- | --- | --- |
| `<version>/tier1-offline.json` | `qualify_windows.py --tier offline` | `native` for discovery, configure, doctor, plan |
| `<version>/tier2-backends.json` | `qualify_windows.py --tier backends` | `native` for `dev setup`, `gsc`, `ff`, `project` with real backends |
| `<version>/tier3-game.json` | `qualify_windows.py --tier game --collect` plus human observations | `game` for the `game` routes exercised |

A receipt proves the exact scope in its `steps`. `docs/SUPPORT.md` links the receipt from each
route's row. A later failure in the same scope is recorded as a new receipt, not by editing an
old one.
