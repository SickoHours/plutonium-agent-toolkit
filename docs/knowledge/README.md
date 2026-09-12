# T6, IW5 and Plutonium knowledge for agents

Read these once per session, before the first `pat` command that builds or changes anything, and
work from them. They hold the engine and client facts that are expensive to rediscover by trial
builds. Each page is short, states facts rather than history, and names what is still unverified.
`docs/playbooks/` turns the facts into finite recipes. The words every page, receipt and skill
uses are defined once in [`../../CONTEXT.md`](../../CONTEXT.md); read it before saying
"verified", "installed", "loaded" or "accepted".

| Page | Read it when |
| --- | --- |
| [plutonium-t6.md](plutonium-t6.md) | You touch the Plutonium client, its storage folder, a mod folder or the console |
| [fastfiles-and-zones.md](fastfiles-and-zones.md) | You link, inspect or extract a `.ff`, or a build "succeeded" but the game disagrees |
| [gsc.md](gsc.md) | You write, port or compile a script |
| [zombies-contracts.md](zombies-contracts.md) | You add a weapon, perk, HUD element, boss or sound to a Zombies mod |
| [foundations.md](foundations.md) | You choose what to build on, or name a test build |
| [crashes.md](crashes.md) | The game dropped to the menu, closed, or the player said "crashed" |
| [iw5.md](iw5.md) | The target is Modern Warfare 3 under Plutonium: what the client loads, that scripts ship as source, where a mod goes and how it is selected |
| [iw5-tools.md](iw5-tools.md) | You need a tool for IW5 beyond the two pinned backends, or want to know what OpenAssetTools can build from source on that title |
| [other-titles.md](other-titles.md) | Someone asks about Black Ops 1 or World at War, or how the titles differ |
| [prior-art.md](prior-art.md) | You were asked for a feature and no donor or source is on disk |
| [bo3-workshop-formats.md](bo3-workshop-formats.md) | A Black Ops III Workshop map is the donor: what its fastfile, XPAK and sound banks are and how much reads offline on Linux |
| [weapon-camo.md](weapon-camo.md) | You port a Pack-a-Punch camo, or a ported gun renders the wrong camo |
| [weapon-aim.md](weapon-aim.md) | A ported gun aims wrong: blurry when aiming, no zoom, or sights that do not line up |
| [weapon-attachments.md](weapon-attachments.md) | A ported BO3 weapon has no iron sight picture, or carries a sight or optic |
| [bo3-sab-audio.md](bo3-sab-audio.md) | You recover a BO3 donor weapon's sounds offline, or rebuild its alias rows |
| [engine-limits.md](engine-limits.md) | A build compiled and linked but the engine rejected it at load; you are about to design to a number |

Every fact here was learned on a real T6 Zombies install with real ports. Where a number is a
measured engine limit it says so; where it is a working rule from experience it says that too.
When a page is wrong for the user's machine, fix the page in the same change as the fix.

Three pages carry data behind them, shipped in the package and generated from the shipped
Zombies zones: `pat knowledge builtin <name>` (which script VM a call exists on, with which
argument counts), `pat knowledge limits [--map <zm_map>]` (the limits and what a map's loaded
zones already carry against each) and `pat knowledge signature --log <slice>` (which recorded
crash line this is and what fixed it). Ask the data before designing to a number or a name.
