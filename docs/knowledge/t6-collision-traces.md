# T6 player collision: choose the trace and the evidence

A bullet-trace miss is not proof that an object lacks player-blocking collision.
In a running T6 PC server-VM probe, `bullettrace` missed an owned stock player-clip
object, while `playerphysicstrace` found a surface and a small `physicstrace` volume
hit that same owned entity. The queries are not interchangeable.

## Source-backed call and return contracts

| Call | Result used by stock source | Important distinction |
| --- | --- | --- |
| `playerphysicstrace(start, end)` | A position vector, used directly in vector arithmetic | Not a trace dictionary; do not read `point["fraction"]` or `point["entity"]`. It alone does not identify an owned hit. |
| `physicstrace(start, end, mins, maxs, ignored, mask)` | A trace dictionary with `fraction` and optional `entity` | Check both collision and expected entity identity. Bounds describe the swept volume, not the rendered mesh. |
| `bullettrace(start, end, trace_entities, ignored)` | A trace dictionary | Its miss does not rule out collision found by the player/physics queries. |

Stock primary call sites: `maps/mp/zombies/_load.gsc` defines
`physicstracemaskphysics = 1` and `physicstracemaskclip = 8` (lines 92–95 in the
inspected T6 stock source). `_zm_ai_mechz_claw.gsc` combines those flags and calls
six-argument `physicstrace`, reading `fraction` and `entity` (lines 485–488).
Its earlier `playerphysicstrace` call adds a vector directly to the result
(lines 58–60). Thus the combined physics/clip mask is **9**, not a guessed mask.
`pat knowledge builtin physicstrace --json` and `playerphysicstrace` report the
shipped native call inventory; other overloads do not change this example's contract.

A newly authored, non-moving probe illustrates the distinction:

```c
probe_owned_collision(start, end, ignored, expected)
{
    result = spawnstruct();
    result.point = playerphysicstrace(start, end);
    trace = physicstrace(start, end, (-1, -1, -1), (1, 1, 1), ignored, 9);
    result.owned_hit = trace["fraction"] < 1
        && isdefined(trace["entity"]) && trace["entity"] == expected;
    return result;
}
```

The tiny box is a diagnostic choice, not a player-sized clearance guarantee.
Sweep impact position can differ from the point-query surface because of its
bounds; the observed unit half-height produced a corresponding vertical offset.
Do not require equal coordinates or treat the swept box origin as the surface.

## Geometry exports and runtime support are different facts

The inspected generated mesh JSON/glTF described render data but exposed no T6
collision maps or contents flags. That omission is not proof that the original
model has no collision. Rendered bounds, vertices or a model name do not prove
collision contents, player support or a usable floor. Require an explicit collision
representation/readback or appropriate engine probes; do not infer one from an
otherwise successful visual export. An exporter that explicitly preserves collision
metadata must establish that independently.

An owned physics hit proves only that the query found the owned collision object
under that mask and volume. It does **not** prove a player can stand or walk there,
that their full bounds fit, that rails contain them, or that AI can navigate there.
Use [the collision probe playbook](../playbooks/probe-player-collision.md) to keep
these tests and their outcomes separate.

## Scope

The trace distinction above has a running T6 PC server-VM witness. No private
source, logs, assets, coordinates or build identifiers are published here. This
does not establish another title/VM, every collision material, actual standing,
combat navigation, or a new toolkit route qualification.
