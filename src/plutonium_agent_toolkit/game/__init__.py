"""Game component: Plutonium T6 Zombies control on native Windows (Thread 2).

Modules: native (Win32 console transport), engine (marker-bracketed queries),
control (transitions, receipts, launch observation), worker (bounded child),
routes (contracts). Every live route is Windows-gated and runs in one worker
under the toolkit mutex. See docs/GAME-CONTROL.md and docs/SUPPORT.md.
"""
