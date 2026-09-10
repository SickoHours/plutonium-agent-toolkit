# Engineering history

Why the rules in this toolkit exist. Each note names the problem, what exposed it and what the
toolkit does about it now. No transcripts, assets or personal data; summaries only.

## Rigs that compile but break

Porting a BO3 weapon (Bloodhound) to T6 produced a fastfile that linked cleanly and loaded, yet the
view model's off-hand bones were wrong in game. Compile success proved nothing about the rig.
**Now:** model routes inspect bone names and hierarchy after conversion, and `docs/SUPPORT.md`
separates "offline verified" from "playable".

## The bytes on disk are not the bytes in the engine

A mod folder's `mod.ff` hash matched the build, but the running game had loaded an older package
from a previous session. **Now:** load operations return a load ID bound to process identity and
fresh engine state; `check-load` verifies that binding rather than trusting disk hashes.

## Lost acknowledgements

A console command was written but the reply marker never arrived. Repeating it would have double
purchased or double loaded. **Now:** `delivery_uncertain` is terminal. The agent inspects fresh
state; the toolkit never retries a game command automatically.

## Recording must outlive the chat

Handing the controller to a human mid-test closed the agent's session and would have stopped the
recording with it. **Now:** the recorder is a finite worker independent of any chat or panel;
`test cancel` stops automation and leaves capture running.

## Display power state changes what "background" means

One background capture run on the authoring machine produced zero fresh frames after the display
powered down, while a later run with the screensaver active and the monitor off succeeded. Two
conditions, two results. **Now:** capture reports the display condition it observed, and each
condition is qualified separately on Windows. No blanket promise either way.

## Version drift

The internal toolkit's changelog stopped at one version while the installed binary and guides
described the next. **Now:** `tools/release_check.py` fails CI when the package version,
`pyproject.toml`, the top changelog entry, `docs/SUPPORT.md` and the tag disagree.

## A compile is not a gameplay pass

Every one of the above came down to treating an earlier, cheaper signal as if it were the
expensive one. **Now:** the evidence ladder in `docs/SUPPORT.md` (contract, offline, native, game,
accepted) is part of every route's documentation and every changelog entry.
