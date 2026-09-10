# Preflight: audio and memory

Gates before the first install of any build that adds sounds or large assets. Each came from a
build that passed decoded-audio equality and then failed at map load with an out-of-memory
dialog, played glitchy, or dropped shots.

## Preconditions

- The packaged sound banks and every added alias are listed with sample sizes and storage mode
  (loaded or streamed), from the readback or an inspection of the linked package.
- The full loaded composition is known: base fastfiles, map fastfile, mod, global scripts.

## Steps

1. Count sound assets across the whole load. Proof: the aggregate for map plus mod is
   recorded and below the observed 32-asset limit. Failure: `Exceeded limit of 32 'sound'
   assets`.
2. Total the preload reservation. Preloaded bank bytes plus the fastfile's virtual block, for the
   whole composition, not the new module's delta. Proof: the total is recorded and compared
   with the last build that loaded on this map. Failure: "Out of memory" dialog during map load
   with 76 GiB of host RAM free.
3. Stream large samples losslessly. Samples above the established threshold move to native
   streamed FLAC at 1,024-sample blocks; decoded PCM, rate, channels, loop flags, priorities,
   ducks and secondary aliases stay exact. Proof: the emitted codec headers are inspected and
   show 1,024. Failure: four mist streams at 4,096-sample blocks played glitchy after a fix
   elsewhere.
4. Protect hot one-shots. Aliases fired repeatedly in overlapping layers (gunshots, explosions)
   stay loaded under a bounded cap; only other large assets stream. Proof: the storage mode
   of each protected prefix is verified after the memory pass. Failure: repeated fire dropped out
   when every layer streamed against a ten-voice pool.
5. Compare with the accepted baseline, not the previous build. Retained aliases match the last
   build a person accepted, byte for byte where bytes are the contract. Proof: the comparison
   target is the accepted hash. Failure: an already-broken intermediate build passed as the
   baseline.
6. Keep volume representation exact. Exported volumes reimport to the stored amplitude; a
   precision fallback that truncates one unit is recovered, and integer rows are untouched. Proof: every retained alias's playback metadata compares exact.

## Do not

- Reason from the new module's asset delta; measure the whole composition's reservation.
- Take encoder source or PCM equality as proof of block size; inspect the emitted headers.
- Compare against the previous build when an accepted build exists; the accepted hash is the
  baseline.

## Stop conditions

- Reservation cannot be measured for the composition: record it unknown. Do not call the build
  memory-safe.
- Streaming pressure can only be measured in play: report it as a live gate.

## Report

Per gate, pass, fail or unknown, with the reservation number and the streamed and loaded counts.
State that audible playback and voice pressure remain live gates.
