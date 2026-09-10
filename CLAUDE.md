# CLAUDE.md

This file orients Claude Code. The operating contract is in `AGENTS.md`; read it in full, it is
the single source of truth and every other harness reads it directly.

@AGENTS.md

## For Claude Code specifically

- You have the Read, Edit, Write, Bash and Glob/Grep tools you need to install, configure, run,
  debug and adapt this toolkit on the user's machine. Use them; this repository never asks you to
  install another agent or a provider account.
- `skills/plutonium-agent-toolkit/SKILL.md` is a plain-Markdown skill you can read directly, and it
  installs as a Claude Code skill if the user wants it discoverable. It is harness-neutral by
  design; nothing here depends on a Claude-only feature.
- Treat the toolkit as malleable. When the user's setup does not match a default, prefer
  `pat configure`, `PAT_HOME` and `PAT_BACKEND_*` first, then edit the small adapters in `src/`
  with a test, over telling the user something is unsupported. `docs/FOR-AGENTS.md` explains how.
- When you finish a task, report what was verified versus assumed, using the six levels in
  `AGENTS.md`. Do not present an `implemented` route as if it had a native receipt.
