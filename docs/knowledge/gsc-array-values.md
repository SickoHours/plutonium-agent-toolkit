# T6 GSC array assignment and owner writeback

A running T6 PC server-VM witness observed **value semantics for array assignment**:
mutating a local copy did not change the array it was assigned from. A new,
self-contained example of the observed operation is:

```c
array_value_example()
{
    original = [];
    edited = original;
    edited[0] = true;
    println(original.size); // observed: 0
    println(edited.size);   // observed: 1
}
```

This is observable copy-on-write behavior, not a claim about the VM's internal
allocation strategy. Do not treat `edited` as a mutable alias of `original`.
A loop can fill its local array correctly while its caller or state owner still
holds an empty array. Compilation and readable local values do not detect that.

## Updating an owned array

Write through the owner's field directly, or explicitly assign the changed local
array back to that field. For example, this update retains the local result:

```c
level.example_entries = [];
entries = level.example_entries;
entries["sample"] = true;
level.example_entries = entries;
```

Without the last assignment, the local mutation is not an owner update. When
reviewing stateful code, follow each array's read, mutation and final writeback;
check the owner's value after the operation, not only the local variable.
For a helper returning a changed array, keep the returned value at the call site.

## JavaScript fixtures can conceal the bug

JavaScript arrays alias objects by default: `const edited = original; edited[0] = true`
changes `original` too. A GSC function translated into JavaScript can therefore
pass a state-update test even though it loses that update in the game.

A fixture for this behavior must model array assignment as a value copy and must
assert the final owner's contents. Include a negative control where a local
mutation without writeback leaves the owner unchanged. This does not justify
cloning every object: this array witness does not establish `spawnstruct`, entity,
or nested-container semantics. Qualify those separately before modeling them.

## Evidence scope

The assignment/mutation witness above was observed in a running T6 PC server VM.
No private scripts, logs, assets or build identifiers are included here. This is
an engine-behavior note, not a new route or a gameplay acceptance claim. Client-VM,
IW5, other-title and nested-container behavior were not established by this
witness. Test those contexts explicitly instead of inferring them from JavaScript.
