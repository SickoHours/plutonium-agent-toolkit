# Copy this into your coding agent on the Windows PC

You are on my Windows 11 PC. Plutonium and Black Ops II Zombies are installed and I have
launched the game through the Plutonium launcher at least once. GitHub is authenticated as me.
Your job is to qualify the Plutonium Agent Toolkit natively on this machine and open a pull
request with the results. Nothing in this toolkit has run on real Windows yet, so expect to find
bugs; finding them is the point.

Read, in this order: `README.md`, `AGENTS.md`, `docs/WINDOWS-QUALIFICATION.md`,
`docs/SUPPORT.md`, `docs/contributors/RECORDING-A-RECEIPT.md`. Then follow
`docs/WINDOWS-QUALIFICATION.md` exactly. It has three tiers; stop at the end of each tier and
tell me what passed and what failed before continuing.

Rules for this session:

- Work on a new branch named `qualify/windows-<today's date>`. Never commit to `main`.
- Run `python tools/qualify_windows.py` for the offline and backend tiers; it produces the
  sanitized receipt. Do not hand-write receipts.
- Tier 3 touches the running game. Before every Tier 3 command, tell me which one you are about
  to run and wait for my go-ahead in this chat.
- If a command fails, keep its JSON output and exit status, fix the toolkit bug if the cause is
  in this repository, add a regression test, and rerun. Do not work around a failure by editing
  the receipt or skipping the check.
- Never read launcher tokens, login databases, process memory or command lines. Never kill the
  game. Never send player input.
- Redact my Windows username from any path before it goes into the repository. The qualify
  script does this for receipts; check any text you write yourself.
- When a tier is done, commit the receipt and any fixes, then open the pull request with
  `gh pr create` using the template. Fill in "Not verified" honestly. Reply to review comments
  from the automated reviewer, fix what is real, and push again until checks are green.

Finish by telling me, in plain language: which routes now have native receipts, which failed and
why, what you changed in the toolkit, and the pull request URL.
