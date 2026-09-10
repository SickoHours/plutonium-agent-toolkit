"""weapon catalog / plan with a synthetic sealed donor. Offline; no converter."""
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


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class WeaponFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        os.environ["PAT_HOME"] = str(self.root / "home")
        self.addCleanup(lambda: os.environ.pop("PAT_HOME", None))
        self.donor = self.root / "donor"
        (self.donor / "capture-01").mkdir(parents=True)
        self.n = 0
        self.build_donor()

    def out(self):
        self.n += 1
        return str(self.root / f"job-{self.n:03d}")

    def build_donor(self, page_bytes=4096, drop_pap_clip=False, duplicate=False):
        pages = {}
        files = {}
        for i in range(2):
            name = f"{i * 4096:016x}.bin"
            data = bytes([i]) * page_bytes
            (self.donor / "capture-01" / name).write_bytes(data)
            pages[name] = sha(data)
            files[f"capture-01/{name}"] = sha(data)
        animations = [{"name": "viewmodel_ar_idle"}, {"name": "viewmodel_ar_fire"}, {"name": "viewmodel_ar_reload"}]
        if not drop_pap_clip:
            animations.append({"name": "viewmodel_ar_reload_upgraded"})
        if duplicate:
            animations.append({"name": "viewmodel_ar_idle"})
        manifest = {"map_before": [{"name": "zm_zod"}], "map_after": [{"name": "zm_zod"}], "pid": 4242, "start_ticks": "99",
                    "captured_bytes": len(pages) * 4096, "pages": pages,
                    "models": [{"name": "c_zom_hands", "tags": ["j_root", "j_hand"], "lods": [{"materials": ["mtl_hands"]}]},
                               {"name": "t7_weapon_ar_view", "tags": ["tag_origin", "tag_weapon"], "lods": []},
                               {"name": "t7_weapon_ar_world", "tags": ["tag_origin"], "lods": []}],
                    "animations": animations,
                    "weapons": [{"name": "ar_standard"}, {"name": "ar_standard_upgraded"}]}
        data = json.dumps(manifest).encode()
        (self.donor / "capture-01" / "manifest.json").write_bytes(data)
        files["capture-01/manifest.json"] = sha(data)
        (self.donor / "sounds").mkdir(exist_ok=True)
        (self.donor / "sounds" / "fire.wav").write_bytes(b"RIFF")
        files["sounds/fire.wav"] = sha(b"RIFF")
        index = json.dumps({"files": files}).encode()
        (self.donor / "index.json").write_bytes(index)
        self.receipt = self.root / "donor.json"
        self.receipt.write_text(json.dumps({"root": str(self.donor), "index": "index.json", "index_sha256": sha(index),
                                            "map": "zm_zod", "pid": 4242, "start_ticks": "99"}))

    def recipe(self, **overrides):
        base = {
            "schema": 1, "family": "ar-standard", "source_engine": "t7", "target_engine": "t6",
            "adapter": "example/weapon_port", "hands_model": "c_zom_hands",
            "variants": [
                {"role": "normal", "source_weapon": "ar_standard", "target_weapon": "t6_ar_standard", "view_model": "t7_weapon_ar_view",
                 "world_model": "t7_weapon_ar_world", "clips": {"idle": "viewmodel_ar_idle", "fire": "viewmodel_ar_fire", "reload": "viewmodel_ar_reload"},
                 "native_template": "ar_template", "inventory_type": "primary"},
                {"role": "pap", "source_weapon": "ar_standard_upgraded", "target_weapon": "t6_ar_standard_upgraded", "view_model": "t7_weapon_ar_view",
                 "world_model": "t7_weapon_ar_world", "clips": {"idle": "viewmodel_ar_idle", "fire": "viewmodel_ar_fire", "reload": "viewmodel_ar_reload_upgraded"},
                 "native_template": "ar_template", "inventory_type": "primary"},
            ],
            "required_files": ["sounds/fire.wav"], "keep_loaded_prefixes": ["ar_std_"], "resident_cap_bytes": 1024 * 1024,
            "menu_route": "Weapons > AR",
        }
        base.update(overrides)
        p = self.root / f"recipe-{self.n}.json"
        p.write_text(json.dumps(base))
        return p


