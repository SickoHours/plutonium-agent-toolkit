# Find prior art before building from nothing

The user names a feature and hands over no donor, no source and no files. Before designing
anything, find out whether someone has already built, ported or extracted it, for this game or for
any other. Popular things have been done; a port found is a port half done, and an extraction
found is a donor. Words: `CONTEXT.md` (**Donor**, **Sealed donor**, **Lead**, **Prior art**).
Where ports usually live, by origin and container: `docs/knowledge/prior-art.md`.

## Preconditions

- The request names the thing (a weapon, item, character, behaviour, HUD element) and its origin
  title, or enough to identify both. Settle the other decisions in a `pat-grill` round after this
  playbook, not before it: the leads change the answers.
- No donor is on disk for it. If one is (a `pat weapon catalog` receipt, a fastfile, an extracted
  folder the user points at), skip to `port-a-feature.md`.
- Your harness can fetch web pages, or you will say that it cannot and hand the search brief to
  the user at step 1. A search you cannot run is reported, never invented.

## Steps

1. Write the search brief: canonical name, origin title and year, aliases and misspellings, the
   forms wanted (normal, PAP, both) and which assets matter (model, animations, textures, sounds,
   script behaviour). Proof: the brief at the top of the module's README.
2. Search the T6 community first: has anyone shipped it for Plutonium T6 / Black Ops II Zombies?
   Look in GitHub (the name plus `zm`, `t6`, `bo2`, `plutonium`), UGX-Mods, ModDB, GameBanana,
   NexusMods and video demonstrations that link a download. Proof: a leads table in the README
   with URL, author, date, what the listing claims, terms, and the status `lead`.
3. Widen to every engine. A port to another game (Left 4 Dead 2, Garry's Mod, Dark Souls, GTA,
   Beat Saber, Minecraft, Skyrim) proves the assets were extracted once and usually ships them in
   a readable container (Source VPK, Unity bundle, a plain model folder). Check the Steam Workshop
   of those titles, their mod sites, and Black Ops III Workshop items for Call of Duty content.
   Proof: the leads table extended with engine and container.
4. Check the origin title's own extraction tools when no port exists: the game's modding forum or
   wiki names the archive format and a tool for it. Proof: tool name, format and the page that
   documents it, in the table.
5. Acquire only public bytes: release downloads, official CDN URLs, a public API such as Steam's
   published-file details. No login, no payment, no bypass of a paywall or DRM, and never a
   credential from the user. A page that says "removed" or "sign in" is a lead that failed to
   scrape, not proof the bytes are gone; the API or a mirror may still serve them. Proof: a
   downloads receipt (`downloads.json`) with URL, bytes, SHA-256 and time for every file, kept
   beside the files and outside the recipe's source tree.
6. Inspect before trusting: open the container and count meshes, bones, textures and sounds; note
   weight data, jiggle or physics settings and animation clips. Use
   `pat model inspect <model> --output <out> --json` for formats the toolkit reads and the
   container's own public tooling otherwise. Mark each asset retained, adapted or unsupported.
   Proof: an inspection record with the counts, and the marks in the leads table.
7. Check the content and the terms. Decline a lead whose content is hateful or mocks a real
   person, whose assets are ripped from a paid product without permission, or whose terms forbid
   reuse, and say why. Assets found this way stay on the user's machine unless the terms allow
   redistribution. Proof: a `content` and a `terms` line per acquired lead.
8. Seal the chosen donor: a hashed inventory a later plan can check (`pat weapon catalog` for a
   saved Black Ops III capture; otherwise a manifest with a SHA-256 per file). Then continue with
   `port-a-feature.md`. Proof: the manifest path and its hash in the README.

## Do not

- Design or build from a description while step 2 or 3 is unsearched; do not re-derive a rig, a
  texture set or a sound someone already extracted.
- Treat a listing as a payload. A lead becomes a donor only after acquisition, hashing and
  inspection.
- Log in, pay, scrape past a login, or use the user's credentials to reach a file.
- Copy a whole replacement mod when a narrow piece of it suffices; take the one definition,
  manifest or asset set, not the mod's balance, quests or map hooks.
- Import a donor's engine limits, physics settings or balance as facts about T6.
- Stop at "no T6 port exists". Other engines and the origin title's tools are two more tiers.

## Stop conditions

- A sealed donor exists: continue with `port-a-feature.md`.
- All tiers searched and nothing usable found: report the tiers, the leads that failed and why,
  and the one thing only the user can supply (their own copy of the origin title, or a capture from
  a game they have running). Ask for that; do not ask for a fact the search could have given.
- Content or terms fail step 7: stop that lead and say so; keep searching if other leads exist.
- No web access in this harness: stop after step 1 and give the user the brief and the tiers.

## Report

Nothing here earns a build fact: **offline verified**, installed, launched, playable, captured
and accepted are each "no" until a later playbook says otherwise. State: the brief; the leads
found, by tier, best first; what was acquired, with hashes; what inspection counted; what is
retained, adapted and unsupported; content and terms per lead; the sealed donor's manifest hash;
and what remains for the port.
