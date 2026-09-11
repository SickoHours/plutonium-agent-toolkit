#!/usr/bin/env python3
"""Run the native qualification tiers on Windows or Linux and write sanitized receipts.

    python tools/qualify.py --tier offline  --output docs/receipts
    python tools/qualify.py --tier backends --output docs/receipts [--media]
    python tools/qualify.py --tier game     --output docs/receipts --collect     (Windows only)
    python tools/qualify.py --redact-existing docs/receipts/<version>/<receipt>.json

Tiers 1 and 2 run commands themselves on the host they are started on; the receipt names
that host's OS (``environment.os``) and whether it is native (not Wine, not WSL). Receipts are
written as ``<platform>-tier<N>-<name>.json``. Tier 3 is Windows-only because game control
uses the Win32 console; it never touches the game itself. With --collect it reads the
toolkit's state files after the human-authorized commands were run by hand and folds them
into a receipt. Every receipt is redacted before writing: any drive-letter Users path and any
/home/<name> path for any account, the username, machine name, toolkit home, work directory
and 32-hex request/load/job IDs are replaced, and private-scan hit excerpts are dropped.
--redact-existing reapplies the current rules to a committed receipt in place.
``tools/qualify_windows.py`` is a compatibility shim that runs this file.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from plutonium_agent_toolkit import __version__  # noqa: E402

PAT = [sys.executable, "-m", "plutonium_agent_toolkit"]


# ----- redaction --------------------------------------------------------------------------

# Any drive letter, any account, either slash style, single or JSON-escaped separators. This
# does not depend on USERPROFILE, so a truncated excerpt such as C:\Users\m, another account's
# profile or another drive's Users folder cannot survive (maintainer finding on the first
# qualification pull request). The account segment runs to the next separator, quote or line
# end, so names containing spaces ("Jane Doe") are covered too; over-redacting prose that
# follows a bare path is the safe direction.
USERS_PATH = re.compile(r"(?i)[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}[^\\/\"\r\n\t]*")
# Any POSIX home directory for any account: /home/<name>, /Users/<name>, /root.
HOME_PATH = re.compile(r"(?<![A-Za-z0-9_])/(?:home|Users)/[^/\"\r\n\t]+|(?<![A-Za-z0-9_])/root(?=/|\"|$)")


def redactor(extra_paths=()):
    user = getpass.getuser()
    host = socket.gethostname()
    profile = os.environ.get("USERPROFILE", "")
    patterns = []
    # Known private locations first (toolkit home, work directory), in every slash style.
    for label, raw in extra_paths:
        for variant in {raw, raw.replace("\\", "/"), raw.replace("\\", "\\\\")}:
            if variant:
                patterns.append((re.compile(re.escape(variant), re.I), f"<{label}>"))
    # Any qualification work directory, not only this run's: Tier 1's configure step stores the
    # fake storage path in config.json, and Tier 2 reads it back through doctor.
    temp = tempfile.gettempdir()
    for variant in {temp, temp.replace("\\", "/"), temp.replace("\\", "\\\\")}:
        patterns.append((re.compile(re.escape(variant) + r"[\\/]{1,2}pat-qualify-home-[^\\/\"\r\n\t]*", re.I), "<pat-home>"))
        patterns.append((re.compile(re.escape(variant) + r"[\\/]{1,2}pat-qualify-[^\\/\"\r\n\t]*", re.I), "<work>"))
    patterns.append((USERS_PATH, "<userprofile>"))
    patterns.append((HOME_PATH, "<userprofile>"))
    if profile:
        patterns.append((re.compile(re.escape(profile), re.I), "<userprofile>"))
        patterns.append((re.compile(re.escape(profile.replace("\\", "\\\\")), re.I), "<userprofile>"))
        patterns.append((re.compile(re.escape(profile.replace("\\", "/")), re.I), "<userprofile>"))
    if user:
        patterns.append((re.compile(r"(?i)(?<![A-Za-z0-9])" + re.escape(user) + r"(?![A-Za-z0-9])"), "<user>"))
    if host:
        patterns.append((re.compile(r"(?i)(?<![A-Za-z0-9])" + re.escape(host) + r"(?![A-Za-z0-9])"), "<host>"))
    # request/load/job IDs are private; git SHAs (40 hex) are not and must survive intact.
    patterns.append((re.compile(r"(?<![0-9a-f])[a-f0-9]{32}(?![0-9a-f])"), "<id>"))

    def redact(value):
        if isinstance(value, str):
            for pattern, replacement in patterns:
                value = pattern.sub(replacement, value)
            return value
        if isinstance(value, list):
            return [redact(v) for v in value]
        if isinstance(value, dict):
            return {redact(k): redact(v) for k, v in value.items()}
        return value
    return redact


# ----- running commands --------------------------------------------------------------------

NESTED_ENV = "PAT_QUALIFY_NESTED"


def child_env():
    """Children import the checked-out source even if `pip install -e .` was skipped.

    NESTED_ENV tells tests/test_qualify_tool.py not to launch this script again from
    inside the unit-test step; without it the offline tier would recurse forever."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env[NESTED_ENV] = "1"
    return env


