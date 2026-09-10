# Track record: what this approach has built

This page is generated from `docs/track-record.json`, an export of the authoring workspace's
private module registry and reviewed acceptance records. It describes what a coding agent,
working the way `AGENTS.md`, the knowledge pages and the playbooks describe, has already
produced for Plutonium T6 Zombies. Private receipts back every row; they are not published.

It is the wide view. [SUPPORT.md](SUPPORT.md) is the narrow one: it grades the packaged `pat`
routes one at a time and is deliberately strict. Read both, and do not tell a user something is
impossible because it has no packaged route; several rows below had none.

**107 of 165 cataloged modules are player-accepted.**
Registry reviewed 2026-09-10; milestones reviewed 2026-09-10.

Counting: One implementation family per row; PAP/alternate/internal forms are not additional ports. Reawakened and native same-name guns remain distinct implementations. Support and program rows are not weapon counts.

Every acceptance is scoped to the exact package, base and map in its private receipt. Acceptance does not transfer to another base, map, composition, co-op play or measured performance.

## The workflow that produced them

1. You describe the feature.
2. The agent researches the donor, extracts or recovers assets, adapts or writes tools, then builds and verifies the package offline.
3. The agent installs the build and launches the game under the shared live lock.
4. You playtest and give a scoped verdict; the agent records it against the exact package hash, base and map.

Step 2 is where the agent does most of its work and where the packaged routes are only part
of the toolbox. Step 4 is a human verdict; the toolkit never records one on its own.

## Accepted by category

| Category | Accepted | Entries | Other statuses |
| --- | --- | --- | --- |
| firearms-reawakened | 43 | 43 | none |
| wonder-weapons | 20 | 26 | failed-or-paused 2, pending 4 |
| firearms-native-ports | 11 | 11 | none |
| gobblegums | 6 | 21 | pending 15 |
| melee | 5 | 13 | failed-or-paused 2, preview 6 |
| perks | 5 | 5 | none |
| tacticals | 5 | 6 | pending 1 |
| perk-support | 3 | 3 | none |
| powerups | 3 | 10 | pending 7 |
| bosses | 2 | 3 | pending 1 |
| equipment | 2 | 4 | failed-or-paused 1, pending 1 |
| firearms-other | 1 | 1 | none |
| gum-support | 1 | 1 | none |
| abilities | 0 | 1 | pending 1 |
| companions | 0 | 1 | pending 1 |
| core-services | 0 | 2 | pending 2 |
| effect-adapters | 0 | 8 | pending 8 |
| powerup-support | 0 | 1 | pending 1 |
| programs | 0 | 1 | pending 1 |
| specialists | 0 | 3 | pending 3 |
| weapon-support | 0 | 1 | pending 1 |

Status words, as the registry defines them:

- `accepted-scoped`: Owner acceptance in stated legacy scope, which may be broad or presentation-only; not automatically independently modular.
- `accepted-report-unbound`: Owner success report lacks exact tested package/map binding.
- `pending`: Source/candidate exists but reviewed evidence does not establish player acceptance.
- `failed-or-paused`: Player failure or paused work; repairs do not inherit acceptance.
- `preview`: Incomplete presentation/behavior preview.

## Representative milestones

One row per milestone, with what the agent did to get there and the exact scope of the verdict.

### Baby Gun / 31-79 JGb215

Accepted 2026-09-05 on Zombies Declassified Beta 1, Der Riese. Category `wonder-weapons`.

**How:** Ported with its shrink-and-stomp behaviour, miniature Hellhound coat textures and a real Pack-a-Punch path; runtime dog tags and same-frame contact kills were verified from logs before the player verdict.

**Scope of the verdict:** Solo Der Riese: appearance, audio, shrink/stomp, miniature dogs and PAP.

### 17-family wonder-weapon Arsenal

Accepted 2026-09-06 on Zombies Declassified Beta 1, Der Riese. Category `wonder-weapons`.

**How:** Five consecutive startup failures (unresolved builtins, a malformed animation state table, a projectile-effect table overflow, a missing rumble asset) were each diagnosed from logs and fixed by the agent before the accepted build.

**Scope of the verdict:** Broad pool acceptance; individual modes, charge and soak cases not itemized. Co-op and other maps separate.

> i tested most and omg they all work so good

### Eleven native firearm ports

Accepted 2026-09-06 on Zombies Declassified Beta 1, Der Riese. Category `firearms-native-ports`.

**How:** Normal and Pack-a-Punch forms registered through the native weapon registry; the verdict was bound to fresh engine state (loaded profile, map, running server) and the package hash.

