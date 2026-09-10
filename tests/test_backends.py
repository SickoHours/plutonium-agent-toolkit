"""Backend pin and archive-safety tests. Offline; uses synthetic zips."""
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from plutonium_agent_toolkit.core.errors import Failure
from plutonium_agent_toolkit.dev import backends


class PinTests(unittest.TestCase):
    def test_pins_are_well_formed(self):
        data = backends.pins()
        self.assertEqual(data["schema"], 1)
        for p in data["programs"]:
            self.assertRegex(p["id"], r"^[a-z0-9]+$")
            self.assertTrue(p["url"].startswith("https://"), p["id"])
            self.assertIn("license", p)
            self.assertIsInstance(p["optional"], bool)
            if p["sha256"]:
                self.assertRegex(p["sha256"], r"^[0-9a-f]{64}$", p["id"])
            else:
                self.assertTrue(p["optional"], f"{p['id']} lacks a hash but is required")

    def test_required_backends_are_all_pinned(self):
        for p in backends.pins()["programs"]:
            if not p["optional"]:
                self.assertTrue(p["sha256"], p["id"])


def make_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries:
            z.writestr(name, data)
    return buf.getvalue()


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, entries):
        p = self.root / name
        p.write_bytes(make_zip(entries))
        return p

    def test_extracts_and_strips_single_root(self):
        archive = self.write("ok.zip", [("tool/bin/a.exe", b"A"), ("tool/readme.txt", b"R")])
        dest = self.root / "dest"
        dest.mkdir()
        backends.safe_extract(archive, dest, strip_root=True)
        self.assertEqual((dest / "bin" / "a.exe").read_bytes(), b"A")

    def test_refuses_traversal_reserved_and_case_collisions(self):
        cases = {
            "traversal": [("../evil.exe", b"x")],
            "absolute": [("/abs.exe", b"x")],
            "reserved": [("CON.txt", b"x")],
            "collision": [("A.txt", b"x"), ("a.txt", b"y")],
        }
        for label, entries in cases.items():
            archive = self.write(f"{label}.zip", entries)
            dest = self.root / f"dest-{label}"
            dest.mkdir()
            with self.assertRaises(Failure, msg=label):
                backends.safe_extract(archive, dest)

    def test_install_refuses_changed_tree_and_verifies_unchanged(self):
        archive_bytes = make_zip([("gsc-tool.exe", b"GSC")])
        sha = backends.hashlib.sha256(archive_bytes).hexdigest()
        item = {"id": "gsc", "name": "gsc-tool", "optional": False, "license": "GPL-3.0",
                "downloads": {backends.platform_token(): {"url": "https://example.invalid/gsc.zip", "sha256": sha, "strip_root": False}}}
        cache = self.root / "cache"
        cache.mkdir()
        (cache / f"gsc-{sha[:12]}.zip").write_bytes(archive_bytes)
        backends_dir = self.root / "backends"
        first = backends.install(item, backends_dir, cache)
        self.assertEqual(first["action"], "installed")
        second = backends.install(item, backends_dir, cache)
        self.assertEqual(second["action"], "verified")
        (backends_dir / "gsc" / "gsc-tool.exe").write_bytes(b"TAMPERED")
        with self.assertRaises(Failure) as ctx:
            backends.install(item, backends_dir, cache)
        self.assertEqual(ctx.exception.code, "backend_failed")
        self.assertEqual((backends_dir / "gsc" / "gsc-tool.exe").read_bytes(), b"TAMPERED", "preserved, not repaired")


class CrossPlatformTests(unittest.TestCase):
    def test_override_hint_names_each_binary_not_the_program_id(self):
        hint = backends.override_hint(backends.program("oat"))
        self.assertIn("PAT_BACKEND_LINKER", hint)
        self.assertIn("PAT_BACKEND_UNLINKER", hint)
        self.assertIn("PAT_BACKEND_IMAGE", hint)
        self.assertNotIn("PAT_BACKEND_OAT", hint)
        # A directory-resolved add-on (Cast) has no PAT_BACKEND override.
        self.assertIn("resolved by directory", backends.override_hint(backends.program("cast")))

    def test_platform_independent_addon_downloads_anywhere_but_exe_pins_do_not(self):
        self.assertIsNotNone(backends.resolve_download(backends.program("cast"), "linux"))
        self.assertIsNotNone(backends.resolve_download(backends.program("cast"), "darwin"))
        self.assertIsNone(backends.resolve_download(backends.program("gsc"), "linux"))
        self.assertIsNotNone(backends.resolve_download(backends.program("gsc"), "windows"))

    def test_install_for_another_platform_is_override_required_not_verified(self):
        from plutonium_agent_toolkit.core.receipts import inventory
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        backends_dir = root / "backends"
        (backends_dir / "gsc").mkdir(parents=True)
        (backends_dir / "gsc" / "gsc-tool.exe").write_bytes(b"GSC")
        (backends_dir / "receipts").mkdir(parents=True)
        other = "linux" if backends.platform_token() == "windows" else "windows"
        (backends_dir / "receipts" / "gsc.json").write_text(json.dumps(
            {"id": "gsc", "sha256": "x", "platform": other, "files": inventory(backends_dir / "gsc")}))
        res = backends.install(backends.program("gsc"), backends_dir, backends_dir / "cache")
        self.assertEqual(res["action"], "override-required", res)
        self.assertEqual(res["installed_for"], other)


if __name__ == "__main__":
    unittest.main()
