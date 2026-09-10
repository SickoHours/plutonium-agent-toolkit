# Contributing

Contributions are welcome from humans and from development agents working on a human's behalf.
Both follow the same path. The toolkit is Windows-only for this release; unit tests and
documentation work run anywhere.

You do not need anyone's permission to change this toolkit to fit your machine or your agent.
Fork it, edit it, run the three checks below, keep `docs/SUPPORT.md` honest.
[docs/FOR-AGENTS.md](docs/FOR-AGENTS.md) maps the common machine differences to the code that
handles them. Sending the change back is welcome and optional.

## Set up a development environment

```sh
git clone https://github.com/SickoHours/plutonium-agent-toolkit
cd plutonium-agent-toolkit
python -m venv .venv
.venv\Scripts\activate           # PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e .
python -m unittest discover -s tests -v
```

Set `PAT_HOME` to a scratch directory while developing so you never touch a real installation.

## Make a change

1. Open or pick an issue. State the route, the platform and the evidence you intend to produce.
2. Branch from `main`: `git switch -c <topic>`.
3. Change code, tests and docs together. Add an entry under `## [Unreleased]` in `CHANGELOG.md`.
4. Run the three local checks:
   ```sh
   python -m unittest discover -s tests -v
   python tools/private_scan.py
   python tools/release_check.py
   ```
5. If the change touches a backend, the game or capture, run it on a native Windows host and
   attach a sanitized receipt (argv, exit status, versions, hashes). Wine, WSL and CI cannot
   stand in for that host.
6. Open a pull request using the template. Fill in every section honestly, including
   "Not verified".

## What reviewers check

- Tests cover the change, including the failure paths (missing input, busy, timeout, uncertain).
- `docs/SUPPORT.md` still tells the truth about every route the change touches.
- No new escape hatch: no raw console strings, memory access, arbitrary function calls.
- No personal paths, credentials, recordings, logs or game assets. `tools/private_scan.py` is clean.
- Exit codes and `error_code` values follow `core/errors.py`. New codes are added, not repurposed.
- Every job writes a receipt into a new directory and refuses to overwrite.

## Extension recipes

Step-by-step guides for the common contributions live in [docs/contributors/](docs/contributors/):

- Adding a CLI route
- Adding a backend program
- Adding a map recipe
- Adding a test scenario
- Recording a qualification receipt

## Releasing (maintainers)

```sh
python tools/bump_version.py 0.1.0b1        # updates __init__, pyproject, SUPPORT.md, promotes Unreleased
python tools/release_check.py               # prints the tag to use
git commit -am "release: 0.1.0b1" && git push
git tag v0.1.0-beta.1 && git push origin v0.1.0-beta.1
```

The tag push runs the release workflow. It refuses a tag that disagrees with the version,
changelog or support matrix, so a mismatched release cannot ship.

## Reporting bugs

Use the bug template. Include `pat version --json`, the command's full JSON output and exit
status, your Windows and Plutonium versions, and what you expected. Redact your username and any
paths you do not want public. Never attach recordings or logs that show other people.

## Security

See [SECURITY.md](SECURITY.md). Do not open public issues for vulnerabilities.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).

## License

By contributing you agree that your contribution is licensed under Apache-2.0.
