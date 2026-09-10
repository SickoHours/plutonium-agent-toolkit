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


class WeaponMalformedManifestTests(WeaponFixture):
    def test_malformed_manifest_shapes_are_structured_failures(self):
        manifest_path = self.donor / "capture-01" / "manifest.json"
        cases = {
            "not an object": "[]",
            "map_before not objects": json.dumps({"map_before": ["zm_zod"], "map_after": ["zm_zod"], "pid": 4242, "start_ticks": "99", "captured_bytes": 8192, "pages": {}, "models": [], "animations": [], "weapons": []}),
            "model row not object": json.dumps({"map_before": [{"name": "zm_zod"}], "map_after": [{"name": "zm_zod"}], "pid": 4242, "start_ticks": "99", "captured_bytes": 0, "pages": {}, "models": ["x"], "animations": [], "weapons": []}),
        }
        for label, text in cases.items():
            manifest_path.write_text(text)
            # re-seal the index so the manifest hash matches and the structural check is what fails
            index = json.loads((self.donor / "index.json").read_text())
            index["files"]["capture-01/manifest.json"] = sha(text.encode())
            index_bytes = json.dumps(index).encode()
            (self.donor / "index.json").write_bytes(index_bytes)
            r = json.loads(self.receipt.read_text())
            r["index_sha256"] = sha(index_bytes)
            self.receipt.write_text(json.dumps(r))
            code, row = invoke(["weapon", "catalog", str(self.receipt), "--capture", "capture-01/manifest.json", "--output", self.out()])
            self.assertEqual(code, 1, label)
            self.assertEqual(row["error_code"], "input_invalid", label)


class WeaponBoundsTests(unittest.TestCase):
    def test_page_bound_fits_inside_index_and_job_bounds(self):
        from plutonium_agent_toolkit.core.receipts import MAX_FILES
        from plutonium_agent_toolkit.dev import weapons

        self.assertLess(weapons.MAX_PAGES + 64, weapons.MAX_INDEX_FILES, "pages plus manifest and media must fit the index")
        # donor index + adapter index + receipt/index/manifest/adapter-index metadata must fit the Job cap
        self.assertLessEqual(weapons.MAX_INDEX_FILES + weapons.MAX_ADAPTER_FILES + 8, MAX_FILES,
                             "donor plus adapter files must fit the Job declared-input cap")


class WeaponElementTypeTests(WeaponFixture):
    def test_unhashable_elements_are_input_invalid_not_operation_failed(self):
        manifest_path = self.donor / "capture-01" / "manifest.json"
        m = json.loads(manifest_path.read_text())
        m["models"][0]["tags"] = [[]]
        text = json.dumps(m)
        manifest_path.write_text(text)
        index = json.loads((self.donor / "index.json").read_text())
        index["files"]["capture-01/manifest.json"] = sha(text.encode())
        index_bytes = json.dumps(index).encode()
        (self.donor / "index.json").write_bytes(index_bytes)
        r = json.loads(self.receipt.read_text())
        r["index_sha256"] = sha(index_bytes)
        self.receipt.write_text(json.dumps(r))
        code, row = invoke(["weapon", "catalog", str(self.receipt), "--capture", "capture-01/manifest.json", "--output", self.out()])
        self.assertEqual(row["error_code"], "input_invalid")
        # Recipe side: unhashable prefixes and required_files
        self.build_donor()
        code, row = invoke(["weapon", "catalog", str(self.receipt), "--capture", "capture-01/manifest.json", "--output", self.out()])
        library = Path(row["result"]["output"]) / "library.json"
        for field, value in (("keep_loaded_prefixes", [[]]), ("required_files", [{}])):
            code, row = invoke(["weapon", "plan", str(self.recipe(**{field: value})), "--library", str(library), "--output", self.out()])
            self.assertEqual(row["error_code"], "input_invalid", field)