def run(argv, timeout=900, cwd=None):
    started = time.monotonic()
    shown = argv[len(PAT):] if argv[:len(PAT)] == PAT else argv
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=child_env())
    except subprocess.TimeoutExpired as exc:
        return {"argv": shown, "exit_code": 124, "elapsed_seconds": round(time.monotonic() - started, 3), "json": None,
                "stdout_head": str(exc.stdout or "")[:2000], "stderr_head": f"timed out after {timeout}s; " + str(exc.stderr or "")[:1800]}
    except OSError as exc:
        return {"argv": shown, "exit_code": 127, "elapsed_seconds": round(time.monotonic() - started, 3), "json": None,
                "stdout_head": None, "stderr_head": f"could not start: {exc}"}
    elapsed = round(time.monotonic() - started, 3)
    try:
        payload = json.loads(proc.stdout) if proc.stdout.strip() else None
    except ValueError:
        payload = None
    return {"argv": shown, "exit_code": proc.returncode,
            "elapsed_seconds": elapsed, "json": payload,
            "stdout_head": None if payload is not None else proc.stdout[:2000],
            "stderr_head": proc.stderr[:2000] if proc.stderr else ""}


def step(receipt, name, argv, expect_ok=True, timeout=900, cwd=None):
    row = run(argv, timeout=timeout, cwd=cwd)
    ok = (row["exit_code"] == 0 and bool(row["json"]) and row["json"].get("ok") is True) if expect_ok \
        else (row["exit_code"] != 0 and bool(row["json"]) and row["json"].get("ok") is False)
    row.update(name=name, passed=ok, expected="success" if expect_ok else "structured failure")
    receipt["steps"].append(row)
    print(("PASS " if ok else "FAIL ") + name, flush=True)
    return row


PLATFORM_TOKENS = {"Windows": "windows", "Linux": "linux", "Darwin": "darwin"}
NATIVE_PLATFORMS = ("windows", "linux")


def platform_token() -> str:
    system = platform.system()
    return PLATFORM_TOKENS.get(system, system.lower())


def os_release() -> dict:
    """PRETTY_NAME, ID, ID_LIKE and VERSION_ID from /etc/os-release, when present."""
    rows = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                key, _, value = line.partition("=")
                if key in ("PRETTY_NAME", "ID", "ID_LIKE", "VERSION_ID"):
                    rows[key.lower()] = value.strip().strip('"')
    except OSError:
        pass
    return rows


CI_MARKERS = ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "BUILDKITE", "TF_BUILD", "CIRCLECI", "JENKINS_URL")


def ci_runner() -> str | None:
    """The CI variable that identifies this process as a hosted runner, or None."""
    for name in CI_MARKERS:
        value = os.environ.get(name, "")
        if value and value.lower() not in ("0", "false", "no"):
            return name
    return None


def compatibility_layer() -> str | None:
    """wine / wsl when this interpreter is not running on the OS it reports, else None."""
    if os.name == "nt":
        try:
            import ctypes

            if hasattr(ctypes.WinDLL("ntdll"), "wine_get_version"):  # type: ignore[attr-defined]
                return "wine"
        except (OSError, AttributeError):
            pass
        return None
    if platform.system() == "Linux":
        try:
            text = (platform.release() + " " + Path("/proc/version").read_text(encoding="utf-8")).lower()
        except OSError:
            text = platform.release().lower()
        if "microsoft" in text or "wsl" in text:
            return "wsl"
    return None


def os_identity() -> str:
    """One human-readable line naming the host OS for docs/SUPPORT.md."""
    if os.name == "nt":
        return f"Windows {platform.release()} build {platform.win32_ver()[1]}"
    rel = os_release()
    if platform.system() == "Linux":
        base = rel.get("id_like") or rel.get("id") or "linux"
        name = rel.get("pretty_name") or rel.get("id") or "Linux"
        version = rel.get("version_id")
        label = f"{name} {version}" if version and version not in name else name
        return f"{base.split()[0].title()} Linux ({label})" if base != "linux" else label
    return platform.platform()


def environment():
    token = platform_token()
    layer = compatibility_layer()
    info = {"toolkit_version": __version__, "python": sys.version.split()[0], "platform": platform.platform(),
            "machine": platform.machine(), "platform_token": token, "os": os_identity(),
            "native_windows": token == "windows" and layer is None,
            "native_linux": token == "linux" and layer is None,
            "compatibility_layer": layer,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if os.name == "nt":
        try:
            info["windows_build"] = platform.win32_ver()[1]
        except Exception:  # noqa: BLE001
            pass
    else:
        info["os_release"] = os_release()
    try:
        info["git_head"] = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
        info["git_dirty"] = bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=ROOT).stdout.strip())
    except OSError:
        pass
    return info


