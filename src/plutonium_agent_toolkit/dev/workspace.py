"""``workspace init``: scaffold a modding workspace for the person and their agent, outside the
toolkit checkout.

The toolkit is installed once on a machine; the work happens somewhere else. A workspace is a
directory the agent opens as its project: an ``AGENTS.md`` that says how to operate here, the
places modules, compositions, jobs and registries go, an ignore file that keeps packages and
receipts out of version control, and a ``workspace.json`` record naming the toolkit version and
checkout that created it. Nothing is copied from the checkout; the skills already point at it.

The route creates a new directory (or fills an empty one), refuses a directory that holds
anything, refuses a location inside the toolkit checkout, and touches no game, backend or
network. ``workspace.json`` hashes every file written, so a later inspection can tell what the
route wrote from what the person changed.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .. import __version__
from ..core.envelope import now
from ..core.errors import INPUT_INVALID, OUTPUT_EXISTS, Failure

NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}\Z")
LAYOUT = ("modules", "compositions", "jobs", "receipts", "registries", "donors")

AGENTS = """# {name}: a Plutonium T6 Zombies modding workspace

You are the agent working here. The Plutonium Agent Toolkit (`pat`) is installed on this machine
from the checkout at `{checkout}`; read that checkout's `AGENTS.md` once, then `docs/knowledge/README.md`
and the playbook in `docs/playbooks/` that matches the task. `pat manifest --json` lists every route;
`pat describe <group> <action> --json` explains one. Discovery is inert.

## Layout

| Directory | What goes there |
| --- | --- |
| `modules/<id>/` | One module: `project.json` (recipe) or a seed, `module.json` (declaration), scripts, a README with the numbers table and their sources, `TEST.md` build by build |
| `compositions/<name>/` | One `composition.json` naming a base, a map and the modules it composes |
| `jobs/` | One new directory per `pat` job (`--output jobs/<module>-build-001`); never reused, never deleted to retry |
| `receipts/` | Install and test records you write by hand: which package, which profile, which map, what was seen |
| `registries/` | Registry files you host or mirror (`pat registry add` reads them from anywhere) |
| `donors/` | Sealed donor inventories and captures; hashed indexes, never edited |

Packages (`mod.ff`, sound banks), job outputs and donor bytes are ignored by `.gitignore`;
recipes, declarations, scripts and records are what version control keeps.

## Rules that travel with this workspace

- A new mod is one module built alone on a named base (`stock` or a base release's token) and
  tested as `<base>_<feature>_test` before it joins any composition.
- Every build is a new job directory with a receipt; a changed input is a new build.
- Offline verified, installed, launched, playable, captured and player-accepted are six facts;
  say which ones you have.
- Live game operations need the person's go-ahead for the specific test, and run on Windows.
- Keep paths, receipts, recordings and logs on this machine; sanitize before sharing.

## When the toolkit does not fit

Adapt it: `pat configure`, `PAT_BACKEND_<NAME>`, or an edit in the checkout with a test, then
offer to upstream it. The checkout's `docs/FOR-AGENTS.md` says how.
"""

README = """# {name}

A modding workspace for Plutonium Black Ops II Zombies, created by `pat workspace init`
(toolkit {version}). Open this directory in your coding agent; `AGENTS.md` tells it how to work here.
"""

GITIGNORE = """# Created by pat workspace init. Packages, job outputs and donor bytes stay out of version control.
/jobs/
/donors/**
!/donors/**/*.json
!/donors/**/*.md
*.ff
*.ipak
*.sabl
*.sabs
*.iwi
*.wav
*.flac
*.mkv
*.png
"""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _checkout() -> Path | None:
    candidate = Path(__file__).resolve().parents[3]
    if (candidate / "AGENTS.md").is_file() and (candidate / "skills").is_dir():
        return candidate
    return None


def init(directory: str, name: str | None = None) -> dict:
    target = Path(directory).expanduser()
    if not target.is_absolute():
        target = Path.cwd() / target
    target = target.resolve()
    label = name or target.name
    if not NAME.match(label):
        raise Failure(INPUT_INVALID, f"Workspace name must be lowercase letters, digits, - or _ (1-64): {label!r}",
                      "Pass --name, or choose a directory whose name fits.")
    checkout = _checkout()
    if checkout and (target == checkout or checkout in target.parents):
        raise Failure(INPUT_INVALID, f"{target} is inside the toolkit checkout {checkout}",
                      "A workspace is the person's own directory; the toolkit stays installed beside it.")
    if target.exists():
        if target.is_symlink() or not target.is_dir():
            raise Failure(INPUT_INVALID, f"{target} exists and is not a directory")
        if any(target.iterdir()):
            raise Failure(OUTPUT_EXISTS, f"{target} is not empty; a workspace is created only in a new or empty directory",
                          "Choose a new directory. Nothing in an existing one is overwritten.")
    else:
        target.mkdir(parents=True)
    files = {}
    checkout_text = str(checkout) if checkout else "the installed toolkit (a wheel carries no docs; clone the repository for them)"
    for rel, text in (("AGENTS.md", AGENTS.format(name=label, checkout=checkout_text)),
                      ("CLAUDE.md", "@AGENTS.md\n"),
                      ("README.md", README.format(name=label, version=__version__)),
                      (".gitignore", GITIGNORE)):
        data = text.encode("utf-8")
        (target / rel).write_bytes(data)
        files[rel] = _sha(data)
    for rel in LAYOUT:
        (target / rel).mkdir()
        keep = target / rel / ".gitkeep"
        keep.write_bytes(b"")
        files[f"{rel}/.gitkeep"] = _sha(b"")
    record = {"schema": 1, "name": label, "created": now(), "toolkit_version": __version__,
              "toolkit_checkout": str(checkout) if checkout else None, "files": files,
              "verification": "Directories and files written; nothing copied, downloaded, launched or installed."}
    (target / "workspace.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return {"workspace": str(target), "name": label, "toolkit_checkout": record["toolkit_checkout"],
            "files": sorted(files), "record": str(target / "workspace.json"), "game_touched": False,
            "next": ["open the directory in your coding agent", "pat dev setup --json (backends, once per machine)",
                     "pat project init --name <id> --output modules/<id>", "pat module build compositions/<name>/composition.json --output jobs/<name>-build-001"]}