class WeaponReceiptFieldTests(WeaponFixture):
    def test_adapter_fields_must_come_together_and_no_unknown_fields(self):
        r = json.loads(self.receipt.read_text())
        r["adapter_index_sha256"] = "0" * 64
        self.receipt.write_text(json.dumps(r))
        code, row = invoke(["weapon", "catalog", str(self.receipt), "--capture", "capture-01/manifest.json", "--output", self.out()])
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("together", row["message"])
        r = json.loads(self.receipt.read_text())
        del r["adapter_index_sha256"]
        r["typo_field"] = 1
        self.receipt.write_text(json.dumps(r))
        code, row = invoke(["weapon", "catalog", str(self.receipt), "--capture", "capture-01/manifest.json", "--output", self.out()])
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("unknown fields", row["message"])


class WeaponMalformedInputFuzzTests(WeaponFixture):
    """Every malformed shape must come back as a structured input failure, never operation_failed."""

    STRUCTURED = {"input_invalid", "input_changed", "input_missing", "input_limit"}

    def reseal(self, manifest_obj):
        text = json.dumps(manifest_obj)
        (self.donor / "capture-01" / "manifest.json").write_text(text)
        index = json.loads((self.donor / "index.json").read_text())
        index["files"]["capture-01/manifest.json"] = sha(text.encode())
        index_bytes = json.dumps(index).encode()
        (self.donor / "index.json").write_bytes(index_bytes)
        r = json.loads(self.receipt.read_text())
        r["index_sha256"] = sha(index_bytes)
        self.receipt.write_text(json.dumps(r))

    def test_receipt_shapes(self):
        base = json.loads(self.receipt.read_text())
        for label, mutate in {
            "root not str": lambda r: r.update(root=123),
            "root list": lambda r: r.update(root=["x"]),
            "index not str": lambda r: r.update(index={}),
            "index_sha not str": lambda r: r.update(index_sha256=5),
            "map not str": lambda r: r.update(map=None),
            "pid weird": lambda r: r.update(pid={"a": 1}),
            "adapter_index only": lambda r: r.update(adapter_index="x.json"),
            "adapter_index not str": lambda r: r.update(adapter_index=1, adapter_index_sha256="0" * 64),
        }.items():
            r = dict(base)
            mutate(r)
            self.receipt.write_text(json.dumps(r))
            code, row = invoke(["weapon", "catalog", str(self.receipt), "--capture", "capture-01/manifest.json", "--output", self.out()])
            self.assertIn(row.get("error_code"), self.STRUCTURED, f"{label}: {row.get('error_code')} {row.get('message')}")
        self.receipt.write_text(json.dumps(base))

    def test_manifest_shapes(self):
        good = json.loads((self.donor / "capture-01" / "manifest.json").read_text())
        for label, mutate in {
            "pages list": lambda m: m.update(pages=[]),
            "pages value obj": lambda m: m["pages"].update({f"{8192:016x}.bin": {}}),
            "captured_bytes str": lambda m: m.update(captured_bytes="x"),
            "models not list": lambda m: m.update(models={}),
            "model name int": lambda m: m["models"][0].update(name=5),
            "tags not list": lambda m: m["models"][0].update(tags="j_root"),
            "tags nested": lambda m: m["models"][0].update(tags=[["a"]]),
            "lods not list": lambda m: m["models"][0].update(lods={}),
            "lod materials not list": lambda m: m["models"][0].update(lods=[{"materials": "x"}]),
            "lod material int": lambda m: m["models"][0].update(lods=[{"materials": [1]}]),
            "animation row str": lambda m: m.update(animations=["x"]),
            "map_before dict": lambda m: m.update(map_before={}, map_after={}),
            "map_before name int": lambda m: m.update(map_before=[{"name": 1}], map_after=[{"name": 1}]),
        }.items():
            m = json.loads(json.dumps(good))
            mutate(m)
            self.reseal(m)
            code, row = invoke(["weapon", "catalog", str(self.receipt), "--capture", "capture-01/manifest.json", "--output", self.out()])
            self.assertIn(row.get("error_code"), self.STRUCTURED, f"{label}: {row.get('error_code')} {row.get('message')}")

    def test_recipe_and_library_shapes(self):
        code, row = invoke(["weapon", "catalog", str(self.receipt), "--capture", "capture-01/manifest.json", "--output", self.out()])
        library = Path(row["result"]["output"]) / "library.json"
        good = json.loads(self.recipe().read_text())
        for label, mutate in {
            "variants scalar": lambda r: r.update(variants=["a", "b"]),
            "variant missing role": lambda r: r["variants"][0].pop("role"),
            "variant role int": lambda r: r["variants"][0].update(role=1),
            "clips list": lambda r: r["variants"][0].update(clips=["idle"]),
            "clip value int": lambda r: r["variants"][0]["clips"].update(idle=1),
            "family int": lambda r: r.update(family=1),
            "adapter list": lambda r: r.update(adapter=[]),
            "menu_route int": lambda r: r.update(menu_route=1),
            "cap str": lambda r: r.update(resident_cap_bytes="1"),
            "prefixes str": lambda r: r.update(keep_loaded_prefixes="ar_"),
            "required_files str": lambda r: r.update(required_files="a.wav"),
            "extra field": lambda r: r.update(extra=1),
            "schema str": lambda r: r.update(schema="1"),
        }.items():
            r = json.loads(json.dumps(good))
            mutate(r)
            p = self.root / f"fuzz-{label.replace(' ', '_')}.json"
            p.write_text(json.dumps(r))
            code, row = invoke(["weapon", "plan", str(p), "--library", str(library), "--output", self.out()])
            self.assertIn(row.get("error_code"), self.STRUCTURED, f"{label}: {row.get('error_code')} {row.get('message')}")
        for label, lib in {
            "library list": [],
            "library null fields": {"donor_receipt": None, "capture": []},
            "library missing capture": {"donor_receipt": "x"},
        }.items():
            bad = self.root / f"lib-{label.replace(' ', '_')}.json"
            bad.write_text(json.dumps(lib))
            code, row = invoke(["weapon", "plan", str(self.recipe()), "--library", str(bad), "--output", self.out()])
            self.assertIn(row.get("error_code"), self.STRUCTURED, f"{label}: {row.get('error_code')} {row.get('message')}")


