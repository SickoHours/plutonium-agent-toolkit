# Receipts

Sanitized evidence that a route ran on a native host. One directory per toolkit version; files
are produced by `tools/qualify.py`, never hand-written. Usernames, machine names, user-profile and
home paths, and request/load/job IDs are redacted before writing. Each receipt's `environment`
names the OS (`os`, `platform_token`, `native_windows`, `native_linux`, `compatibility_layer`).

| File | Produced by | Level it can prove |
| --- | --- | --- |
| `<version>/<platform>-tier1-offline.json` | `qualify.py --tier offline` | `native` for discovery, configure, doctor, plan and `dev install-skills` (into a scratch home) on that platform |
| `<version>/<platform>-tier2-backends.json` | `qualify.py --tier backends [--media]` | `native` for `dev setup`, `gsc`, `ff`, `project`, `module` with real backends; with `--media`, also `audio` and `model` |
| `<version>/windows-tier3-game.json` | `qualify.py --tier game --collect` plus human observations | `game` for the `game` routes exercised (Windows only) |
| `<version>/<platform>-tier4-agent.json` | `qualify.py --tier agent --project … --instance … --model …` | `native` for the `agent` routes against the user's running T3 Code server (one proof thread) |

The `0.1.0a1` receipts predate the platform prefix (`tier1-offline.json` and so on) and were
produced by `tools/qualify_windows.py`, which is now a shim over `tools/qualify.py`. They are
native Windows 11 receipts.

A receipt proves the exact scope in its `steps`. `docs/SUPPORT.md` links the receipt from each
route's row. A later failure in the same scope is recorded as a new receipt, not by editing an
old one.
