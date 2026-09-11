"""Which upstream program each development route runs, and with what command line.

This is data, not code: ``tools/backends_doc.py`` renders it into ``docs/BACKENDS.md`` and
``tests/test_backends.py`` checks it against ``EXECUTABLES`` in ``backends.py`` so the page cannot
name a binary the toolkit does not resolve, or omit one it does. The ``argv`` templates mirror the
adapters in ``scripts.py``, ``fastfiles.py``, ``projects.py``, ``media.py`` and ``models.py``;
``<...>`` marks a value filled in per job and ``[...]`` an optional part.
"""
from __future__ import annotations

USAGE = [
    {"routes": ["gsc compile", "gsc decompile", "project build", "module build"], "executable": "gsc", "source": "dev/scripts.py, dev/projects.py",
     "argv": ["gsc-tool", "-m", "<comp|decomp>", "-g", "<t6|iw5>", "-s", "pc", "-i", "<server|client>", "[-w <includes>]", "<script>"],
     "checks": "exit status, error lines in the log, non-empty output files"},
    {"routes": ["ff link", "project build", "module build"], "executable": "linker", "source": "dev/fastfiles.py",
     "argv": ["Linker", "--no-color", "--base-folder", "<project>", "--output-folder", "<out>/packages",
              "[--add-asset-search-path <dir>]...", "[-l <zone.ff>]...", "<zone>"],
     "checks": "a .ff was produced; every package is read back with Unlinker"},
    {"routes": ["ff inspect", "ff link", "project build", "module build", "module declare"], "executable": "unlinker", "source": "dev/fastfiles.py",
     "argv": ["Unlinker", "--no-color", "--skip-obj", "--list", "[-l <zone.ff>]...", "<fastfile>"],
     "checks": "readback log has no load failure; inventory kept as a job log"},
    {"routes": ["ff extract", "project build", "module build", "module declare"], "executable": "unlinker", "source": "dev/fastfiles.py, dev/projects.py",
     "argv": ["Unlinker", "--no-color", "--output-folder", "<out>/assets", "[--model-format <fmt>]", "[--image-format <fmt>]",
              "[--include-assets <types>]", "[-l <zone.ff>]...", "<fastfile>"],
     "checks": "files were written; project build byte-compares every rawfile against its source"},
    {"routes": ["image convert"], "executable": "image", "source": "dev/media.py",
     "argv": ["ImageConverter", "--no-color", "--<t6|t5|iw5>", "<image.dds|image.iwi>"],
     "checks": "a non-empty converted image exists beside the staged input"},
    {"routes": ["audio inspect", "audio convert"], "executable": "ffprobe", "source": "dev/media.py",
     "argv": ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", "<file>"],
     "checks": "JSON with at least one audio stream; after convert, sample rate and channels match the request"},
    {"routes": ["audio convert"], "executable": "ffmpeg", "source": "dev/media.py",
     "argv": ["ffmpeg", "-nostdin", "-v", "error", "-n", "-i", "<src>", "-map", "0:a:0", "-vn",
              "-ar", "<rate>", "-ac", "<1|2>", "-c:a", "<pcm_s16le|flac|libvorbis|libmp3lame>", "<out>/audio.<format>"],
     "checks": "non-empty output, then ffprobe verifies the stream parameters"},
    {"routes": ["lua decompile"], "executable": "lua", "source": "dev/media.py",
     "argv": ["CoDLuaDecompiler", "<out>/input.lua"],
     "checks": "a non-empty decompiled .lua exists beside the staged input"},
    {"routes": ["model inspect", "model convert", "model transform", "model rename-bones", "model retime", "model preview"],
     "executable": "blender", "source": "dev/models.py",
     "argv": ["blender", "--background", "--factory-startup", "--disable-autoexec", "--threads", "2", "--python-exit-code", "1",
              "--python", "<toolkit>/dev/blender_worker.py", "--", "<out>/request.json"],
     "checks": "the worker writes model-result.json; outputs must exist and be non-empty. The Cast add-on is loaded by path from the cast backend directory"},
]

# Programs the toolkit can download but never runs: their use is manual through the upstream GUI.
MANUAL = ["greyhound", "husky", "c2m"]

# Directory-resolved backends that are not executables (loaded by Blender from the backends dir).
ADDONS = ["cast"]
