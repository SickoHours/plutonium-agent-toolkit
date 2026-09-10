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
]

PLANNED = [
    Route("gsc", "compile", "Compile a T6 GSC/CSC script with gsc-tool into a new output directory", "writes-output",
          status="available", owner=OWNER),
    Route("gsc", "decompile", "Decompile a compiled script with gsc-tool", "writes-output",
          status="implemented", owner=OWNER),
    Route("ff", "inspect", "List a fastfile's assets with OpenAssetTools Unlinker", "writes-output",
          status="available", owner=OWNER),
    Route("ff", "link", "Link a mod fastfile from a zone source with OpenAssetTools Linker", "writes-output",
          status="implemented", owner=OWNER),
    Route("ff", "extract", "Extract selected assets from a fastfile", "writes-output",
          status="available", owner=OWNER),
    Route("project", "init", "Create a minimal T6 Zombies mod project and build recipe", "writes-output",
          status="implemented", owner=OWNER),
    Route("project", "plan", "Validate a recipe and hash its declared inputs without running backends", "writes-output",
          status="available", owner=OWNER),
    Route("project", "build", "Compile, link, read back and compare a recipe into a new job directory", "writes-output",
          status="available", owner=OWNER),
    Route("project", "verify", "Re-hash a receipt's outputs and optionally its inputs", "writes-output",
          status="available", owner=OWNER),
    Route("model", "convert", "Convert a model/rig/animation through Blender and the Cast add-on", "writes-output",
          status="implemented", owner=OWNER),
    Route("model", "inspect", "Report bones, meshes, materials and animation ranges", "writes-output",
          status="implemented", owner=OWNER),
    Route("model", "transform", "Scale and rotate root objects, then export", "writes-output",
          status="implemented", owner=OWNER),
    Route("model", "rename-bones", "Rename bones from a JSON mapping without .001 collisions, then export", "writes-output",
          status="implemented", owner=OWNER),
    Route("model", "retime", "Rescale keyframes to a new FPS, then export", "writes-output",
          status="implemented", owner=OWNER),
    Route("model", "preview", "Render a 640px studio-lit PNG of the mesh", "writes-output",
          status="implemented", owner=OWNER),
    Route("audio", "inspect", "Probe format, streams and duration with ffprobe", "writes-output",
          status="implemented", owner=OWNER),
    Route("audio", "convert", "Convert and verify audio streams with FFmpeg", "writes-output",
          status="implemented", owner=OWNER),
    Route("image", "convert", "Convert DDS/IWI textures with OpenAssetTools ImageConverter", "writes-output",
          status="implemented", owner=OWNER),
    Route("lua", "decompile", "Decompile LUI bytecode with CoDLuaDecompiler", "writes-output",
          status="implemented", owner=OWNER),
    Route("weapon", "catalog", "Inventory a saved BO3 weapon asset library with provenance", "writes-output",
          status="implemented", owner=OWNER),
    Route("weapon", "plan", "Validate a normal/PAP weapon recipe against a catalog", "writes-output",
          status="implemented", owner=OWNER),
]

for route in AVAILABLE + PLANNED:
    register(route)