class WeaponIdentityTests(WeaponFixture):
    def reseal(self, manifest_obj, receipt_mutation):
        text = json.dumps(manifest_obj)
        (self.donor / "capture-01" / "manifest.json").write_text(text)
        index = json.loads((self.donor / "index.json").read_text())
        index["files"]["capture-01/manifest.json"] = sha(text.encode())
        index_bytes = json.dumps(index).encode()
        (self.donor / "index.json").write_bytes(index_bytes)
        receipt = json.loads(self.receipt.read_text())
        receipt["index_sha256"] = sha(index_bytes)
        receipt_mutation(receipt)
        self.receipt.write_text(json.dumps(receipt))

    def test_missing_or_invalid_process_identity_never_matches_by_accident(self):
        good = json.loads((self.donor / "capture-01" / "manifest.json").read_text())
        cases = (
            ("both missing pid", lambda d: d.pop("pid", None)),
            ("both missing ticks", lambda d: d.pop("start_ticks", None)),
            ("both None pid", lambda d: d.update(pid=None)),
            ("both zero pid", lambda d: d.update(pid=0)),
            ("both bool pid", lambda d: d.update(pid=True)),
            ("both empty ticks", lambda d: d.update(start_ticks="")),
            ("both bool ticks", lambda d: d.update(start_ticks=True)),
        )
        for label, mutate in cases:
            manifest = json.loads(json.dumps(good))
            mutate(manifest)
            self.build_donor()                      # restore a clean receipt, then mutate both documents the same way
            self.reseal(manifest, mutate)
            code, row = invoke(["weapon", "catalog", str(self.receipt), "--capture", "capture-01/manifest.json", "--output", self.out()])
            self.assertEqual(code, 1, label)
            self.assertEqual(row["error_code"], "input_invalid", f"{label}: {row.get('message')}")
