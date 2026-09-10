"""Backend pin and archive-safety tests. Offline; uses synthetic zip and tar archives."""
import io
import json
import os
import stat
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from plutonium_agent_toolkit.core.errors import Failure
from plutonium_agent_toolkit.dev import backends

PLATFORMS = ("windows", "linux")


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

    def test_per_platform_downloads_are_well_formed(self):
        # Every downloads.<token> entry is a complete pin: HTTPS URL with a known archive suffix,
        # 64-hex SHA-256, positive byte count, and Linux binaries never named *.exe.
        for p in backends.pins()["programs"]:
            for token, dl in (p.get("downloads") or {}).items():
                self.assertIn(token, PLATFORMS, f"{p['id']}: unknown platform token {token}")
                self.assertTrue(dl["url"].startswith("https://"), p["id"])
                backends.archive_suffix(dl["url"])
                self.assertRegex(dl["sha256"], r"^[0-9a-f]{64}$", p["id"])
                self.assertGreater(dl["bytes"], 0, p["id"])
                self.assertIsInstance(dl.get("strip_root", False), bool)
                if token == "linux":
                    for rel in dl.get("provides", []):
                        self.assertFalse(rel.lower().endswith(".exe"), f"{p['id']}: {rel}")
                if "links" in dl:
                    self.assertEqual(dl["links"], "copy", p["id"])

    def test_required_and_media_backends_are_pinned_for_linux(self):
        # The Linux pins the toolkit claims in docs/SUPPORT.md. Not darwin: nothing is pinned there.
        for pid in ("gsc", "oat", "ffmpeg", "blender"):
            self.assertIsNotNone(backends.resolve_download(backends.program(pid), "linux"), pid)
            self.assertIsNone(backends.resolve_download(backends.program(pid), "darwin"), pid)
        for pid in ("lua", "greyhound", "husky", "c2m"):
            self.assertIsNone(backends.resolve_download(backends.program(pid), "linux"), pid)

    def test_linux_provides_match_the_executable_table(self):
        # doctor and executable() resolve a binary at relative(name, "linux"); the pin's provides
        # must name the same path so setup marks it executable and doctor finds it.
        for name, (pid, _win) in backends.EXECUTABLES.items():
            item = backends.program(pid)
            if backends.resolve_download(item, "linux") is None:
                continue
            self.assertIn(backends.relative(name, "linux"), backends.provides_for(item, "linux"), name)

    def test_archive_suffix_is_derived_from_the_url(self):
        self.assertEqual(backends.archive_suffix("https://x/y/oat-linux.tar.gz"), ".tar.gz")
        self.assertEqual(backends.archive_suffix("https://x/y/ffmpeg-linux64.tar.xz"), ".tar.xz")
        self.assertEqual(backends.archive_suffix("https://x/y/windows-x64-release.zip"), ".zip")
        self.assertEqual(backends.archive_suffix("https://x/y/tool.TGZ?download=1"), ".tgz")
        with self.assertRaises(Failure):
            backends.archive_suffix("https://x/y/tool.7z")

    def test_relative_paths_per_platform(self):
        self.assertEqual(backends.relative("linker", "windows"), "Linker.exe")
        self.assertEqual(backends.relative("linker", "linux"), "Linker")
        self.assertEqual(backends.relative("ffprobe", "linux"), "bin/ffprobe")
        self.assertEqual(backends.provides_for(backends.program("oat"), "windows"), ["Linker.exe", "Unlinker.exe", "ImageConverter.exe"])
        self.assertEqual(backends.provides_for(backends.program("oat"), "linux"), ["Linker", "Unlinker", "ImageConverter"])


def make_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries:
            z.writestr(name, data)
    return buf.getvalue()


