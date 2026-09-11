# Prior art: where existing implementations live

An existing port or extraction of the thing you were asked for is the fastest donor. This page
says where such things are usually found and what container they arrive in, so the search in
`docs/playbooks/find-prior-art.md` starts in the right place. Every row is a place a real port
came from or was checked; none is a promise that a given item is there. Words: `CONTEXT.md`.

## By origin

| Origin of the feature | Where ports and extractions turn up | Container you will meet |
| --- | --- | --- |
| Another Call of Duty title (BO1, BO3, BO4, WaW, IW) | Black Ops III Steam Workshop items (mod-tools ports), UGX-Mods "full weapons" boards, GitHub repositories of cross-map weapon packs with per-weapon manifests | T7 `.ff` and `.xpak` (encrypted; read from a loaded game or with a T7 reader), loose `.ff` zones, per-weapon manifest folders |
| A non-CoD game (Saints Row, Halo, Half-Life, Resident Evil, Doom) | Ports to Source-engine games on the Steam Workshop (Left 4 Dead 2, Garry's Mod, Team Fortress 2); NexusMods pages for Dark Souls, Skyrim and GTA; ModelSaber and other Unity-game mod sites | Source VPK (MDL/VVD/VTX with VTF textures and WAV audio), Unity asset bundles, plain OBJ/FBX/PNG folders |
| A community-made weapon or item | The author's GitHub or ModDB page; a video with a download link; a Discord release mirrored on GitHub | A ZIP of loose assets and scripts, sometimes a whole replacement mod |
| The origin game itself | Its modding forum or wiki names the archive format and a community extractor | Game-specific packages (VPP and STR2 for Saints Row, PAK or WAD elsewhere) that need the named tool first |

## Reading a lead

- A listing proves that someone claimed to have it on that date. Bytes prove they had it.
  Acquire, hash and inspect before the word "donor" is used.
- Public download paths: release assets, a site's CDN, a public API. Steam's published-file
  details API returns direct file URLs for Workshop items without a login. A page that renders
  "removed" or "sign in" is a failed scrape, not a missing file.
- Source VPK and Unity bundles are readable offline with public libraries. A T7 fastfile is not:
  it needs the loaded-game capture route or a T7 reader. Count what is actually inside: meshes,
  bones, weight data, clips, textures, sounds.
- Jiggle, cloth or physics settings from the donor engine do not run in T6; they are a reference
  for baked motion, not a payload.
- Two independent leads for the same thing are worth more than one. Compare geometry, rigs and
  texture sizes and choose by inspection, not by upload date or vertex count.
- Narrow reuse: from a whole replacement mod take the one weapon definition, manifest or asset
  set; leave its balance, quests and map hooks behind.

## Content and terms

Decline a lead whose content is hateful or mocks a real person, whose assets are ripped from a
paid product without permission, or whose terms forbid reuse; say why and keep looking. What is
acquired stays on the user's machine unless the terms allow redistribution; a public listing is
not a licence to republish. Never log in, pay, or use credentials to reach a file.

## What this has produced

A melee weapon from a non-CoD title reached T6 with five accepted revisions after two community
Left 4 Dead 2 ports of it were found on the Steam Workshop, fetched from the public CDN through the
published-file API, verified by checksum and inspected with an open Source-engine reader: one
carried weighted flex bones, the other denser geometry and impact sounds. A published Dark Souls
port and a Unity saber were kept as backups. Native firearm ports took their per-weapon
dependency manifests from a public community cross-map repository as a checked reference. A Workshop item that inspection showed to be
hateful content was declined before any port work.