**Scope of the verdict:** All eleven reported working; per-action, co-op and soak cases not itemized.

> also just confirmed the firearms all work !!

### Panzer Soldat and Brutus

Accepted 2026-09-07 on Zombies Declassified Beta 1, Der Riese. Category `bosses`.

**How:** Native actor implementations preserved and summoned through the developer menu; pursuit, flamethrower, claw grab, armour weak points and repeated summons were on the pre-load checklist.

**Scope of the verdict:** Manually summoned Der Riese scope through the menu.

> Panzer's fully ported, working great.

### 43 Reawakened normal/PAP pairs

Accepted 2026-09-08 on Zombies Declassified Beta 1, Der Riese. Category `firearms-reawakened`.

**How:** Fitted under the engine's byte-wide weapon index by measuring the live slot table read-only and substituting stock IDs from a reviewed roster manifest.

**Scope of the verdict:** Accepted across three separate rosters, including both repaired scopes; the combined roster's box, wall-buy and PAP acceptance is pending.

> Everything sounds good. All of the weapons were tested going good.

### World at War perks on four maps

Accepted 2026-09-08 on Zombies Declassified Beta 1, Nacht der Untoten, Verruckt, Shi No Numa, Der Riese. Category `perks`.

**How:** Perk machines placed and rendered per map with correct icons; installed file hashes were reverified against the build before the verdict was recorded.

**Scope of the verdict:** Placement, machine and icon verdict on all four maps; not every perk effect, co-op or soak.

> Okay, I just tested and it all works perfectly good. Everything is so beautiful. Consider this pass.

### Bloodhound and Meat Wagon (from Black Ops III Shadows of Evil)

Accepted 2026-09-09 on Zombies Declassified Beta 1, Der Riese. Category `firearms-other`.

**How:** Donor recovered by a read-only page snapshot of the user's already-loaded BO3 match, pinned by process identity, sealed into a hashed donor index and replayed offline; layouts decoded from Greyhound and HydraX source. The first install was rejected for a distorted first-person rig; the agent rewrote the animation encoder, then repaired the native left-hand slot, and that build was accepted.

**Scope of the verdict:** Normal Bloodhound and PAP Meat Wagon on Der Riese after the native left-hand repair; a PAP projectile/audio follow-up, lifecycle, co-op, other maps and performance are separate.

### GobbleGum machine and gums on Beta 2

Accepted 2026-09-10 on Zombies Declassified Beta 2, Der Riese. Category `gobblegums`.

**How:** Original machine art and animations, a memory repair and a purchase-flow replacement, rebuilt as a single module on the new base after the foundation cutover; the first Beta 2 module to reach playable Der Riese.

**Scope of the verdict:** Five previously reported bugs confirmed fixed on this build; frame drops unresolved; not an all-gum, lifecycle, co-op or other-map verdict.

## Beyond the packaged routes

`pat` packages the routes that have a stable interface and a receipt shape. The agent is not
limited to them. These are workflows the agent completed by reading upstream source, driving a
tool directly, or writing an adapter, and what a fresh agent can start from to repeat them.

| Workflow | Packaged route | What the agent did | Reproducible from |
| --- | --- | --- | --- |
| Live BO3 donor capture | `weapon catalog` and `weapon plan` consume the sealed donor; the capture itself has no packaged route | A read-only snapshot of an already-loaded Shadows of Evil match, process identity pinned by PID and start time, about 4.6 MB of pages sealed with SHA-256 for offline replay. Nothing was launched, restarted or written to the game. | The donor receipt and `bo3-page-capture-v1` manifest format in `docs/WEAPONS.md`; Greyhound and HydraX source for the layouts |
| T6 IPAK texture extraction on Linux | none | The agent ported Greyhound's IPAK reader to a bounded Linux adapter, indexed a 13,366-entry base package and decoded selected images to DDS with validated dimensions. | Greyhound's `IPAKCache.cpp`; the adapter pattern in `docs/contributors/ADDING-A-BACKEND.md` |
| Live map geometry capture (Husky and C2M) | none | Both original exporters were driven against an already-loaded Nuketown under the live lock, every consumed byte re-verified against the process, with an offline replay that reproduces every artifact. | The upstream exporters' source; `docs/FOR-AGENTS.md` step 4 (add a route) once the adapter exists on the user's machine |

## What this page is not

It is not a promise that any row works on another base, map or machine, and it is not a route
evidence level. A user's own build earns its own receipts and its own verdict. When the
authoring workspace's registry changes, the data file is re-exported and this page regenerates.

<!-- Generated by tools/track_record_doc.py; edit docs/track-record.json, never this page. -->
