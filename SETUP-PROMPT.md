# Copy this into your coding agent

Set up the Plutonium Agent Toolkit from this folder on my Windows PC.

Read README.md, AGENTS.md and docs/GETTING-STARTED.md first, then docs/SUPPORT.md so you know
which capabilities are actually verified in this version. This toolkit is meant to be adapted to
my machine: if a default does not fit my setup, prefer `pat configure`, `PAT_HOME` and
`PAT_BACKEND_*`, and edit the small adapters in `src/` (with a test) rather than telling me
something is unsupported. `docs/FOR-AGENTS.md` explains how.

Handle the routine work yourself:

1. Confirm native Windows Python 3.11+ is available. If not, tell me the official python.org
   installer to run; do not install it silently.
2. Install the toolkit for my user: `python -m pip install --user -e .` from this folder, then run
   `pat version --json` from an unrelated directory and show me the result.
3. Find my Plutonium T6 storage folder (usually `%LOCALAPPDATA%\Plutonium\storage\t6`) and my
   `plutonium.exe`. Save them with `pat configure`. Do not guess; if you cannot find them, ask.
4. Run `pat dev setup --plan --json` and show me what it will download and from where. Then run
   `pat dev setup --json` to download the required backends. Allow time for the downloads.
5. Run `pat doctor --json` and explain, in plain language, what is ready and what is not.

Keep this scoped to installation. Do not launch, attach to, query or change the game. Do not
install mods, other agents or paid services. Do not ask me for passwords or tokens.

Finish by telling me the exact installed command path, what passed, what is missing, and what
`docs/SUPPORT.md` says I can safely ask you to do next.
