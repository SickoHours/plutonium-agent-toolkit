"""audio / image / lua / model routes against fake backends."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from plutonium_agent_toolkit.cli import entry

FAKES = Path(__file__).resolve().parent / "fakes"


def invoke(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = entry(argv)
    return code, json.loads(buf.getvalue())


class MediaFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = {"PAT_HOME": str(self.root / "home"), "PAT_DEV_UNGATED": "1",
               "PAT_BACKEND_FFMPEG": str(FAKES / "fake_ffmpeg.py"), "PAT_BACKEND_FFPROBE": str(FAKES / "fake_ffprobe.py"),
               "PAT_BACKEND_IMAGE": str(FAKES / "fake_image.py"), "PAT_BACKEND_LUA": str(FAKES / "fake_lua.py"),
               "PAT_BACKEND_BLENDER": str(FAKES / "fake_blender.py")}
        self.saved = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        self.addCleanup(self._restore)
        # Fake Cast add-on so model routes pass the add-on presence check.
        cast = self.root / "home" / "backends" / "cast" / "io_scene_cast"
        cast.mkdir(parents=True)
        (cast / "__init__.py").write_text("")
        self.n = 0

    def _restore(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def out(self):
        self.n += 1
        return str(self.root / f"job-{self.n:03d}")


class AudioTests(MediaFixture):
    def test_inspect_and_convert_verify_parameters(self):
        wav = self.root / "in.wav"
        wav.write_bytes(b"RIFF" * 8)
        code, row = invoke(["audio", "inspect", str(wav), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["audio_streams"], 1)
        code, row = invoke(["audio", "convert", str(wav), "--format", "flac", "--rate", "48000", "--channels", "1", "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["file"], "audio.flac")
        self.assertEqual(row["result"]["media"]["streams"][0]["sample_rate"], "48000")

    def test_parameter_mismatch_is_backend_failed(self):
        wav = self.root / "bad.wav"
        wav.write_bytes(b"RIFF WRONG_RATE")
        code, row = invoke(["audio", "convert", str(wav), "--rate", "48000", "--output", self.out()])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "backend_failed")
        self.assertEqual(row["details"]["actual"]["rate"], "22050")

    def test_no_audio_stream_is_input_invalid(self):
        f = self.root / "silent.bin"
        f.write_bytes(b"x")
        code, row = invoke(["audio", "inspect", str(f), "--output", self.out()])
        self.assertEqual(row["error_code"], "input_invalid")


class ImageLuaTests(MediaFixture):
    def test_image_convert_round_trip_and_empty_output(self):
        dds = self.root / "tex.dds"
        dds.write_bytes(b"DDS ")
        code, row = invoke(["image", "convert", str(dds), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["files"], ["tex.iwi"])
        bad = self.root / "empty.dds"
        bad.write_bytes(b"DDS EMPTY_OUT")
        code, row = invoke(["image", "convert", str(bad), "--output", self.out()])
        self.assertEqual(row["error_code"], "backend_failed")
        png = self.root / "x.png"
        png.write_bytes(b"PNG")
        code, row = invoke(["image", "convert", str(png), "--output", self.out()])
        self.assertEqual(row["error_code"], "input_invalid")

    def test_lua_decompile_and_missing_output(self):
        lua = self.root / "ui.lua"
        lua.write_bytes(b"\x1bLua")
        code, row = invoke(["lua", "decompile", str(lua), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["files"], ["input.dec.lua"])
        bad = self.root / "none.lua"
        bad.write_bytes(b"NO_OUTPUT")
        code, row = invoke(["lua", "decompile", str(bad), "--output", self.out()])
        self.assertEqual(row["error_code"], "backend_failed")


class ModelTests(MediaFixture):
    def test_inspect_convert_rename_and_failure(self):
        cast = self.root / "gun.cast"
        cast.write_bytes(b"cast")
        code, row = invoke(["model", "inspect", str(cast), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["before"]["totals"]["bones"], 1)
        code, row = invoke(["model", "convert", str(cast), "--format", "obj", "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["file"], "model.obj")
        self.assertIn("rigs and animations are dropped", row["result"]["format_limitation"])
        mapping = self.root / "map.json"
        mapping.write_text(json.dumps({"tag_weapon": "tag_weapon_right"}))
        code, row = invoke(["model", "rename-bones", str(cast), "--mapping", str(mapping), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["renamed"], {"tag_weapon": "tag_weapon_right"})
        bad = self.root / "broken.cast"
        bad.write_bytes(b"FAIL")
        code, row = invoke(["model", "convert", str(bad), "--output", self.out()])
        self.assertEqual(row["error_code"], "backend_failed")
        receipt = json.loads(Path(row["receipt"]).read_text())
        self.assertEqual(receipt["status"], "failed")

    def test_validation_before_blender(self):
        cast = self.root / "gun.cast"
        cast.write_bytes(b"cast")
        code, row = invoke(["model", "transform", str(cast), "--scale", "0", "--output", self.out()])
        self.assertEqual(row["error_code"], "input_invalid")
        code, row = invoke(["model", "retime", str(cast), "--fps", "0", "--output", self.out()])
        self.assertEqual(row["error_code"], "input_invalid")
        bad_map = self.root / "bad.json"
        bad_map.write_text(json.dumps({"a": "x" * 64}))
        code, row = invoke(["model", "rename-bones", str(cast), "--mapping", str(bad_map), "--output", self.out()])
        self.assertEqual(row["error_code"], "input_invalid")
        obj = self.root / "m.obj"
        obj.write_bytes(b"o")
        code, row = invoke(["model", "inspect", str(obj), "--rig", str(cast), "--output", self.out()])
        self.assertEqual(row["error_code"], "input_invalid")

    def test_missing_cast_addon_is_backend_unavailable(self):
        import shutil
        shutil.rmtree(self.root / "home" / "backends" / "cast")
        cast = self.root / "gun.cast"
        cast.write_bytes(b"cast")
        code, row = invoke(["model", "inspect", str(cast), "--output", self.out()])
        self.assertEqual(row["error_code"], "backend_unavailable")
