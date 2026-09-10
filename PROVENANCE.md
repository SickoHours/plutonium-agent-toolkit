# Source provenance

This repository started with a fresh history on 2026-09-09. Its design and parts of its code
descend from private Linux-first tooling built between 2026-09-06 and 2026-09-09 in the
author's modding workspace. That workspace, its conversations, recordings and game assets are
not published. This file records where reusable ideas and code came from so that lineage is
honest without exposing private material.

| Area in this repository | Descends from | Private commit at import | Notes |
| --- | --- | --- | --- |
| `core/errors.py`, `core/receipts.py` | `halo_modding/common.py` (development CLI) | gaming-desktop `90ec824856aec44ef57629480288328385a56803` | Exit codes, stable error strings, receipt shape, refuse-overwrite rule |
| `dev/backends.json`, `dev/backends.py` | `t6-tools-setup/windows/programs.json`, `windows/runtime/setup.py` | gaming-desktop `90ec824856aec44ef57629480288328385a56803` | Pins, HTTPS-only download, archive safety, receipt-verified reinstall |
| `game/native.py`, `game/engine.py`, `game/control.py`, `game/maps.json` | `shared/plutonium-control/windows/{native,cli,maps}` (0.1.0-preview.1) and `plutonium-dev-toolkit/gameplay` | game-modding `3d06b09c0a8831cb71b9b901b4193c0422bf720e`, gaming-desktop `90ec824856aec44ef57629480288328385a56803` | Win32 console transport, marker queries, map recipes (18), load-ID/check-load semantics, no-replay rule. Rewritten to this toolkit's error/receipt contracts; the private-preview launch route (open launcher only) is replaced by the fixed-URI launch with focus logging |
| `testing/routes.py` contract | `plutonium-dev-toolkit/testing/*` and `plutonium-dev-lab/lab/test_runs.py` | gaming-desktop as above; dev-lab `c569822fd064a83c4d9b123664160de43d1a2a86` | Run ledger, capture health, marker/clip semantics, cancel-hands-to-human. The Linux capture stack (Hyprland, wl-screenrec, PipeWire) is not ported |
| `dev/blender_worker.py`, `dev/models.py` | `halo_modding/blender_worker.py`, `halo_modding/models.py` | gaming-desktop `90ec824856aec44ef57629480288328385a56803` | Worker imported with a neutral temp-name prefix; adapter rewritten to this toolkit's contracts |
| `dev/media.py` | `halo_modding/native.py` (audio/image/lua sections) | gaming-desktop as above | Same argument shapes and post-checks |
| `dev/weapons.py`, `docs/WEAPONS.md` | `halo_modding/weapons.py`, `BO3_WEAPONS.md` | gaming-desktop as above | Same donor/recipe schema and gates; rewritten validation |
| `AGENTS.md`, `SETUP-PROMPT.md` | `t6-tools-setup/windows/docs/AGENTS.md`, `plutonium-control/windows/SETUP-PROMPT.md` | gaming-desktop, game-modding as above | Rewritten for this product; same operating rules |
| `docs/history/` | Author's playtest and porting records | not imported | Summaries only; no transcripts |

## What was deliberately not imported

- The in-game typed test receiver (`76_testing.gsc`, `77_recipes.gsc`). It belongs to a
  proprietary developer menu. A standalone, Apache-2.0 receiver is a 1.0 deliverable.
- Any game asset, fastfile, donor model, recording, screenshot, console log or chat transcript.
- Machine-specific paths, desktop integration, Stream Deck pages, the Linux live lock.
- The old command names (`halo-modding-dev`, `halo-plutonium-dev`). This toolkit is `pat`.

## Upstream references consulted

- Plutonium console and mod loading documentation: https://plutonium.pw/docs/
- Plutonium launcher protocol handler (`plutonium://play/t6zm`): https://plutonium.pw/docs/changelog/
- Microsoft Win32 console, process and window APIs: https://learn.microsoft.com/windows/
