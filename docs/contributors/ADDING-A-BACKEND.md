# Adding a backend program

1. Choose a pinned upstream release with a stable HTTPS URL per platform: the Windows x64
   archive at the top level (`url`, `sha256`, `bytes`, `strip_root`, `provides`) and, when
   upstream ships one, a Linux x64 archive under `downloads.linux` with the same keys. Archives may
   be `.zip`, `.tar.gz` or `.tar.xz`. A pure-Python add-on installs anywhere: mark it
   `platform_independent`. Do not add a `darwin` entry; macOS is not claimed.
2. Download each archive once, compute `sha256` from the file (never from memory), note the byte
   count, record the license SPDX identifier and whether the archive has a single root to strip.
   List the archive first (`tar tvf`, `unzip -l`): links are refused unless the pin says
   `"links": "copy"`, which writes relative in-archive symlinks as copies of their target.
3. Add the entry to `src/plutonium_agent_toolkit/dev/backends.json` with `optional: true` unless the
   first-run workflow needs it. `provides` lists the relative paths `doctor` checks; on Linux those
   are also the files setup marks executable, so name every binary the routes run.
4. If the routes call it, add its name to `EXECUTABLES` in `dev/backends.py` (Windows path; the
   `.exe` is dropped on Linux, so the Linux archive must use the same layout or its `provides` must
   say where the binary is).
5. Add the program and license to `NOTICE`.
6. Run `tests/test_backends.py`. Then natively on each pinned platform: `pat dev setup --only <id>
   --json` and `pat doctor --json`, or the backends tier of `tools/qualify.py`. Attach the
   sanitized output to your pull request.

Never commit the archive. Never vendor the program's files. If the upstream project has no license,
mark it `optional`, say so in the `note`, and do not make any required route depend on it.