def new_receipt(tier):
    return {"schema_version": 1, "tier": tier, "environment": environment(), "steps": [], "notes": []}


def supersede(path: Path) -> Path | None:
    """Move an existing receipt aside instead of overwriting it.

    A rerun after a fix must keep the failed attempt (docs/contributors/RECORDING-A-RECEIPT.md)."""
    if not path.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    aside = path.with_name(f"{path.stem}.superseded-{stamp}{path.suffix}")
    n = 1
    while aside.exists():
        n += 1
        aside = path.with_name(f"{path.stem}.superseded-{stamp}-{n}{path.suffix}")
    path.rename(aside)
    return aside


def strip_excerpts(value):
    """Drop ``excerpt`` from embedded private_scan hits: it quotes the offending text itself.

    ``file``, ``line`` and ``pattern`` are enough for a receipt."""
    if isinstance(value, list):
        return [strip_excerpts(v) for v in value]
    if isinstance(value, dict):
        if "excerpt" in value and "pattern" in value and "file" in value:
            value = {k: v for k, v in value.items() if k != "excerpt"}
        return {k: strip_excerpts(v) for k, v in value.items()}
    return value


def sanitize(receipt, redact):
    """Everything a receipt goes through before it is written or rewritten."""
    return redact(strip_excerpts(receipt))


def redact_existing(path: Path, redact) -> bool:
    """Reapply the current redaction rules to a committed receipt in place.

    Returns True if the file changed. A note records the rewrite; an already-clean file is left
    untouched so the operation is idempotent."""
    original = path.read_text(encoding="utf-8")
    data = json.loads(original)
    cleaned = sanitize(data, redact)
    if cleaned == data:
        return False
    cleaned.setdefault("notes", []).append({"re_redacted": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                            "by": "tools/qualify.py --redact-existing"})
    path.write_text(json.dumps(cleaned, indent=2) + "\n", encoding="utf-8")
    return True


def finish(receipt, output: Path, name: str, redact):
    receipt["passed"] = all(s["passed"] for s in receipt["steps"])
    observations = receipt.get("human_observations")
    if observations is not None:
        # Tier 3 needs the human facts the script cannot know; a receipt with any of them
        # unanswered or false is not a pass, whatever the state files say.
        required = ("main_menu_reached", "town_spawn_playable", "hello_zm_line_visible_after_spawn", "quit_exited_cleanly")
        receipt["passed"] = receipt["passed"] and all(observations.get(key) is True for key in required)
    receipt["summary"] = {"steps": len(receipt["steps"]), "passed": sum(s["passed"] for s in receipt["steps"]),
                          "failed": [s["name"] for s in receipt["steps"] if not s["passed"]]}
    output.mkdir(parents=True, exist_ok=True)
    path = output / name
    previous = supersede(path)
    if previous:
        receipt["notes"].append({"superseded": previous.name})
    path.write_text(json.dumps(sanitize(receipt, redact), indent=2) + "\n", encoding="utf-8")
    print(f"\n{'PASSED' if receipt['passed'] else 'FAILED'}: {receipt['summary']['passed']}/{receipt['summary']['steps']} steps -> {path}")
    return receipt["passed"]


# ----- tiers ------------------------------------------------------------------------------

def tier_offline(receipt, home: Path, work: Path):
    env_note = f"PAT_HOME={home}"
    receipt["notes"].append(env_note)
    tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], capture_output=True, text=True, cwd=ROOT, env=child_env())
    receipt["steps"].append({"name": "unit tests", "argv": ["python", "-m", "unittest", "discover", "-s", "tests"],
                             "exit_code": tests.returncode, "passed": tests.returncode == 0,
                             "stderr_head": tests.stderr[-2000:], "expected": "success"})
    print(("PASS " if tests.returncode == 0 else "FAIL ") + "unit tests", flush=True)
    step(receipt, "version", PAT + ["version", "--json"])
    step(receipt, "manifest", PAT + ["manifest", "--json"])
    step(receipt, "describe game load-map", PAT + ["describe", "game", "load-map", "--json"])
    step(receipt, "doctor before configure", PAT + ["doctor", "--json"])
    storage = work / "fake-storage" / "t6"
    (storage / "mods").mkdir(parents=True)
    step(receipt, "configure fake storage", PAT + ["configure", "--plutonium-storage-t6", str(storage), "--json"])
    step(receipt, "game mods on empty storage", PAT + ["game", "mods", "--json"])
    step(receipt, "dev setup --plan", PAT + ["dev", "setup", "--plan", "--json"])
    step(receipt, "project plan hello-zm", PAT + ["project", "plan", str(ROOT / "examples/hello-zm/project.json"),
                                                  "--output", str(work / "plan-hello"), "--json"])
    step(receipt, "output_exists refusal", PAT + ["project", "plan", str(ROOT / "examples/hello-zm/project.json"),
                                                   "--output", str(work / "plan-hello"), "--json"], expect_ok=False)
    init = step(receipt, "project init", PAT + ["project", "init", "--name", "qualify_init", "--output", str(work / "init"), "--json"])
    if init["passed"]:
        step(receipt, "project plan the init recipe", PAT + ["project", "plan", str(work / "init" / "project.json"),
                                                            "--output", str(work / "init-plan"), "--json"])
    step(receipt, "planned route refuses", PAT + ["capture", "start"], expect_ok=False)
    step(receipt, "private scan", [sys.executable, str(ROOT / "tools/private_scan.py")])
    step(receipt, "release check", [sys.executable, str(ROOT / "tools/release_check.py")])


