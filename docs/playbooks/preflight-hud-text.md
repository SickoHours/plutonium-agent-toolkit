# Preflight: HUD text and icons

Run before packaging a mod that creates HUD elements. Every item is a check that has failed in
a real game after compilation and unit tests passed.

## Preconditions

- The script that creates the elements compiles alone (`add-a-script.md` step 2).
- You know which side owns each element (server-created player HUD versus client-side fields).
- A rendering reference exists when the design copies another mod: trace its purchase, attach,
  offer, held, expiry and cleanup flow, not only its dimensions and text.

## Steps

1. Font scale: every `fontscale` is at or above 1.0 and at most 1.15. T6 renders text below 1.0
   enormously oversized (**measured**, reproduced twice: labels at 0.75, 0.95 and 0.8 filled the
   screen while a 1.55 label was normal). Grep the script for every assignment and record each
   value.
2. Allocation pool: each element is created in a pool that is actually visible in the composed
   client. A forced non-archived pool shared with other tools hid five elements that the server
   reported as allocated. Use the pool the reference uses; do not override it.
3. Element budget: count HUD elements the mod holds at once per player plus the ones the base and
   any shared menu hold; a local count of five means nothing without the rest of the composition.
4. Lifecycle: every element has an owner and is destroyed on off, expiry, down, death, respawn,
   disconnect and map transition; a stale worker from a previous life cannot redraw it.
5. Input: while a menu element is open, D-pad navigation must not activate carried equipment and a
   held Select must not carry into a nearby pickup after close; ADS and melee permissions are
   restored to their captured values.
6. Strings and images: every string and icon material is precached at initialization; an icon
   needs its image binding at the moment it is acquired, not only in the zone.
7. Record the six results in the module README.

## Do not

- Ship a mockup's sub-1.0 scale because it "looks right" in the mockup.
- Take a unit-test HUD double as proof of rendering; it certifies the code path, not the pixels.
- Add a second grant or draw path to work around a rejected element; find the pool or lifecycle
  bug.

## Stop conditions

- Any item fails: fix and rerun the item.
- All pass: build (`add-a-script.md` step 5). Visibility is confirmed only by a person or an
  inspected frame after a load the user authorized.

## Report

List every font scale and pool used, the element count against the composition, the lifecycle
events covered, and say **offline verified; rendering not observed**.
