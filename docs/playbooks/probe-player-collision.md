# Probe player collision without mistaking it for standing support

Use when a rendered prop/platform looks usable, or a bullet-trace miss conflicts
with a suspected player collision object. This is a scoped development probe, not
a general construction workflow or an automatic gameplay verdict.

## Preconditions

- The target title, script VM, map and exact candidate are declared.
- A bounded, owned test object and its removal path exist; no unrelated entity is modified.
- Engine work has the person's authorization and the host's normal control ownership.
- Read [T6 collision traces](../knowledge/t6-collision-traces.md). A visual export alone
  has not established collision contents or player support.

## Steps

1. Check the intended native call forms and script VM:
   ```sh
   pat knowledge builtin physicstrace --json
   pat knowledge builtin playerphysicstrace --json
   ```
   Keep the source call sites and exact mask/bounds with the test plan. Do not treat
   a same-named client or other-title function as equivalent.
2. Inspect what the model/export actually retains. Record render bounds separately
   from collision-map/contents evidence. Missing collision data is unknown, not absent
   collision. Do not publish proprietary source or assets as the report.
3. In the authorized test, run a bounded non-moving trace probe against the known
   owned entity. Read `playerphysicstrace` as a vector; read the six-argument
   `physicstrace` result as a dictionary. Record the mask, swept bounds, fraction and
   expected-entity match. A bullet trace can be a comparison, not the sole gate.
4. Check a finite declared set of center/edge and overhead samples for the intended
   footprint. Distinguish a point surface from a swept-volume impact. An owned hit
   and clearance samples still do not establish full-player support.
5. Only after the probe gate passes, perform the separately authorized standing,
   walking and exit/return test. Record what the player actually did and whether
   supported geometry and containment held. Test safe removal and owner cleanup.
   Treat AI pursuit, zones, combat and round progression as separate qualifications.

## Do not

- Read `playerphysicstrace` as a dictionary or infer hit ownership from its vector alone.
- Substitute rendered bounds, a collision-sounding name or a glTF preview for contents evidence.
- Treat a tiny-box hit as proof of player-sized clearance, standing support or AI navigation.
- Broaden a failed trace into an arbitrary mask sweep or mutate unrelated map collision.

## Stop conditions

- Wrong entity, unknown return contract, inconsistent samples or blocked return: stop,
  retain the failed result and use the owned rollback path; do not move a player onto it.
- A completed trace gate permits only the next scoped test, not a gameplay acceptance claim.
- Standing or containment fails: retain that failure even if the earlier trace passed.

## Report

Use **offline verified** only for completed source/export/build checks.
Separate visual inspection, collision representation, point query, owned volume hit,
clearance, standing/walking, teardown and AI/combat results. Name untested stages.
Keep exact candidate identity and engine evidence privately; share only permitted
source-independent facts. No new `pat` live-probe route is implied by this playbook.
