# Copy this into your coding agent

Set up the Plutonium Agent Toolkit from this folder.

Read README.md, AGENTS.md and docs/GETTING-STARTED.md first, then docs/SUPPORT.md so you know which
capabilities are actually verified in this version. The development (build) tools run on Windows
and Linux. Game control and capture are native-Windows-only, because their transport is the Win32
console; skip them unless you are on Windows with Plutonium installed. macOS is untested and has
no pinned backends; if I am on a Mac, say so and stop after discovery.

This toolkit is meant to be adapted to my machine: if a default does not fit my setup, prefer
`pat configure`, `PAT_HOME` and `PAT_BACKEND_*`, and edit the small adapters in `src/` (with a test)
rather than telling me something is unsupported. `docs/FOR-AGENTS.md` explains how.

Handle the routine work yourself:

1. Confirm Python 3.11+ is available. If not, tell me the official installer to run; do not install
   it silently.
2. Install the toolkit for my user: `python -m pip install --user -e .` from this folder, then run
   `pat version --json` from an unrelated directory and show me the result.
3. Obtain the backends. Run `pat dev setup --plan --json` and show me what it will do on my platform.
   Where a pinned download exists for my OS, run `pat dev setup --json` to fetch and verify it. Where
   it reports `override-required` (no pinned build for my OS), find or install the tool and point the
   toolkit at it with an absolute path in `PAT_BACKEND_<NAME>` (for example `PAT_BACKEND_GSC`).
4. If I am on Windows and want game control later, find my Plutonium T6 storage folder (usually
   `%LOCALAPPDATA%\Plutonium\storage\t6`) and my `plutonium.exe`, and save them with `pat configure`.
   On Linux, game control is out of scope; configure only what the build tools need.
5. Run `pat doctor --json` and explain, in plain language, what is ready and what is not. `doctor`
   reports development-tool readiness separately from whether game control is supported on this host.

Keep this scoped to installation. Do not launch, attach to, query or change the game. Do not install
mods, other agents or paid services. Do not ask me for passwords or tokens.

Finish by telling me the exact installed command path, what passed, what is missing, and what
`docs/SUPPORT.md` says I can safely ask you to do next on this platform.
