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


class InstallFixture(unittest.TestCase):
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
        self.mod_ff.write_bytes(b"TAff" + b"FASTFILE")



class InstallModTests(InstallFixture):
    def test_opt_in_soundbanks_and_profile_links_are_receipted(self):
        bank = self.mod_ff.parent / "example.all.sabl"
        bank.write_bytes(b"synthetic bank")
        load = self.root / "mod_load.ff"
        load.write_bytes(b"synthetic load")
        foundation = self.root / "foundation.json"
        foundation.write_text(json.dumps({"profile_links": {"mod_load.ff": str(load)}}))
        code, row = invoke(["game", "install-mod", str(self.mod_ff), "example", "--with-soundbanks", "--profile-foundation", str(foundation)])
        self.assertEqual(code, 0, row)
        self.assertEqual((self.storage / "mods/example/example.all.sabl").read_bytes(), b"synthetic bank")
        self.assertTrue((self.storage / "mods/example/mod_load.ff").is_symlink())
        self.assertEqual(row["result"]["soundbanks"][0]["name"], bank.name)
        self.assertEqual(row["result"]["profile_links"][0]["name"], "mod_load.ff")
        self.assertFalse(row["result"]["game_touched"])


    def test_unhashable_profile_link_refuses_before_moving_the_previous_install(self):
        code, row = invoke(["game", "install-mod", str(self.mod_ff), "example"])
        self.assertEqual(code, 0, row)
        installed = self.storage / "mods/example/mod.ff"
        before = installed.read_bytes()
        link_dir = self.root / "link_dir"
        link_dir.mkdir()
        foundation = self.root / "foundation.json"
        foundation.write_text(json.dumps({"profile_links": {"mod_load.ff": str(link_dir)}}))
        self.mod_ff.write_bytes(b"TAffNEWER")
        code, row = invoke(["game", "install-mod", str(self.mod_ff), "example", "--replace", "--profile-foundation", str(foundation)])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_missing")
        self.assertEqual(installed.read_bytes(), before, "the previous install is untouched")
        self.assertFalse(list((Path(os.environ["PAT_HOME"])).rglob("mod-backups/*")), "nothing was moved aside")

    def test_install_copies_hashes_and_refuses_overwrite(self):
        code, row = invoke(["game", "install-mod", str(self.mod_ff), "hello_zm"])
        self.assertEqual(code, 0, row)
        dest = self.storage / "mods" / "hello_zm" / "mod.ff"
        self.assertEqual(dest.read_bytes(), b"TAff" + b"FASTFILE")
        self.assertEqual(row["result"]["sha256"], hashlib.sha256(b"TAff" + b"FASTFILE").hexdigest())
        self.assertFalse(row["result"]["game_touched"])
        code, row = invoke(["game", "install-mod", str(self.mod_ff), "hello_zm"])
        self.assertEqual(row["error_code"], "output_exists")
        self.assertEqual(dest.read_bytes(), b"TAff" + b"FASTFILE")
        self.mod_ff.write_bytes(b"TAffNEWER")
        code, row = invoke(["game", "install-mod", str(self.mod_ff), "hello_zm", "--replace"])
        self.assertEqual(code, 0, row)
        self.assertEqual(dest.read_bytes(), b"TAffNEWER")
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


class InstallModReplaceSafetyTests(InstallFixture):
    def test_replace_from_inside_the_installed_folder_keeps_the_mod(self):
        # First install, then --replace using the installed file itself as the source.
        invoke(["game", "install-mod", str(self.mod_ff), "hello_zm"])
        installed = self.storage / "mods" / "hello_zm" / "mod.ff"
        code, row = invoke(["game", "install-mod", str(installed), "hello_zm", "--replace"])
        self.assertEqual(code, 0, row)
        self.assertEqual(installed.read_bytes(), b"TAff" + b"FASTFILE")

    def test_replace_restores_backup_when_the_copy_fails(self):
        from unittest.mock import patch

        from plutonium_agent_toolkit.game import install

        invoke(["game", "install-mod", str(self.mod_ff), "hello_zm"])
        installed_dir = self.storage / "mods" / "hello_zm"
        self.mod_ff.write_bytes(b"TAffNEWER")
        with patch.object(install, "sha256_file", return_value="0" * 64):
            code, row = invoke(["game", "install-mod", str(self.mod_ff), "hello_zm", "--replace"])
        self.assertEqual(row["error_code"], "hash_mismatch")
        self.assertEqual((installed_dir / "mod.ff").read_bytes(), b"TAff" + b"FASTFILE", "previous install restored")

    def test_extra_argument_and_replace_are_rejected_for_other_actions(self):
        code, row = invoke(["game", "select-mod", "foo", "unintended"])
        self.assertEqual(code, 2)
        self.assertIn("at most one argument", row["message"])
        code, row = invoke(["game", "mods", "--replace"])
        self.assertEqual(code, 2)
        self.assertIn("--replace applies only", row["message"])