def stage_for_tier3(mod_ff: Path, home: Path) -> Path | None:
    """Copy the built mod.ff to <home>/qualify/hello_zm/mod.ff without renaming it.

    A T6 fastfile is bound to its file name (the zone name keys its compressed streams), so a
    build that did not produce mod.ff cannot be staged by renaming: OpenAssetTools cannot read
    the copy and the Plutonium client hung loading one. Refuse instead of corrupting it."""
    if mod_ff.name != "mod.ff":
        return None
    staged_dir = home / "qualify" / "hello_zm"
    staged_dir.mkdir(parents=True, exist_ok=True)
    staged = staged_dir / "mod.ff"
    shutil.copyfile(mod_ff, staged)
    return staged


def write_tone(path: Path, seconds: float = 1.0, rate: int = 44100) -> None:
    """A 440 Hz stereo 16-bit WAV written with the standard library; no backend needed."""
    import math
    import struct
    import wave

    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(rate * seconds)):
            v = int(12000 * math.sin(2 * math.pi * 440 * i / rate))
            frames += struct.pack("<hh", v, v)
        w.writeframes(bytes(frames))


CUBE_OBJ = """o cube
v -1 -1 -1
v 1 -1 -1
v 1 1 -1
v -1 1 -1
v -1 -1 1
v 1 -1 1
v 1 1 1
v -1 1 1
f 1 2 3 4
f 5 8 7 6
f 1 5 6 2
f 2 6 7 3
f 3 7 8 4
f 5 1 4 8
"""


MAKE_RIG = """import bpy, sys
out = sys.argv[sys.argv.index('--') + 1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.object.armature_add(enter_editmode=True)
arm = bpy.context.object
arm.name = 'rig'
eb = arm.data.edit_bones
root = eb[0]; root.name = 'root'; root.head = (0, 0, 0); root.tail = (0, 0, 1)
child = eb.new('tag_weapon'); child.head = (0, 0, 1); child.tail = (0, 0, 2); child.parent = root
bpy.ops.object.mode_set(mode='OBJECT')
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 1))
cube = bpy.context.object; cube.name = 'body'
cube.parent = arm
cube.modifiers.new('skin', 'ARMATURE').object = arm
cube.vertex_groups.new(name='root').add(list(range(len(cube.data.vertices))), 1.0, 'REPLACE')
arm.animation_data_create()
arm.animation_data.action = bpy.data.actions.new('swing')
scene = bpy.context.scene
scene.frame_start = 1; scene.frame_end = 10; scene.render.fps = 30
pb = arm.pose.bones['tag_weapon']
pb.rotation_mode = 'XYZ'  # pose bones default to quaternion; Euler keys are inert without this
for frame, rot in ((1, 0.0), (10, 0.5)):
    pb.rotation_euler = (rot, 0, 0); pb.keyframe_insert('rotation_euler', frame=frame)
bpy.ops.wm.save_as_mainfile(filepath=out)
"""


