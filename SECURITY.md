# Security policy

## Scope

This toolkit runs on the user's Windows machine with the user's privileges. It downloads pinned
third-party programs, runs them as subprocesses, attaches to the Plutonium T6 Zombies external
console and records the game window. It never:

- reads process memory, launcher command lines, tokens or login databases;
- injects code into the game or hooks its windows;
- bypasses Plutonium authentication or anti-cheat;
- elevates privileges or changes system-wide settings;
- sends data anywhere. Evidence stays on the local machine until the user shares it.

Supported game scope is Plutonium T6 Zombies only. Multiplayer is not supported and no route
targets it.

## Supply chain

Backend downloads are pinned by URL and SHA-256 in `src/plutonium_agent_toolkit/dev/backends.json`.
Setup refuses a hash mismatch and keeps the failed download for inspection. Updating a pin requires
a pull request that states the upstream release and how the hash was obtained.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting on this repository. Include the toolkit version,
the route, and steps to reproduce. You will receive an acknowledgement within seven days. Please
do not open a public issue until a fix is released.

## Supported versions

Only the latest release receives fixes during the pre-1.0 period.
