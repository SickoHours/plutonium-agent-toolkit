# T6 PC script string-pool addresses

The header-v1 string pool starts at byte 64 and ends at the header's `include_offset`
(unsigned little-endian 32-bit value at byte 12). Its strings are NUL-terminated.
String references in imports, exports and string fixups use **16-bit starting addresses**.
A start at 65535 fits; 65536 does not. A final string may extend beyond 65535 without
violating this particular invariant. Do not substitute a total-pool-size threshold.

An unchecked compiler can truncate an address. Disassembly may fail, or may resolve the
wrapped value to an earlier valid string boundary. Therefore successful compilation or
readback alone cannot establish this address invariant. `gsc compile` checks every emitted
T6 pool before returning success, including child compiles in project/module builds.
Malformed headers, pool boundaries, unterminated strings and oversized starts are refused
as `backend_failed`, with the check name and offending offset in the failure details.
Successful compile results include `artifact_checks`. Dry-run `gsc check`, decompilation
and IW5 compilation do not claim this check; no bytecode is produced by a dry run.

Shorten repeated descriptive text or split appropriately separated scripts to reduce string
addresses. Continue other readback, external-symbol and runtime checks: this guard only
establishes the pool-address invariant, not complete bytecode validity or gameplay behavior.

Primary format references: xensik/gsc-tool commit
`cd304ac752fe52ae1cd6726e5edb56e5f838595c`,
[assembler.cpp](https://github.com/xensik/gsc-tool/blob/cd304ac752fe52ae1cd6726e5edb56e5f838595c/src/arc/assembler.cpp#L79)
(header-v1 pool placement and u16 string-reference writes), and
[disassembler.cpp](https://github.com/xensik/gsc-tool/blob/cd304ac752fe52ae1cd6726e5edb56e5f838595c/src/arc/disassembler.cpp#L83)
(pool traversal and offset lookup). This documentation describes the format; no upstream
implementation code or game assets are copied.

