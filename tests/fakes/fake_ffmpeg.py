"""Stand-in for ffmpeg convert: honours -ar/-ac and writes a sidecar the fake ffprobe reads.
A source containing WRONG_RATE makes the fake ignore -ar, reproducing a parameter mismatch."""
import json
import sys
from pathlib import Path

args = sys.argv[1:]
src = Path(args[args.index("-i") + 1])
rate = int(args[args.index("-ar") + 1])
channels = int(args[args.index("-ac") + 1])
dest = Path(args[-1])
if b"WRONG_RATE" in src.read_bytes():
    rate = 22050
dest.write_bytes(b"AUDIO" * 16)
dest.with_suffix(dest.suffix + ".probe.json").write_text(json.dumps(
    {"format": {"duration": "1.0"}, "streams": [{"codec_type": "audio", "sample_rate": str(rate), "channels": channels}]}))