def make_rig(work: Path) -> tuple[Path | None, str]:
    """A two-bone rigged, skinned, animated .blend made by the installed Blender itself.

    A .blend is the one input on which every model action is legal: glTF import adds NLA tracks
    and root animation, which transform and retime refuse by design. Returns the fixture path
    and a diagnostic; on failure the path is None and the diagnostic says why (kept in the
    receipt so a host failure can be classified)."""
    script = work / "make_rig.py"
    script.write_text(MAKE_RIG, encoding="utf-8")
    rig = work / "rig.blend"
    try:
        from plutonium_agent_toolkit.dev.backends import executable
        argv = executable("blender")
    except Exception as exc:  # noqa: BLE001  (backend_unavailable surfaces as a failed step)
        return None, f"blender is not resolvable: {exc}"[:2000]
    try:
        proc = subprocess.run([*argv, "--background", "--factory-startup", "--python", str(script), "--", str(rig)],
                              capture_output=True, text=True, timeout=600, env=child_env())
    except subprocess.TimeoutExpired as exc:
        return None, ("timed out after 600s; " + str(exc.stdout or "")[-1000:] + str(exc.stderr or "")[-800:])[:2000]
    except OSError as exc:
        return None, f"could not start blender: {exc}"[:2000]
    (work / "make_rig.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0 or not rig.is_file():
        return None, (f"exit {proc.returncode}; rig.blend {'present' if rig.is_file() else 'absent'}; "
                      + (proc.stdout + proc.stderr)[-1800:])[:2000]
    return rig, f"exit 0; {rig.stat().st_size} bytes"


def tier_media(receipt, work: Path):
    """Optional Tier 2 extension: real FFmpeg and Blender+Cast on synthetic inputs.

    Downloads are large (FFmpeg about 130 MB, Blender about 380 MB, unpacked 1.7 GB on Linux
    because its library symlinks are written as copies). Run it only when that is acceptable."""
    step(receipt, "dev setup ffmpeg blender cast", PAT + ["dev", "setup", "--only", "ffmpeg", "blender", "cast", "--json"], timeout=1800)
    tone = work / "tone.wav"
    write_tone(tone)
    step(receipt, "audio inspect tone.wav", PAT + ["audio", "inspect", str(tone), "--output", str(work / "audio-inspect"), "--json"])
    step(receipt, "audio convert tone.wav 48 kHz mono", PAT + ["audio", "convert", str(tone), "--format", "wav", "--rate", "48000",
                                                            "--channels", "1", "--output", str(work / "audio-convert"), "--json"])
    cube = work / "cube.obj"
    cube.write_text(CUBE_OBJ, encoding="utf-8")
    step(receipt, "model inspect cube.obj", PAT + ["model", "inspect", str(cube), "--output", str(work / "model-inspect"), "--timeout", "600", "--json"], timeout=900)
    step(receipt, "model convert cube.obj to cast", PAT + ["model", "convert", str(cube), "--format", "cast", "--output", str(work / "model-convert"),
                                                       "--timeout", "600", "--json"], timeout=900)
    rig, diagnostic = make_rig(work)
    receipt["steps"].append({"name": "make rigged fixture with the installed Blender", "passed": rig is not None,
                             "expected": "rig.blend written", "stderr_head": diagnostic})
    print(("PASS " if rig else "FAIL ") + "make rigged fixture with the installed Blender", flush=True)
    if rig is None:
        return
    mapping = work / "bones.json"
    mapping.write_text('{"tag_weapon": "tag_weapon_renamed"}\n', encoding="utf-8")
    common = ["--timeout", "600", "--json"]
    step(receipt, "model inspect rig.blend (armature, skin, action)", PAT + ["model", "inspect", str(rig), "--output", str(work / "rig-inspect"), *common], timeout=900)
    step(receipt, "model rename-bones rig.blend", PAT + ["model", "rename-bones", str(rig), "--mapping", str(mapping), "--format", "blend",
                                                        "--output", str(work / "rig-rename"), *common], timeout=900)
    retime = step(receipt, "model retime rig.blend 30 to 60 fps", PAT + ["model", "retime", str(rig), "--fps", "60", "--format", "blend",
                                                                        "--output", str(work / "rig-retime"), *common], timeout=900)
    if retime["passed"]:
        after = retime["json"]["result"]["after"]
        frames = [a["frame_range"] for a in after.get("animations", [])]
        ok = after.get("fps") == 60 and frames and all(list(r) == [2, 20] for r in frames)
        receipt["steps"].append({"name": "retime doubled the frame range", "passed": bool(ok), "expected": "fps 60, swing 2..20",
                                 **({} if ok else {"stderr_head": f"fps {after.get('fps')}, ranges {frames}"})})
        print(("PASS " if ok else "FAIL ") + "retime doubled the frame range", flush=True)
    step(receipt, "model transform rig.blend scale 2", PAT + ["model", "transform", str(rig), "--scale", "2", "--format", "blend",
                                                             "--output", str(work / "rig-transform"), *common], timeout=900)
    step(receipt, "model preview rig.blend", PAT + ["model", "preview", str(rig), "--output", str(work / "rig-preview"), *common], timeout=900)


def tier_backends(receipt, home: Path, work: Path, media: bool = False):
    step(receipt, "dev setup gsc oat", PAT + ["dev", "setup", "--only", "gsc", "oat", "--json"], timeout=1800)
    step(receipt, "doctor after setup", PAT + ["doctor", "--json"])
    step(receipt, "dev setup rerun verifies", PAT + ["dev", "setup", "--only", "gsc", "oat", "--json"], timeout=600)
    recipe = ROOT / "examples/hello-zm/project.json"
    step(receipt, "project plan hello-zm", PAT + ["project", "plan", str(recipe), "--output", str(work / "plan"), "--json"])
    build = step(receipt, "project build hello-zm (real gsc-tool + OAT)", PAT + ["project", "build", str(recipe), "--output", str(work / "build"), "--json"], timeout=600)
    if build["passed"]:
        result = build["json"]["result"]
        mod_ff = Path(result["output"]) / result["mod_ff"]
        receipt["notes"].append({"mod_ff_sha256": hashlib.sha256(mod_ff.read_bytes()).hexdigest(),
                                 "mod_ff_bytes": mod_ff.stat().st_size, "rawfiles_verified": result["rawfiles_verified"]})
        step(receipt, "project verify --inputs", PAT + ["project", "verify", str(Path(result["output"]) / "receipt.json"),
                                                        "--inputs", "--output", str(work / "verify"), "--json"])
        step(receipt, "ff inspect mod.ff", PAT + ["ff", "inspect", str(mod_ff), "--output", str(work / "inspect"), "--json"])
        step(receipt, "ff extract rawfiles", PAT + ["ff", "extract", str(mod_ff), "--types", "rawfile",
                                                    "--output", str(work / "extract"), "--json"])
        if platform_token() == "windows":
            # Stage the built mod at a durable, documented location for Tier 3 step 3h, never renaming it.
            staged = stage_for_tier3(mod_ff, home)
            stage_row = {"name": "stage mod.ff for tier 3", "passed": staged is not None, "expected": "built file named mod.ff"}
            if staged is None:
                stage_row["stderr_head"] = (f"project build produced {mod_ff.name}; a T6 fastfile is bound to its file name, "
                                            "so it cannot be renamed to mod.ff for install")
            receipt["steps"].append(stage_row)
            print(("PASS " if staged else "FAIL ") + "stage mod.ff for tier 3", flush=True)
            if staged is not None:
                receipt["notes"].append({"tier3_mod_ff": "<pat-home>/qualify/hello_zm/mod.ff"})
                print(f"\nTier 3 step 3h uses this file:\n  pat game install-mod \"{staged}\" hello_zm --json", flush=True)
    composition = ROOT / "examples/hello-pack/composition.json"
    step(receipt, "module plan hello-pack", PAT + ["module", "plan", str(composition), "--output", str(work / "pack-plan"), "--json"])
    pack = step(receipt, "module build hello-pack (real gsc-tool + OAT)", PAT + ["module", "build", str(composition), "--output", str(work / "pack-build"), "--json"], timeout=600)
    if pack["passed"]:
        result = pack["json"]["result"]
        pack_ff = Path(result["output"]) / result["mod_ff"]
        receipt["notes"].append({"hello_pack_mod_ff_sha256": hashlib.sha256(pack_ff.read_bytes()).hexdigest(),
                                 "hello_pack_mod_ff_bytes": pack_ff.stat().st_size, "hello_pack_rawfiles_verified": result["rawfiles_verified"],
                                 "hello_pack_modules": [m["id"] for m in result["modules"]]})
        step(receipt, "project verify --inputs the pack receipt", PAT + ["project", "verify", str(Path(result["output"]) / "receipt.json"),
                                                                       "--inputs", "--output", str(work / "pack-verify"), "--json"])
        step(receipt, "ff inspect the pack mod.ff", PAT + ["ff", "inspect", str(pack_ff), "--output", str(work / "pack-inspect"), "--json"])
    if build["passed"]:
        # Seeds: the hello-zm package just built becomes a seed module, declared from its fastfile, then
        # composed with the second example on the stock game. Exercises declare, seed loads and roots.
        seed_dir = work / "seed-module"
        seed_dir.mkdir()
        shutil.copyfile(mod_ff, seed_dir / "mod.ff")
        declared = step(receipt, "module declare the hello-zm package", PAT + ["module", "declare", str(seed_dir / "mod.ff"),
                                                                              "--id", "hello_seed", "--base", "stock", "--map", "zm_transit",
                                                                              "--output", str(work / "declare"), "--json"])
        if declared["passed"]:
            shutil.copyfile(work / "declare" / "seed.json", seed_dir / "seed.json")
            if (work / "declare" / "mod.str").is_file():
                shutil.copyfile(work / "declare" / "mod.str", seed_dir / "mod.str")
            declaration = json.loads((work / "declare" / "module.json").read_text(encoding="utf-8"))
            declaration.update({"category": "scripts", "kind": "script", "maps": ["*"]})
            (seed_dir / "module.json").write_text(json.dumps(declaration, indent=2) + "\n", encoding="utf-8")
            second = work / "second-module"
            shutil.copytree(ROOT / "examples/hello-zm-two", second)
            pack_dir = work / "seed-pack"
            pack_dir.mkdir()
            (pack_dir / "composition.json").write_text(json.dumps({
                "schema": 1, "name": "stock_seeded_pack", "title": "hello-zm as a seed plus the round announcer",
                "base": "stock", "map": "zm_transit",
                "modules": [{"path": "../seed-module", "role": "base"}, "../second-module"]}, indent=2) + "\n", encoding="utf-8")
            step(receipt, "module plan a seed composition", PAT + ["module", "plan", str(pack_dir / "composition.json"),
                                                                  "--output", str(work / "seed-plan"), "--json"])
            seeded = step(receipt, "module build a seed composition (real OAT)", PAT + ["module", "build", str(pack_dir / "composition.json"),
                                                                                       "--output", str(work / "seed-build"), "--json"], timeout=600)
            if seeded["passed"]:
                result = seeded["json"]["result"]
                receipt["notes"].append({"seed_pack_mod_ff_sha256": hashlib.sha256((Path(result["output"]) / result["mod_ff"]).read_bytes()).hexdigest(),
                                         "seed_roots_verified": result["seed_roots_verified"], "seed_pack_base_member": result["base_member"]})
    bad = work / "bad.gsc"
    bad.write_text("main()\n{\n    this is not gsc ;;; \n}\n", encoding="utf-8")
    step(receipt, "gsc compile broken script fails structurally", PAT + ["gsc", "compile", str(bad), "--output", str(work / "bad-compile"), "--json"], expect_ok=False)
    good = work / "good.gsc"
    good.write_text("main()\n{\n    level thread noop();\n}\n\nnoop()\n{\n    wait 1;\n}\n", encoding="utf-8")
    compiled = step(receipt, "gsc compile minimal script", PAT + ["gsc", "compile", str(good), "--output", str(work / "good-compile"), "--json"])
    if compiled["passed"]:
        produced = Path(compiled["json"]["result"]["output"]) / compiled["json"]["result"]["files"][0]
        step(receipt, "gsc decompile the compiled script", PAT + ["gsc", "decompile", str(produced), "--output", str(work / "good-decompile"), "--json"])
    if media:
        tier_media(receipt, work)


BEGIN_MARKER = "qualify-tier3-begin.json"


def tier_game_begin(home: Path) -> None:
    """Record when the human-authorized Tier 3 run starts so stale state files cannot count."""
    marker = home / "game" / BEGIN_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"began": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                  "began_unix": time.time()}) + "\n", encoding="utf-8")
    print(f"Tier 3 begun at {marker.read_text().strip()}. Run the commands in docs/WINDOWS-QUALIFICATION.md, then rerun with --collect.")


