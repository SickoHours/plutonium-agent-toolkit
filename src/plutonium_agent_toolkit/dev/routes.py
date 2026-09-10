"""Registered development routes. Backends setup/doctor are available; the rest is Thread 1's contract."""
from ..core.discovery import Route, register

OWNER = "thread-1-development"

AVAILABLE = [
    Route("dev", "backends", "List pinned backend programs, licenses and whether each is installed", "inert", owner="core"),
    Route("dev", "setup", "Download pinned backends over HTTPS, verify SHA-256 and extract into the backends directory", "downloads-backends",
          owner="core", requires_windows=True,
          notes="Use --plan to list without downloading; --only to select IDs. Runs no vendor installer."),
]

PLANNED = [
    Route("gsc", "compile", "Compile a T6 GSC/CSC script with gsc-tool into a new output directory", "writes-output",
          status="planned", owner=OWNER, requires_windows=True),
    Route("gsc", "decompile", "Decompile a compiled script with gsc-tool", "writes-output",
          status="planned", owner=OWNER, requires_windows=True),
    Route("ff", "inspect", "List a fastfile's assets with OpenAssetTools Unlinker", "writes-output",
          status="planned", owner=OWNER, requires_windows=True),
    Route("ff", "link", "Link a mod fastfile from a zone source with OpenAssetTools Linker", "writes-output",
          status="planned", owner=OWNER, requires_windows=True),
    Route("ff", "extract", "Extract selected assets from a fastfile", "writes-output",
          status="planned", owner=OWNER, requires_windows=True),
    Route("project", "init", "Create a minimal T6 Zombies mod project and build recipe", "writes-output",
          status="planned", owner=OWNER),
    Route("project", "plan", "Validate a recipe and hash its declared inputs without running backends", "writes-output",
          status="planned", owner=OWNER),
    Route("project", "build", "Compile, link, read back and compare a recipe into a new job directory", "writes-output",
          status="planned", owner=OWNER, requires_windows=True),
    Route("project", "verify", "Re-hash a receipt's outputs and optionally its inputs", "writes-output",
          status="planned", owner=OWNER),
    Route("model", "convert", "Convert a model/rig/animation through Blender and the Cast add-on", "writes-output",
          status="planned", owner=OWNER, requires_windows=True),
    Route("model", "inspect", "Report bones, meshes, materials and animation ranges", "writes-output",
          status="planned", owner=OWNER, requires_windows=True),
    Route("audio", "convert", "Convert and verify audio streams with FFmpeg", "writes-output",
          status="planned", owner=OWNER, requires_windows=True),
    Route("image", "convert", "Convert DDS/IWI textures with OpenAssetTools ImageConverter", "writes-output",
          status="planned", owner=OWNER, requires_windows=True),
    Route("lua", "decompile", "Decompile LUI bytecode with CoDLuaDecompiler", "writes-output",
          status="planned", owner=OWNER, requires_windows=True),
    Route("weapon", "catalog", "Inventory a saved BO3 weapon asset library with provenance", "writes-output",
          status="planned", owner=OWNER),
    Route("weapon", "plan", "Validate a normal/PAP weapon recipe against a catalog", "writes-output",
          status="planned", owner=OWNER),
]

for route in AVAILABLE + PLANNED:
    register(route)
