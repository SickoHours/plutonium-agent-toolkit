"""Stand-in for ffprobe: -v error -show_format -show_streams -of json <file>. Reads a sidecar JSON
written by fake_ffmpeg or the test, or synthesizes a 44.1k stereo stream for any .wav input."""
import json
import sys
from pathlib import Path

path = Path(sys.argv[-1])
side = path.with_suffix(path.suffix + ".probe.json")
if side.is_file():
    print(side.read_text())
elif path.suffix.lower() in (".wav", ".flac", ".ogg", ".mp3") and path.is_file():
    print(json.dumps({"format": {"duration": "1.0"}, "streams": [{"codec_type": "audio", "sample_rate": "44100", "channels": 2}]}))
else:
    print(json.dumps({"format": {}, "streams": []}))
