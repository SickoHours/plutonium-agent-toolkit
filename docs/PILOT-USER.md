# Pilot: the user journey

This is the first of two acceptance tests the toolkit must pass before `1.0.0`, and the one I
recommend before announcing the beta. It answers one question: **can a person who has never
seen this project hand it to their own agent and get a working mod loaded, using only what is
in the repository?**

## Rules

- The pilot is someone other than the maintainer, on their own Windows PC with Plutonium.
- Their agent is on a **different harness** than the one used to build the toolkit (if the
  toolkit was built with Claude Code, pilot with Codex, Gemini CLI, Cursor or another agent).
  This is the proof that "agent-native" does not mean "works with one vendor".
- The maintainer does not help in real time. Questions the pilot has to ask are findings.
- The pilot records what happened, not what should have happened.

## Script for the pilot

Give your agent this, verbatim:

> Clone https://github.com/SickoHours/plutonium-agent-toolkit and follow README.md. I want you
> to install the toolkit, set it up for my Plutonium installation, build the example mod, install
> it, and then, asking me before each game command, launch Black Ops II Zombies, load Town with
> the example mod and confirm the mod's message appears. Tell me what worked, what did not, and
> what you were unsure about. Do not guess at anything the documentation does not tell you; ask
> me instead.

Then, once that is done, give it this:

> Now break something on purpose: rename the `gsc` backend folder under the toolkit's backends
> directory and try to build the example again. Then put it back. Tell me whether the error
> message told you what to do.

And finally:

> Uninstall the toolkit and remove its configuration. Tell me exactly what you removed and what
> you left in place.

## What the pilot records

| Question | Answer |
| --- | --- |
| Harness and model used | |
| Windows build, Python version, Plutonium build | |
| Minutes from clone to `pat doctor` passing | |
| Minutes from `pat doctor` to `hello_zm` loaded in game | |
| Questions the agent had to ask the human | list each |
| Commands that failed and the `error_code` | list each |
| Anything the agent guessed instead of reading | list each |
| Did the broken-backend error explain the fix? | yes / no / partially |
| Did uninstall leave anything behind? | list |
| Would you trust this toolkit with a mod you cared about? | one sentence |

## What counts as passing

Every row above answered. The agent reached a loaded Town with the hello-zm line visible without
asking the maintainer anything. Every failure the agent hit produced an `error_code` whose hint
named the fix. Anything short of that is a finding, and each finding becomes an issue.

Open the findings as issues with the `pilot` label, one per finding. The maintainer fixes them
or documents them as known limitations in `docs/SUPPORT.md` before the beta announcement.
