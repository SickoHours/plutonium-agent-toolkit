# BO3 weapon audio offline: the SAB name table, the alias namespace and the prototype fallback

Across the authoring workspace's two BO3 weapon ports, weapon audio was recovered without holding
the donor game open. The first port carved its recordings by name and read its alias chain from
one live pass; the second recovered a whole family with no new live capture at all. This page
complements `bo3-workshop-formats.md`, which stops at the bank header. Words: `CONTEXT.md`
(donor, sealed donor, preflight). Steps: `docs/playbooks/port-a-bo3-weapon.md` (step 4 and the
audio bullet of step 5).

## The bank and its name table

A BO3 sound bank (`.sabl` loaded, `.sabs` streamed) has magic `2UX#` and version 15. Its header
carries the entry count, the fixed name width (`name_size`) and the name table's offset
(`name_offset`); the name table is that many fixed-width records, each a recording path.

| Job | How |
| --- | --- |
| Find a recording | Match the name table entry by its path; the donor's own alias records name it, and the bank also carries engine suffixes that distinguish loaded from streamed and platform |
| Carve it | Read the entry's recorded offset and byte count; the data at the offset begins with `fLaC`; write exactly that many bytes |
| Convert it | Decode the FLAC to the T6 audio contract's canonical PCM WAV; native T6 streamed FLAC uses 1,024-sample blocks, so set and check that block size |
| Prove it | Hash every carved file into the sealed index; the prepare step refuses to run if any input hash differs |

## The alias namespace

The serialized sound-alias records are readable from a retained decompressed zone. Each record's
string fields name the alias, a secondary alias (the chain), a stop alias and the recording
path. Walking the secondary chain transitively collects every recording a family needs — the
donor's fire -> mechanical -> low-frequency chain and the tail layers — and each alias's
recording path is checked against the bank's name table before a byte is carved.

The record layout is a property of one executable build, so treat string-identified records as
the anchor and probe any offset before trusting it. The strings alone do not settle the numeric
mixer fields; those need a live alias pass or the prototype fallback below.

## The fallback: a native prototype row

When a family's alias rows were never captured live, there are no donor mixer values to convert.
Build each T6 alias row on a native prototype row of the same kind — a fire player row, a fire
NPC row, a foley row — and override the recording path, storage, looping and limits, setting the
secondary to the port's own alias name so the chain stays intact. The donor's recordings and its
fire -> mechanical -> low-frequency grouping remain donor data; the mixer values on a prototype
row are a documented adaptation, not donor data, and every one belongs in the prepare report.
When a named recording is absent from the bank, use the nearest recorded layer and record that
stand-in too. Exact BO3 mixer values require a live alias capture.

The second port validated the route: 53 recordings carved by name, 72 alias rows built, the package
linked, and every row re-read byte-identical by name. Its missing recordings and every prototype
row are listed in its prepare report as adaptations.

## Check before install

- Every carved recording starts with `fLaC` at its entry offset and is length-bounded by the
  entry, not by the next entry by assumption; all carved bytes come from the sealed donor bank.
- Every alias's recording path resolves in the bank's name table; every `Secondary` resolves
  within the built alias set before linking, and no row points at a missing alias.
- The FLAC-to-PCM conversion and the 1,024-sample block rule for streamed audio are checked;
  decoded PCM equality does not prove audible playback, so listen before accepting.
- Every alias family the clips need is covered: fire player and NPC, mechanical layers, foley,
  reload, and the upgraded form's layers.
- Each row is marked donor (recording, chain) or adaptation (prototype mixer row, stand-in
  layer) in the prepare report; no prototype row is presented as donor data.
- Rows re-read equal after linking, and `docs/playbooks/preflight-audio-memory.md` passes.
