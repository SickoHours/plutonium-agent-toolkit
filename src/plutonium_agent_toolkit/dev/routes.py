"""Registered development (file-tool) routes.

These routes run on Windows and Linux: they drive pinned upstream backends as
ordinary subprocesses and touch no running game. ``status="available"`` means a
native receipt is linked in docs/SUPPORT.md. None of these routes is
platform-gated; a backend that is missing for the current OS reports
``backend_unavailable`` with how to supply it via ``pat dev setup`` or a
``PAT_BACKEND_<NAME>`` override. macOS is untested and not claimed.
"""
from ..core.discovery import Route, register

OWNER = "thread-1-development"

AVAILABLE = [
    Route("dev", "backends", "List pinned backend programs, licenses and whether each is installed", "inert", owner="core"),
    Route("dev", "setup", "Download pinned backends over HTTPS, verify SHA-256 and extract into the backends directory", "downloads-backends",
          owner="core",
          notes="Use --plan to list without downloading; --only to select IDs. Runs no vendor installer. "
                "Pinned downloads are per-platform; where a platform has no pin, supply the tool with PAT_BACKEND_<NAME>."),
    Route("dev", "install-skills", "Copy the toolkit's skills into the skills directories of the coding-agent harnesses found on this machine, with a receipt", "writes-config",
          status="available", owner="core",
          notes="Arguments: [--plan] [--only claude codex gemini opencode cursor hermes agents]... [--home <dir>] [--source <checkout>]. "
                "Detects a harness by its home directory; launches nothing. Writes absent files and files it wrote before; refuses "
                "any other existing file, any link below the resolved home and any oversized file with output_exists after writing the rest. "
                "Record and receipts under <toolkit home>/skills/."),
]

