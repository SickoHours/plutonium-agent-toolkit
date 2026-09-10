# Fake backends for tests

`tests/fakes/` holds tiny Python stand-ins for gsc-tool, Linker and Unlinker. They let the
entire `project build` pipeline (compile, stage, link, read back, byte-compare, verify) run as a
unit test on any platform in under a second. They are not emulators: each reproduces only the
command-line shape and the failure modes our adapters must handle.

| Fake | Behaviour it reproduces |
| --- | --- |
| `fake_gsc.py` | Writes `compiled/<name>`; prints an error line and **exits zero** when the source contains `FAIL_COMPILE`; exits 3 on `CRASH` |
| `fake_linker.py` | Reads `zone_source/<zone>.zone`, packs listed rawfiles from `raw/` into `<zone>.ff` |
| `fake_unlinker.py` | `--list` prints the inventory; `--output-folder` extracts rawfiles; fails on a malformed fastfile |

Point the adapters at them with `PAT_BACKEND_GSC`, `PAT_BACKEND_LINKER` and `PAT_BACKEND_UNLINKER`
(absolute paths; a `.py` runs through the current interpreter). Set `PAT_DEV_UNGATED=1` to bypass
the Windows gate **in tests only**. Neither variable is documented for users.

A passing fake-backend test proves the adapter's control flow and receipt handling. It proves
nothing about the real tool. The native receipt in `docs/SUPPORT.md` does that.