def _fresh(path: Path, began_unix: float) -> bool:
    """Written at or after the begin marker, with one second of slack for coarse mtimes.

    Filesystems that store mtimes at one- or two-second granularity (FAT, some network shares)
    can stamp a file written just after the marker with a time before it. The marker is written
    before any Tier 3 command runs and nothing in the sequence writes these files in the second
    before it, so the slack admits no stale run; it is deliberate and predates this file."""
    return path.stat().st_mtime >= began_unix - 1


def tier_game_collect(receipt, home: Path, notes: str | None):
    state = home / "game"
    marker = state / BEGIN_MARKER
    if not marker.is_file():
        raise SystemExit("Run `--tier game --begin` before the Tier 3 commands; no begin marker found, so freshness cannot be established.")
    began = json.loads(marker.read_text(encoding="utf-8"))["began_unix"]
    receipt["notes"].append({"tier3_began_unix": began})

    def load(name):
        path = state / name
        if not path.is_file():
            return None, "missing"
        if not _fresh(path, began):
            return None, "stale: written before this Tier 3 run began"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None, "unreadable JSON"
        if not isinstance(data, dict):
            return None, "unreadable JSON (expected an object)"
        return data, None

    checks = {
        "last-launch.json": lambda d: d.get("launch_requested") is True and d.get("game_detected") is True,
        "last-load.json": lambda d: d.get("status") == "engine-state-verified",
        "last-load-check.json": lambda d: d.get("verified") is True and d.get("state_matches") is True,
        "last-result.json": lambda d: d.get("ok") is True,
    }
    for name, check in checks.items():
        data, problem = load(name)
        if problem:
            receipt["steps"].append({"name": name, "passed": False, "expected": "fresh, successful state", "stderr_head": problem})
            continue
        passed = bool(check(data))
        receipt["steps"].append({"name": name, "passed": passed, "json": data,
                                 "expected": "fresh, successful state",
                                 **({} if passed else {"stderr_head": "state file present but does not record success"})})
    installs = sorted((state / "installs").glob("hello_zm-*.json")) if (state / "installs").is_dir() else []
    fresh_installs = [p for p in installs if _fresh(p, began)]
    install_data, install_problem = (load(Path("installs") / fresh_installs[-1].name) if fresh_installs
                                     else (None, "no fresh hello_zm install receipt"))
    receipt["steps"].append({"name": "install-mod hello_zm receipt", "passed": install_data is not None,
                             "json": install_data, "expected": "fresh install receipt",
                             **({} if install_data is not None else {"stderr_head": install_problem})})
    receipt["human_observations"] = {
        "launcher_prompt_shown": None, "game_window_took_focus": None, "main_menu_reached": None,
        "town_spawn_playable": None, "hello_zm_line_visible_after_spawn": None, "quit_exited_cleanly": None,
        "plutonium_build": None, "notes": notes or "Fill these in from what you saw on screen; null means not observed."}
    receipt["notes"].append("Tier 3 commands were run by hand with per-command human authorization. Only state files written after the begin marker count, and each must record success. The human observations are required for level `game`; automated state alone is not a playable spawn.")