class WeaponTests(WeaponFixture):
    def test_catalog_then_plan_reports_ready(self):
        code, row = invoke(["weapon", "catalog", str(self.receipt), "--capture", "capture-01/manifest.json", "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["counts"], {"models": 3, "animations": 4, "weapons": 2})
        library = Path(row["result"]["output"]) / "library.json"
        code, row = invoke(["weapon", "plan", str(self.recipe()), "--library", str(library), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertTrue(row["result"]["declared_inputs_available"])
        self.assertEqual(row["result"]["native_templates"], {"ar_template": "owning_builder_required"})
        self.assertFalse(row["result"]["gameplay_accepted"])

    def test_missing_pap_clip_is_reported_not_hidden(self):
        self.build_donor(drop_pap_clip=True)
        code, row = invoke(["weapon", "catalog", str(self.receipt), "--capture", "capture-01/manifest.json", "--output", self.out()])
        library = Path(row["result"]["output"]) / "library.json"
        code, row = invoke(["weapon", "plan", str(self.recipe()), "--library", str(library), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertFalse(row["result"]["declared_inputs_available"])
        self.assertEqual(row["result"]["missing"]["animations"], ["viewmodel_ar_reload_upgraded"])

    def test_altered_page_and_short_page_fail_catalog(self):
        page = self.donor / "capture-01" / f"{0:016x}.bin"
        page.write_bytes(b"\xff" * 4096)
        code, row = invoke(["weapon", "catalog", str(self.receipt), "--capture", "capture-01/manifest.json", "--output", self.out()])
        self.assertEqual(row["error_code"], "input_changed")
        self.build_donor(page_bytes=4000)
        code, row = invoke(["weapon", "catalog", str(self.receipt), "--capture", "capture-01/manifest.json", "--output", self.out()])
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("snapshot page", row["message"])

    def test_duplicate_names_and_identity_mismatch_fail(self):
        self.build_donor(duplicate=True)
        code, row = invoke(["weapon", "catalog", str(self.receipt), "--capture", "capture-01/manifest.json", "--output", self.out()])
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("duplicate animations", row["message"])
        self.build_donor()
        r = json.loads(self.receipt.read_text())
        r["pid"] = 1
        self.receipt.write_text(json.dumps(r))
        code, row = invoke(["weapon", "catalog", str(self.receipt), "--capture", "capture-01/manifest.json", "--output", self.out()])
        self.assertIn("process identity", row["message"])

    def test_stale_library_is_rejected_by_plan(self):
        code, row = invoke(["weapon", "catalog", str(self.receipt), "--capture", "capture-01/manifest.json", "--output", self.out()])
        library = Path(row["result"]["output"]) / "library.json"
        (self.donor / "sounds" / "fire.wav").write_bytes(b"RIFF2")
        code, row = invoke(["weapon", "plan", str(self.recipe()), "--library", str(library), "--output", self.out()])
        self.assertEqual(row["error_code"], "input_changed")

    def test_recipe_validation(self):
        code, row = invoke(["weapon", "catalog", str(self.receipt), "--capture", "capture-01/manifest.json", "--output", self.out()])
        library = Path(row["result"]["output"]) / "library.json"
        bad_left = self.recipe()
        r = json.loads(bad_left.read_text())
        r["variants"][0]["inventory_type"] = "dwlefthand"
        bad_left.write_text(json.dumps(r))
        code, row = invoke(["weapon", "plan", str(bad_left), "--library", str(library), "--output", self.out()])
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("Left hand", row["message"])
        code, row = invoke(["weapon", "plan", str(self.recipe(resident_cap_bytes=64 * 1024**2)), "--library", str(library), "--output", self.out()])
        self.assertIn("16 MiB", row["message"])
        code, row = invoke(["weapon", "plan", str(self.recipe(required_files=["../escape.wav"])), "--library", str(library), "--output", self.out()])
        self.assertEqual(row["error_code"], "input_invalid")
        code, row = invoke(["weapon", "plan", str(self.recipe(keep_loaded_prefixes=["x"])), "--library", str(library), "--output", self.out()])
        self.assertIn("Resident prefix", row["message"])
