# Playbooks

A playbook is a finite recipe: the commands to run, in order, each with the receipt field that
proves it, and the conditions that end it. Read the playbook for the task before the first
command, then run it. Read `docs/knowledge/` once for the facts behind the steps, and `CONTEXT.md` for the words.

| Playbook | Use it when |
| --- | --- |
| [first-build.md](first-build.md) | The toolkit is installed and nothing has been built on this machine yet |
| [add-a-script.md](add-a-script.md) | A mod needs a new or changed server or client script |
| [port-a-feature.md](port-a-feature.md) | A feature from another mod or title is wanted in a T6 mod |
| [preflight-weapon-rig.md](preflight-weapon-rig.md) | A weapon's first-person model or animations are about to be packaged for the first time |
| [preflight-hud-text.md](preflight-hud-text.md) | A mod draws text or icons on the HUD |
| [preflight-scripts.md](preflight-scripts.md) | Any build with new or changed scripts is about to be installed for the first time |
| [preflight-audio-memory.md](preflight-audio-memory.md) | A build adds sounds or large assets and is about to be installed for the first time |
| [diagnose-a-crash.md](diagnose-a-crash.md) | The game dropped to the menu, closed or the player said "crashed" |
| [package-and-install.md](package-and-install.md) | A build is verified and should go into the client's storage folder |

Every playbook has the same five sections: **Preconditions** (what must already be true),
**Steps** (numbered, exact commands, the receipt field that proves each), **Do not** (commands that
are wasted here), **Stop conditions** (what ends it, and what needs the user) and **Report** (the
separate facts to state). The sections are enforced by a test so the shape cannot drift.

Commands are shown for a POSIX shell with `pat` on the path; on Windows PowerShell use the same
arguments. `<out>` is always a new directory the toolkit creates; pick a fresh name per job.
