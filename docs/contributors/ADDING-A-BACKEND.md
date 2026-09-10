# Adding a backend program

1. Choose a pinned upstream release with a stable HTTPS URL for the Windows x64 archive.
2. Download it once, compute `sha256`, note the byte count, and record the license SPDX identifier
   and whether the archive has a single root directory to strip.
3. Add the entry to `src/plutonium_agent_toolkit/dev/backends.json` with `optional: true` unless the
   first-run workflow needs it. List the relative paths in `provides` that `doctor` should check.
4. Add the program and license to `NOTICE`.
5. Run `tests/test_backends.py`. Then on Windows: `pat dev setup --only <id> --json` and
   `pat doctor --json`. Attach the sanitized output to your pull request.

Never commit the archive. Never vendor the program's files. If the upstream project has no license,
mark it `optional`, say so in the `note`, and do not make any required route depend on it.