def make_tar(entries, compression="gz"):
    """entries: (name, data | None for a directory, mode, linkname | None)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode=f"w:{compression}") as t:
        for name, data, mode, link in entries:
            info = tarfile.TarInfo(name)
            info.mode = mode
            if link is not None:
                info.type = tarfile.SYMTYPE
                info.linkname = link
                t.addfile(info)
            elif data is None:
                info.type = tarfile.DIRTYPE
                t.addfile(info)
            else:
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
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

    def write_tar(self, name, entries, compression="gz"):
        p = self.root / name
        p.write_bytes(make_tar(entries, compression))
        return p

    def dest(self, label):
        d = self.root / f"dest-{label}"
        d.mkdir()
        return d

    def test_extracts_and_strips_single_root(self):
        archive = self.write("ok.zip", [("tool/bin/a.exe", b"A"), ("tool/readme.txt", b"R")])
        dest = self.dest("ok")
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
            with self.assertRaises(Failure, msg=label):
                backends.safe_extract(archive, self.dest(label))

    # ----- tar: the same guarantees as zip -----

    def test_tar_gz_and_tar_xz_extract_with_modes_and_strip_root(self):
        for compression, suffix in (("gz", ".tar.gz"), ("xz", ".tar.xz")):
            archive = self.write_tar("ok" + suffix, [
                ("tool", None, 0o755, None),
                ("tool/bin", None, 0o755, None),
                ("tool/bin/ffmpeg", b"FF", 0o755, None),
                ("tool/LICENSE.txt", b"L", 0o644, None),
            ], compression)
            dest = self.dest("ok-" + compression)
            backends.safe_extract(archive, dest, strip_root=True)
            self.assertEqual((dest / "bin" / "ffmpeg").read_bytes(), b"FF")
            self.assertEqual((dest / "LICENSE.txt").read_bytes(), b"L")
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE((dest / "bin" / "ffmpeg").stat().st_mode), 0o755)
                self.assertEqual(stat.S_IMODE((dest / "LICENSE.txt").stat().st_mode), 0o644)

    def test_tar_dot_root_entry_is_the_destination(self):
        # gsc-tool's Linux archive is `./` plus `./gsc-tool` (made with `tar -C dir .`).
        archive = self.write_tar("dot.tar.gz", [("./", None, 0o755, None), ("./gsc-tool", b"G", 0o644, None)])
        dest = self.dest("dot")
        backends.safe_extract(archive, dest)
        self.assertEqual((dest / "gsc-tool").read_bytes(), b"G")

    def test_tar_refuses_traversal_absolute_links_and_two_roots(self):
        cases = {
            "traversal": ([("../evil", b"x", 0o644, None)], {}),
            "absolute": ([("/abs", b"x", 0o644, None)], {}),
            "symlink": ([("tool/lib.so", b"x", 0o644, None), ("tool/link.so", None, 0o777, "lib.so")], {}),
            "two-roots": ([("a/x", b"x", 0o644, None), ("b/y", b"y", 0o644, None)], {"strip_root": True}),
            "collision": ([("A.txt", b"x", 0o644, None), ("a.txt", b"y", 0o644, None)], {}),
            "reserved": ([("NUL", b"x", 0o644, None)], {}),
        }
        for label, (entries, kwargs) in cases.items():
            archive = self.write_tar(f"{label}.tar.gz", entries)
            with self.assertRaises(Failure, msg=label):
                backends.safe_extract(archive, self.dest(label), **kwargs)

    def test_tar_refuses_declared_sizes_over_the_limit(self):
        archive = self.write_tar("big.tar.gz", [("a", b"x", 0o644, None)])
        with mock.patch.object(backends, "MAX_UNPACKED", 0):
            with self.assertRaises(Failure) as ctx:
                backends.safe_extract(archive, self.dest("big"))
        self.assertEqual(ctx.exception.code, "input_limit")

    def test_tar_refuses_a_member_that_grows_beyond_its_declared_size(self):
        # A crafted header can under-declare; the reader copies at most the declared size and
        # must notice any extra bytes rather than write them.
        archive = self.write_tar("grow.tar.gz", [("a", b"0123456789", 0o644, None)])
        real_open = backends._TarReader.open

        def lying_open(self, member):
            member.size = 4
            return real_open(self, member)

        with mock.patch.object(backends._TarReader, "open", lying_open):
            with self.assertRaises(Failure) as ctx:
                backends.safe_extract(archive, self.dest("grow"))
        self.assertEqual(ctx.exception.code, "input_limit")

    def test_tar_links_are_copied_only_when_the_pin_allows_and_only_inside_the_archive(self):
        # Blender's Linux build: lib/libfoo.so -> libfoo.so.1 -> libfoo.so.1.2.3. With links="copy"
        # each link becomes a copy of the resolved regular file; anything escaping is refused.
        archive = self.write_tar("links.tar.xz", [
            ("blender", None, 0o755, None),
            ("blender/lib", None, 0o755, None),
            ("blender/lib/libfoo.so.1.2.3", b"FOO", 0o755, None),
            ("blender/lib/libfoo.so.1", None, 0o777, "libfoo.so.1.2.3"),
            ("blender/lib/libfoo.so", None, 0o777, "libfoo.so.1"),
        ], "xz")
        dest = self.dest("links")
        backends.safe_extract(archive, dest, strip_root=True, links="copy")
        for name in ("libfoo.so.1.2.3", "libfoo.so.1", "libfoo.so"):
            p = dest / "lib" / name
            self.assertFalse(p.is_symlink(), name)
            self.assertEqual(p.read_bytes(), b"FOO", name)
        with self.assertRaises(Failure):
            backends.safe_extract(archive, self.dest("links-refused"), strip_root=True)
        escapes = {
            "up": [("lib/x.so", None, 0o777, "../../etc/passwd")],
            "abs": [("lib/x.so", None, 0o777, "/etc/passwd")],
            "dangling": [("lib/x.so", None, 0o777, "missing.so")],
            "to-dir": [("lib", None, 0o755, None), ("x", None, 0o777, "lib")],
            "cycle": [("a", None, 0o777, "b"), ("b", None, 0o777, "a")],
        }
        for label, entries in escapes.items():
            archive = self.write_tar(f"escape-{label}.tar.gz", entries)
            with self.assertRaises(Failure, msg=label):
                backends.safe_extract(archive, self.dest("escape-" + label), links="copy")

    def test_mark_executable_only_touches_declared_binaries(self):
        if os.name == "nt":
            self.skipTest("POSIX modes")
        root = self.dest("mark")
        (root / "gsc-tool").write_bytes(b"G")
        (root / "readme").write_bytes(b"R")
        os.chmod(root / "gsc-tool", 0o644)
        os.chmod(root / "readme", 0o644)
        self.assertEqual(backends.mark_executable(root, ["gsc-tool", "absent"]), ["gsc-tool"])
        self.assertTrue(stat.S_IMODE((root / "gsc-tool").stat().st_mode) & 0o111)
        self.assertFalse(stat.S_IMODE((root / "readme").stat().st_mode) & 0o111)
        self.assertEqual(backends.mark_executable(root, ["gsc-tool"]), [], "already executable")

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

    def test_install_from_tar_caches_under_the_real_suffix_and_marks_executables(self):
        archive_bytes = make_tar([("./", None, 0o755, None), ("./gsc-tool", b"GSC", 0o644, None)])
        sha = backends.hashlib.sha256(archive_bytes).hexdigest()
        token = backends.platform_token()
        item = {"id": "gsc", "name": "gsc-tool", "optional": False, "license": "GPL-3.0",
                "downloads": {token: {"url": "https://example.invalid/linux-amd64-release.tar.gz", "sha256": sha,
                                      "strip_root": False, "provides": ["gsc-tool"]}}}
        cache = self.root / "cache"
        cache.mkdir()
        (cache / f"gsc-{sha[:12]}.tar.gz").write_bytes(archive_bytes)
        backends_dir = self.root / "backends"
        with mock.patch.object(backends, "resolve_download", wraps=backends.resolve_download):
            result = backends.install(item, backends_dir, cache)
        self.assertEqual(result["action"], "installed", result)
        binary = backends_dir / "gsc" / "gsc-tool"
        self.assertEqual(binary.read_bytes(), b"GSC")
        receipt = json.loads((backends_dir / "receipts" / "gsc.json").read_text())
        self.assertEqual(receipt["platform"], token)
        if os.name != "nt":
            self.assertTrue(stat.S_IMODE(binary.stat().st_mode) & 0o111)
            self.assertEqual(receipt["executables_marked"], ["gsc-tool"])
        self.assertEqual(backends.install(item, backends_dir, cache)["action"], "verified")


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
        self.assertIsNone(backends.resolve_download(backends.program("lua"), "linux"))
        self.assertIsNotNone(backends.resolve_download(backends.program("gsc"), "windows"))
        self.assertIsNotNone(backends.resolve_download(backends.program("gsc"), "linux"))

    def test_darwin_is_named_untested_by_plan_setup_and_doctor(self):
        # macOS has no pins and no claim. The JSON says so instead of silently listing
        # override-required rows; a pinned platform carries no such note.
        self.assertIsNone(backends.platform_note("linux"))
        self.assertIsNone(backends.platform_note("windows"))
        self.assertIn("untested", backends.platform_note("darwin"))
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {"PAT_HOME": temp}), \
                mock.patch.object(backends, "platform_token", return_value="darwin"):
            plan = backends.setup(only=["gsc", "cast"], plan=True)
            self.assertEqual(plan["platform"], "darwin")
            self.assertIn("untested", plan["note"].lower())
            by_id = {p["id"]: p for p in plan["programs"]}
            self.assertFalse(by_id["gsc"]["download_available"])
            self.assertTrue(by_id["cast"]["download_available"], "pure-Python add-on installs anywhere")
            report = backends.doctor()
            self.assertIn("untested", report["note"].lower())
            self.assertFalse(next(r for r in report["backends"] if r["id"] == "gsc")["download_available"])
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {"PAT_HOME": temp}), \
                mock.patch.object(backends, "platform_token", return_value="linux"):
            self.assertNotIn("note", backends.setup(only=["gsc"], plan=True))
            self.assertNotIn("note", backends.doctor())

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
