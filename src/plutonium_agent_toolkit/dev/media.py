"""``audio inspect|convert``, ``image convert`` and ``lua decompile``.

Thin adapters over FFmpeg/ffprobe, OpenAssetTools ImageConverter and
CoDLuaDecompiler. Each stages its input inside the job directory, runs the
backend once, and checks the produced file rather than trusting the exit code.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..core.errors import BACKEND_FAILED, INPUT_INVALID, Failure
from ..core.jobs import Job
from .backends import executable

AUDIO_FORMATS = {"wav": "pcm_s16le", "flac": "flac", "ogg": "libvorbis", "mp3": "libmp3lame"}
AUDIO_RATES = (8000, 11025, 16000, 22050, 32000, 44100, 48000, 96000)
IMAGE_INPUTS = (".dds", ".iwi")
IMAGE_GAMES = ("t6", "t5")


def add_parsers(sub, common):
    p = sub.add_parser("audio", help="Inspect and convert audio with FFmpeg")
    a = p.add_subparsers(dest="action", required=True)
    q = a.add_parser("inspect", help="Probe format, streams and duration")
    q.add_argument("input")
    common(q)
    q = a.add_parser("convert", help="Convert to a game-ready format and verify the stream parameters")
    q.add_argument("input")
    q.add_argument("--format", choices=sorted(AUDIO_FORMATS), default="wav")
    q.add_argument("--rate", type=int, choices=AUDIO_RATES, default=48000)
    q.add_argument("--channels", type=int, choices=(1, 2), default=1)
    common(q)

    p = sub.add_parser("image", help="Convert DDS/IWI textures with OpenAssetTools ImageConverter")
    a = p.add_subparsers(dest="action", required=True)
    q = a.add_parser("convert", help="Convert one DDS or IWI; the output is the other format")
    q.add_argument("input")
    q.add_argument("--game", choices=IMAGE_GAMES, default="t6")
    common(q)

    p = sub.add_parser("lua", help="Decompile LUI bytecode with CoDLuaDecompiler")
    a = p.add_subparsers(dest="action", required=True)
    q = a.add_parser("decompile", help="Decompile one Lua bytecode file")
    q.add_argument("input")
    common(q)


def _probe(job: Job, path: Path, timeout: int) -> dict:
    log = job.run([*executable("ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], timeout=timeout)
    try:
        data = json.loads(log.read_text(encoding="utf-8", errors="replace"))
    except ValueError as exc:
        raise Failure(BACKEND_FAILED, "ffprobe did not return JSON", log=log.name) from exc
    if not data.get("streams"):
        raise Failure(INPUT_INVALID, "No streams found in the media file", log=log.name)
    return data


def execute_audio(args, job: Job) -> dict:
    src = job.input(args.input)
    before = _probe(job, src, args.timeout)
    audio = [s for s in before["streams"] if s.get("codec_type") == "audio"]
    if not audio:
        raise Failure(INPUT_INVALID, "Input contains no audio stream")
    if args.action == "inspect":
        return {"media": before, "audio_streams": len(audio)}
    dest = job.root / f"audio.{args.format}"
    job.run([*executable("ffmpeg"), "-nostdin", "-v", "error", "-n", "-i", str(src), "-map", "0:a:0", "-vn",
             "-ar", str(args.rate), "-ac", str(args.channels), "-c:a", AUDIO_FORMATS[args.format], str(dest)], timeout=args.timeout)
    if not dest.is_file() or dest.stat().st_size == 0:
        raise Failure(BACKEND_FAILED, "FFmpeg produced no output file")
    after = _probe(job, dest, args.timeout)
    stream = after["streams"][0]
    if int(stream.get("sample_rate", 0)) != args.rate or stream.get("channels") != args.channels:
        raise Failure(BACKEND_FAILED, "Encoded audio parameters did not match the request",
                      requested={"rate": args.rate, "channels": args.channels},
                      actual={"rate": stream.get("sample_rate"), "channels": stream.get("channels")})
    return {"file": dest.name, "media": after, "verification": "stream parameters verified by ffprobe; in-game playback untested"}


def execute_image(args, job: Job) -> dict:
    src = job.input(args.input)
    if src.suffix.lower() not in IMAGE_INPUTS:
        raise Failure(INPUT_INVALID, "ImageConverter accepts .dds or .iwi input")
    staged = job.root / src.name
    shutil.copyfile(src, staged)
    job.run([*executable("image"), "--no-color", f"--{args.game}", str(staged)], timeout=args.timeout)
    produced = [p for p in job.root.rglob("*") if p.is_file() and p != staged and p.suffix.lower() in IMAGE_INPUTS
                and p.name != "receipt.json"]
    if not produced:
        raise Failure(BACKEND_FAILED, "ImageConverter produced no converted image")
    if any(p.stat().st_size == 0 for p in produced):
        raise Failure(BACKEND_FAILED, "ImageConverter produced an empty image")
    return {"files": [p.relative_to(job.root).as_posix() for p in produced], "game": args.game,
            "verification": "converted file exists; texture correctness in game untested"}


def execute_lua(args, job: Job) -> dict:
    src = job.input(args.input)
    staged = job.root / "input.lua"
    shutil.copyfile(src, staged)
    job.run([*executable("lua"), str(staged)], timeout=args.timeout)
    # CoDLuaDecompiler writes <name>.dec.lua beside the input.
    candidates = [p for p in job.root.glob("*.lua") if p != staged and p.stat().st_size > 0]
    if not candidates:
        raise Failure(BACKEND_FAILED, "CoDLuaDecompiler produced no non-empty output")
    return {"files": [p.name for p in candidates],
            "verification": "decompiled file exists; semantic equivalence to the original script is not established"}


def execute(args, job: Job) -> dict:
    return {"audio": execute_audio, "image": execute_image, "lua": execute_lua}[args.group](args, job)
