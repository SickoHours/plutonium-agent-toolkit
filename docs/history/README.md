# Engineering history

Why the rules in this toolkit exist, and which practices earned their place. Each note names the
problem or the practice, what exposed it and what the toolkit does about it now. No transcripts,
assets or personal data; summaries only. The outcomes these practices produced are on
[TRACK-RECORD.md](../TRACK-RECORD.md).

## What worked

### A lesson run as a checklist step

Rig failures kept reaching players after clean conversions and passing suites, because the
lesson lived in prose that nobody re-read. The first melee weapon built after that lesson became
a mandatory pre-package rig check went from offline build to five accepted revisions with no
repair records. **Now:** the four preflight playbooks (`docs/playbooks/preflight-*.md`) are
numbered steps with a proof per item, run before the first install, not after the first crash.

### One module on a named base

A test profile that carried a whole composition gave verdicts about more than the feature under
test, and one feature's failure blocked the others. Rebuilding one module alone on a named,
hash-verified base produced the first playable build on the new base after a base change, with a
verdict that names exactly what it covers. **Now:** `docs/knowledge/foundations.md` and the
playbook `port-a-feature.md` start every module from a foundation, and a verdict never carries
over to another base.

### A verdict bound to one build

Eleven firearm ports were accepted in one session because the verdict was recorded against the
loaded profile, the map, the running server and the package hash read from fresh engine state,
not against "the latest build". Later repairs could then say exactly what changed. **Now:**
`check-load` binds a load to process identity, and every receipt carries input and output hashes
so a verdict can name its build.

### Sealed donors

A weapon captured live from another title became a hashed, replayable input. When its first
install failed in game, the rig was repaired and rebuilt from the same sealed bytes without a
second capture. **Now:** `weapon catalog` re-hashes every donor file and refuses stale or edited
catalogs, so a plan proves it used the same bytes as the accepted port.

## What broke, and the rule it left

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
