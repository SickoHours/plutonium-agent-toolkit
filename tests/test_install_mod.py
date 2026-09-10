import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from plutonium_agent_toolkit.cli import entry


def invoke(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = entry(argv)
    return code, json.loads(buf.getvalue())


class InstallModTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        os.environ["PAT_HOME"] = str(self.root / "home")
        self.addCleanup(lambda: os.environ.pop("PAT_HOME", None))
        self.storage = self.root / "storage" / "t6"
        (self.storage / "mods").mkdir(parents=True)
        invoke(["configure", "--plutonium-storage-t6", str(self.storage)])
        self.mod_ff = self.root / "build" / "packages" / "mod.ff"
        self.mod_ff.parent.mkdir(parents=True)
        self.mod_ff.write_bytes(b"FASTFILE")

    def test_install_copies_hashes_and_refuses_overwrite(self):
        code, row = invoke(["game", "install-mod", str(self.mod_ff), "hello_zm"])
        self.assertEqual(code, 0, row)
        dest = self.storage / "mods" / "hello_zm" / "mod.ff"
        self.assertEqual(dest.read_bytes(), b"FASTFILE")
        self.assertEqual(row["result"]["sha256"], hashlib.sha256(b"FASTFILE").hexdigest())
        self.assertFalse(row["result"]["game_touched"])
        code, row = invoke(["game", "install-mod", str(self.mod_ff), "hello_zm"])
        self.assertEqual(row["error_code"], "output_exists")
        self.assertEqual(dest.read_bytes(), b"FASTFILE")
        self.mod_ff.write_bytes(b"NEWER")
        code, row = invoke(["game", "install-mod", str(self.mod_ff), "hello_zm", "--replace"])
        self.assertEqual(code, 0, row)
        self.assertEqual(dest.read_bytes(), b"NEWER")
        self.assertTrue(Path(row["result"]["backup"]).joinpath("mod.ff").is_file(), "old folder moved aside, not deleted")
        code, row = invoke(["game", "mods"])
        self.assertTrue(row["result"]["mods"][0]["available"])

    def test_validation(self):
        code, row = invoke(["game", "install-mod", str(self.mod_ff), "mp_bad"])
        self.assertEqual(row["error_code"], "input_invalid")
        code, row = invoke(["game", "install-mod", str(self.mod_ff), "../escape"])
        self.assertEqual(row["error_code"], "input_invalid")
        other = self.root / "not_mod.ff"
        other.write_bytes(b"x")
        code, row = invoke(["game", "install-mod", str(other), "ok"])
        self.assertEqual(row["error_code"], "input_invalid")
        code, row = invoke(["game", "install-mod", str(self.mod_ff)])
        self.assertEqual(code, 2)
        code, row = invoke(["game", "install-mod", str(self.root / "missing" / "mod.ff"), "ok"])
        self.assertEqual(row["error_code"], "input_missing")

    def test_install_does_not_need_windows(self):
        if os.name == "nt":
            self.skipTest("gate does not apply")
        code, row = invoke(["game", "install-mod", str(self.mod_ff), "anywhere"])
        self.assertEqual(code, 0, row)