def default_home() -> Path:
    """The toolkit's default PAT_HOME on this OS (mirrors core/config.py), to detect isolation."""
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "PlutoniumAgentToolkit"
    return Path.home() / ".local" / "state" / "plutonium-agent-toolkit"


def receipt_name(tier: str, token: str) -> str:
    """``<platform>-tier<N>-<tier>.json``; the 0.1.0a1 Windows receipts predate the prefix."""
    number = {"offline": 1, "backends": 2, "game": 3}[tier]
    return f"{token}-tier{number}-{tier}.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tier", choices=["offline", "backends", "game"])
    ap.add_argument("--output", type=Path, help="Directory for receipts, e.g. docs/receipts")
    ap.add_argument("--begin", action="store_true", help="Tier game: write the begin marker before the human-authorized commands")
    ap.add_argument("--collect", action="store_true", help="Tier game: fold saved state into a receipt; runs nothing")
    ap.add_argument("--notes", help="Tier game: free-text human observations to include")
    ap.add_argument("--media", action="store_true", help="Tier backends: also install FFmpeg, Blender and Cast and run audio/model routes (large downloads)")
    ap.add_argument("--allow-untested-platform", "--allow-non-windows", dest="allow_untested", action="store_true",
                    help="Run on a platform the toolkit does not claim (or the game tier off Windows) for testing this script only")
    ap.add_argument("--redact-existing", type=Path, metavar="FILE",
                    help="Reapply the current redaction rules to a committed receipt in place; runs nothing, works on any platform")
    args = ap.parse_args()
    explicit_home = os.environ.get("PAT_HOME")
    home = Path(explicit_home) if explicit_home else default_home()
    if args.redact_existing:
        changed = redact_existing(args.redact_existing, redactor(extra_paths=[("pat-home", str(home)), ("repo", str(ROOT))]))
        print(f"{'re-redacted' if changed else 'already clean'}: {args.redact_existing}")
        return 0
    if not args.tier:
        ap.error("--tier is required unless --redact-existing is given")
    if not args.output and not (args.begin and args.tier == "game"):
        # Only `--tier game --begin` writes nothing but the marker under PAT_HOME
        # (docs/WINDOWS-QUALIFICATION.md); every other tier writes a receipt and needs --output.
        ap.error("--output is required unless `--tier game --begin` or --redact-existing is given")
    token = platform_token()
    layer = compatibility_layer()
    if token not in NATIVE_PLATFORMS and not args.allow_untested:
        print(f"This script qualifies native Windows and Linux; this host is {token}, which the toolkit does not claim.", file=sys.stderr)
        return 2
    if layer and not args.allow_untested:
        # Wine and WSL are not native hosts; a receipt from them would carry native_* false and
        # must not be produced as if it qualified anything (docs/SUPPORT.md Platform table).
        print(f"This host runs {token} under {layer}, which never counts as native; qualify on a real host.", file=sys.stderr)
        return 2
    if args.tier == "game" and token != "windows" and not args.allow_untested:
        print("Tier game qualifies game control, which uses the Win32 console: run it on native Windows.", file=sys.stderr)
        return 2
    runner = ci_runner()
    if runner and not args.allow_untested:
        # A hosted runner is not a user's machine; docs/SUPPORT.md's native level excludes it.
        print(f"This process runs on a CI runner ({runner} is set); receipts are recorded on real hosts only.", file=sys.stderr)
        return 2
    if not explicit_home and args.tier != "game":
        # Tier 1 runs `configure` against a fake storage path and Tier 2 installs backends. Without
        # an explicit PAT_HOME those must not touch the user's real toolkit home (maintainer
        # finding on the first Linux pull request): use a fresh temporary home instead.
        home = Path(tempfile.mkdtemp(prefix="pat-qualify-home-"))
        print(f"PAT_HOME is unset; using a temporary toolkit home {home} so your real configuration is untouched.", file=sys.stderr)
    os.environ["PAT_HOME"] = str(home)
    work = Path(tempfile.mkdtemp(prefix=f"pat-qualify-{args.tier}-"))
    redact = redactor(extra_paths=[("pat-home", str(home)), ("work", str(work)), ("repo", str(ROOT))])
    receipt = new_receipt(args.tier)
    receipt["environment"]["pat_home_isolated"] = home != default_home()
    receipt["notes"].append(f"work directory {work}")
    try:
        if args.tier == "offline":
            tier_offline(receipt, home, work)
        elif args.tier == "backends":
            tier_backends(receipt, home, work, media=args.media)
        else:
            if args.begin:
                tier_game_begin(home)
                return 0
            if not args.collect:
                print("Tier game runs nothing automatically. Use --begin, run the commands in docs/WINDOWS-QUALIFICATION.md with human authorization, then rerun with --collect.", file=sys.stderr)
                return 2
            tier_game_collect(receipt, home, args.notes)
    finally:
        pass  # the work directory is left for inspection; it holds nothing private
    return 0 if finish(receipt, args.output / __version__, receipt_name(args.tier, token), redact) else 1


if __name__ == "__main__":
    sys.exit(main())