PLANNED = [
    Route("gsc", "compile", "Compile a T6 GSC/CSC script with gsc-tool into a new output directory", "writes-output",
          status="available", owner=OWNER),
    Route("gsc", "decompile", "Decompile a compiled script with gsc-tool", "writes-output",
          status="available", owner=OWNER),
    Route("ff", "inspect", "List a fastfile's assets with OpenAssetTools Unlinker", "writes-output",
          status="available", owner=OWNER),
    Route("ff", "link", "Link a mod fastfile from a zone source with OpenAssetTools Linker", "writes-output",
          status="implemented", owner=OWNER),
    Route("ff", "extract", "Extract selected assets from a fastfile", "writes-output",
          status="available", owner=OWNER),
    Route("project", "init", "Create a minimal T6 Zombies mod project and build recipe", "writes-output",
          status="available", owner=OWNER),
    Route("project", "plan", "Validate a recipe and hash its declared inputs without running backends", "writes-output",
          status="available", owner=OWNER),
    Route("project", "build", "Compile, link, read back and compare a recipe into a new job directory", "writes-output",
          status="available", owner=OWNER),
    Route("project", "verify", "Re-hash a receipt's outputs and optionally its inputs", "writes-output",
          status="available", owner=OWNER),
    Route("model", "convert", "Convert a model/rig/animation through Blender and the Cast add-on", "writes-output",
          status="available", owner=OWNER),
    Route("model", "inspect", "Report bones, meshes, materials and animation ranges", "writes-output",
          status="available", owner=OWNER),
    Route("model", "transform", "Scale and rotate root objects, then export", "writes-output",
          status="available", owner=OWNER),
    Route("model", "rename-bones", "Rename bones from a JSON mapping without .001 collisions, then export", "writes-output",
          status="available", owner=OWNER),
    Route("model", "retime", "Rescale keyframes to a new FPS, then export", "writes-output",
          status="available", owner=OWNER),
    Route("model", "preview", "Render a 640px studio-lit PNG of the mesh", "writes-output",
          status="available", owner=OWNER),
    Route("audio", "inspect", "Probe format, streams and duration with ffprobe", "writes-output",
          status="available", owner=OWNER),
    Route("audio", "convert", "Convert and verify audio streams with FFmpeg", "writes-output",
          status="available", owner=OWNER),
    Route("image", "convert", "Convert DDS/IWI textures with OpenAssetTools ImageConverter", "writes-output",
          status="implemented", owner=OWNER),
    Route("lua", "decompile", "Decompile LUI bytecode with CoDLuaDecompiler", "writes-output",
          status="implemented", owner=OWNER),
    Route("weapon", "catalog", "Inventory a saved BO3 weapon asset library with provenance", "writes-output",
          status="implemented", owner=OWNER),
    Route("weapon", "plan", "Validate a normal/PAP weapon recipe against a catalog", "writes-output",
          status="implemented", owner=OWNER),
    Route("module", "plan", "Resolve a composition of declared modules (dependency order, conflicts, base and map fit, "
          "resource budget), list every collision as a decision, and hash every input without running a backend", "writes-output",
          status="available", owner=OWNER,
          notes="Formats: docs/MODULES.md. A module.json beside each recipe or seed; a composition.json naming base, map, members (modules, nested packs, pinned references), decisions and loads."),
    Route("module", "declare", "Read a prebuilt mod.ff back with OpenAssetTools and draft its seed manifest and module declaration", "writes-output",
          status="available", owner=OWNER,
          notes="Argument: <path to mod.ff> [--load base.ff]... [--id --title --category --base --map]. Writes seed.json and a draft module.json; the draft guesses id and category, never bases or maps."),
    Route("module", "fetch", "Download a published module or pack at its exact commit (owner/id@commit through a registry, or a GitHub URL) into a new directory with a receipt", "downloads-source",
          status="implemented", owner=OWNER,
          notes="Argument: <owner>/<id>@<40 hex> or https://github.com/<owner>/<repo>@<40 hex> [--path <dir>]. GitHub only, HTTPS tarball, no git, no token. The declaration must name the same repository and commit when it names any."),
    Route("dev", "builtin", "Fetch the built-in modules and packs the toolkit's own registry lists, at their pinned commits, into the toolkit home; a rerun verifies them", "downloads-source",
          status="available", owner="core",
          notes="Arguments: [--plan] [--only <owner/id>]... One HTTPS snapshot per repository and commit, hashed and extracted with the archive "
                "safety checks; the entry directories (and a pack's members and loads) are laid out under <toolkit home>/modules/builtin/<owner>/<repo>/<commit>/ "
                "with a receipt per entry. A changed tree is refused with artifact_changed, never overwritten. --plan touches no network. Nothing is installed into the game."),
    Route("registry", "add", "Record a registry file (local path or https URL): validated and copied under the toolkit home", "writes-config",
          status="implemented", owner=OWNER, notes="Argument: <path or https URL to registry.json>. Format: docs/REGISTRY.md."),
    Route("registry", "list", "List the registries on this machine: the built-in one that ships with the toolkit, then the ones you added", "inert", status="implemented", owner=OWNER),
    Route("registry", "search", "Search the built-in and recorded registries by words, category, kind, tag, base, map or origin", "inert",
          status="implemented", owner=OWNER, notes="Arguments: [words]... [--category --kind --tag --base --map --entry-kind --origin builtin|added]. Reads local copies only; a built-in hit carries builtin_dir once dev builtin fetched it."),
    Route("registry", "show", "Show every listing of one entry name with its fetch command", "inert",
          status="implemented", owner=OWNER, notes="Argument: <owner>/<id>."),
    Route("registry", "baseline", "Static, deterministic check of a module or composition directory before it is listed: "
          "executable headers, download-and-execute, links and path escapes, unpinned archives, declaration mismatches, "
          "and the capabilities a reviewer should know about", "writes-output",
          status="available", owner=OWNER,
          notes="Argument: <directory> [--repository <https url>] [--commit <40 hex>]. Reads every eligible file and nothing else "
                "(.git, links and unreadable entries are listed, not read): nothing in the tree is executed, no backend, no network, no model. Policy version 1, enforcement selective: native-plugin, "
                "download-and-execute and path-escape block; everything else is reported for review. Outcomes passed, "
                "review-required, needs-fixes, incomplete (unreadable files fail closed). Writes baseline.json. Not a security "
                "audit, certification, warranty or endorsement. Rules: docs/REGISTRY.md."),
    Route("module", "build", "Compile every module's scripts, stage every asset, link one mod.ff, read it back and compare every rawfile",
          "writes-output", status="available", owner=OWNER,
          notes="Same backends and readback as project build; the composition's fit and budget come from declarations, not from the game."),
]

for route in AVAILABLE + PLANNED:
    register(route)
