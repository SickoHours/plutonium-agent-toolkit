"""Adapter recipes as the third payload; sound banks as a bound; service refusals; refusals as data."""
import json
import os
from pathlib import Path

from tests.test_compositions import CompositionFixture, declaration
from tests.test_dev_routes import FAKES, invoke


class AdapterFixture(CompositionFixture):
    def setUp(self):
        super().setUp()
        os.environ["PAT_BACKEND_ADAPTER_BUILDER"] = str(FAKES / "fake_adapter_builder.py")
        self.addCleanup(lambda: os.environ.pop("PAT_BACKEND_ADAPTER_BUILDER", None))

    def adapter(self, mid, weapons=("halo_gum_x_eat_zm",), bank="halo_gum_x.all", rawfiles=(), localize=None, aliases=("hsp_s_shared",), prepared=True, **overrides):
        d = self.root / "modules" / mid
        (d / "src").mkdir(parents=True, exist_ok=True)
        (d / "src" / f"{mid}.gsc").write_text("main()\n{\n}\n")
        recipe = {"schema": 1, "adapter": mid, "module": mid, "id": mid, "revision": "stock-v1", "foundation": "bo2-stock", "map": "zm_transit",
                  "profile": f"stock_{mid}_test", "weapons": list(weapons), "weapon": weapons[0] if weapons else None,
                  "loose_script": {"source": f"src/{mid}.gsc", "target": f"scripts/zm/halo_{mid}.gsc", "instance": "server"},
                  "localize": localize if localize is not None else {mid.upper(): mid}, "rawfiles": list(rawfiles),
                  "assets": {"weapons": list(weapons), "xmodel": [f"{mid}_view"], "materials": [], "images": []}, "resource_contract": {}}
        if bank:
            recipe["soundbank"] = {"name": bank, "aliases": "soundbank/new.aliases.csv", "sounds": "sound/x"}
        if prepared:
            prep = self.root / "prepared" / mid
            (prep / "assets" / "soundbank").mkdir(parents=True, exist_ok=True)
            (prep / "assets" / "soundbank" / "new.aliases.csv").write_text("Name,FileSource,Storage\n" + "".join(f"{a},raw/sound/x/{a}.wav,loaded\n" for a in aliases))
            (prep / "prepared.json").write_text(json.dumps({"entries": [{"id": w, "clips": {"idle": f"{mid}_idle"}} for w in weapons]}))
            recipe["prepared"] = str(prep)
        (d / "recipe.json").write_text(json.dumps(recipe, indent=2))
        decl = declaration(mid, recipe="recipe.json", category="gobblegums", distribution="private", **overrides)
        (d / "module.json").write_text(json.dumps(decl, indent=2))
        return d


class AdapterPayloadTests(AdapterFixture):
    def test_plan_reads_an_adapter_recipe_as_a_third_payload(self):
        self.adapter("gum_a", rawfiles=["animtrees/halo_gum.atr"])
        code, row = invoke(["module", "plan", str(self.composition(["gum_a"], name="stock_adapter_test")), "--output", self.out()])
        self.assertEqual(code, 0, row)
        member = row["result"]["modules"][0]
        self.assertEqual(member["payload"], "adapter")
        self.assertEqual(row["result"]["adapters"], 1)
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        adapter = plan["adapters"][0]
        self.assertIn("weapon,halo_gum_x_eat_zm", adapter["roots"]); self.assertIn("soundbank,halo_gum_x.all", adapter["roots"])
        self.assertIn("xanim,gum_a_idle", adapter["roots"], "clips come from the prepared record when it is on this machine")
        self.assertEqual(adapter["aliases"], ["hsp_s_shared"])
        self.assertEqual(plan["modules"][0]["provides"]["soundbanks"], ["halo_gum_x.all"])
        self.assertEqual(plan["modules"][0]["provides"]["weapons"], ["halo_gum_x_eat_zm"])
        self.assertEqual(row["result"]["footprint"]["gum_a"], {"rawfiles": 1, "soundbanks": ["halo_gum_x.all"], "scripts": 0})
        self.assertIn("adapter_builder", [c["id"] for c in row["result"]["backends"]])

    def test_a_declaration_may_narrow_but_not_widen_the_recipe_outputs(self):
        self.adapter("gum_a", provides={"weapons": ["other_zm"]})
        code, row = invoke(["module", "plan", str(self.composition(["gum_a"], name="stock_adapter_test")), "--output", self.out()])
        self.assertEqual(code, 1, row); self.assertIn("does not deliver", row["message"])

    def test_build_runs_the_workspace_builder_reads_the_package_back_and_links_against_it(self):
        self.adapter("gum_a", rawfiles=["animtrees/halo_gum.atr"])
        self.module("hud")
        comp = self.composition(["gum_a", "hud"], name="stock_adapter_test")
        code, row = invoke(["module", "build", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertEqual(result["adapters"][0]["id"], "gum_a"); self.assertEqual(result["adapters"][0]["soundbanks"], ["halo_gum_x.all.sabl"])
        self.assertEqual(result["seed_roots_verified"], result["adapters"][0]["roots"])
        self.assertIn("halo_gum_x.all.sabl", result["soundbanks"])
        self.assertIn("scripts/zm/halo_gum_a.gsc", result["loose_scripts"], "the adapter's loose script travels beside the package")
        self.assertIn("scripts/zm/hud.gsc", result["loose_scripts"])
        receipt = json.loads((Path(result["output"]) / "receipt.json").read_text())
        self.assertTrue(any(step["argv"][-2:] == ["--output", str(Path(result["output"]) / "adapters" / "gum_a")] for step in receipt["steps"]), "builder step recorded")
        package = json.loads((Path(result["output"]) / "packages" / "mod.ff").read_text())
        self.assertIn("weapon,halo_gum_x_eat_zm", package["assets"])
        self.assertIn("animtrees/halo_gum.atr", package["rawfiles"])

    def test_build_refuses_a_builder_that_fails_or_writes_nothing(self):
        for mid, want in (("broken", "status succeeded"), ("silent", "no build.json")):
            self.adapter(mid)
            code, row = invoke(["module", "build", str(self.composition([mid], name=f"stock_{mid}_test")), "--output", self.out()])
            self.assertEqual(code, 1, row); self.assertIn(want, row["message"])

    def test_build_without_a_builder_refuses_before_linking(self):
        self.adapter("gum_a")
        os.environ.pop("PAT_BACKEND_ADAPTER_BUILDER", None)
        code, row = invoke(["module", "plan", str(self.composition(["gum_a"], name="stock_adapter_test")), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertFalse(row["result"]["backends_available"])
        code, row = invoke(["module", "build", str(self.composition(["gum_a"], name="stock_adapter_test")), "--output", self.out()])
        self.assertEqual(code, 1, row); self.assertEqual(row["error_code"], "backend_unavailable"); self.assertIn("adapter_builder", row["message"])

    def test_workspace_toolchain_builder_is_found_without_an_override(self):
        self.adapter("gum_a")
        os.environ.pop("PAT_BACKEND_ADAPTER_BUILDER", None)
        (self.root / "toolchain").mkdir()
        (self.root / "toolchain" / "pat-adapter-build.py").write_bytes((FAKES / "fake_adapter_builder.py").read_bytes())
        code, row = invoke(["module", "build", str(self.composition(["gum_a"], name="stock_adapter_test")), "--workspace", str(self.root), "--output", self.out()])
        self.assertEqual(code, 0, row)

    def test_two_adapters_shipping_the_same_rawfile_are_a_decision_and_the_same_weapon_too(self):
        self.adapter("gum_a", rawfiles=["animtrees/shared.atr"], aliases=("a",))
        self.adapter("gum_b", rawfiles=["animtrees/shared.atr"], weapons=("halo_gum_x_eat_zm",), bank="halo_gum_y.all", aliases=("b",))
        code, row = invoke(["module", "plan", str(self.composition(["gum_a", "gum_b"], name="stock_two_test")), "--output", self.out()])
        self.assertEqual(code, 1, row)
        kinds = {r["kind"] for r in row["details"]["refusals"]}
        self.assertEqual(kinds, {"service"})


class SoundBankBoundTests(CompositionFixture):
    def bank_module(self, mid, bank):
        d = self.module(mid)
        (d / "soundbank").mkdir(exist_ok=True)
        (d / "soundbank" / f"{bank}.aliases.csv").write_text(f"Name,FileSource\n{mid}_alias,raw/sound/{mid}.wav\n")
        recipe = json.loads((d / "project.json").read_text())
        recipe["assets"] = [{"source": f"soundbank/{bank}.aliases.csv", "target": f"soundbank/{bank}.aliases.csv", "type": "soundbank", "name": bank}]
        (d / "project.json").write_text(json.dumps(recipe))
        decl = json.loads((d / "module.json").read_text()); decl["provides"] = {"soundbanks": [bank]}
        (d / "module.json").write_text(json.dumps(decl))
        return d

    def test_sound_banks_are_a_counted_bound_with_one_companion_per_all_bank(self):
        ids = [f"gum_{i:02d}" for i in range(11)]
        for mid in ids:
            self.bank_module(mid, f"halo_{mid}.all")
        # TranZit carries 4 banks: with companions 8; 11 banks + 11 companions = 22; 30 of 32 passes.
        code, row = invoke(["module", "plan", str(self.composition(ids, name="stock_banks_test")), "--output", self.out()])
        self.assertEqual(code, 0, row)
        pool = next(c for c in row["result"]["checks"] if c["id"] == "pool:sound-assets")
        self.assertEqual(pool["outcome"], "passed"); self.assertEqual(pool["count"], 30); self.assertEqual(pool["base"], 8); self.assertEqual(pool["contribution"], 22)
        self.bank_module("gum_11", "halo_gum_11.all"); self.bank_module("gum_12", "halo_gum_12.all")
        code, row = invoke(["module", "plan", str(self.composition(ids + ["gum_11", "gum_12"], name="stock_banks_test")), "--output", self.out()])
        self.assertEqual(code, 1, row)
        refusal = next(r for r in row["details"]["refusals"] if r["kind"] == "checks")
        self.assertEqual(refusal["failed"], ["pool:sound-assets"])
        pool = next(c for c in row["details"]["checks"] if c["id"] == "pool:sound-assets")
        self.assertEqual(pool["outcome"], "failed"); self.assertEqual(pool["count"], 34)
        self.assertIn("halo_gum_12.all", pool["banks"]); self.assertIn("halo_gum_12.all", pool["detail"])
        self.assertEqual(pool["contributors"][0]["count"], 2)

    def test_one_shared_alias_in_two_banks_is_a_service_refusal_naming_the_shelf_owner(self):
        a = self.bank_module("gum_a", "halo_gum_a.all"); b = self.bank_module("gum_b", "halo_gum_b.all")
        for d in (a, b):
            bank = f"halo_{d.name}.all"
            (d / "soundbank" / f"{bank}.aliases.csv").write_text("Name,FileSource\nhsp_s_gum_eat,raw/sound/x.wav\n")
        code, row = invoke(["module", "plan", str(self.composition(["gum_a", "gum_b"], name="stock_alias_test")), "--output", self.out()])
        self.assertEqual(code, 1, row)
        refusal = row["details"]["refusals"][0]
        self.assertEqual(refusal["kind"], "service"); self.assertEqual(refusal["collision"], "alias:hsp_s_gum_eat")
        self.assertEqual(refusal["modules"], ["gum_a", "gum_b"]); self.assertIsNone(refusal["service"])
        self.assertIn("no module on the shelf provides it yet", row["message"])
        # A shelf module that declares the alias is named as the service.
        audio = self.module("gum_audio", category="audio", kind="bank", provides={"soundbanks": ["shared_gums.all"], "aliases": ["hsp_s_gum_eat"]})
        code, row = invoke(["module", "plan", str(self.composition(["gum_a", "gum_b"], name="stock_alias_test")), "--workspace", str(self.root), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["details"]["refusals"][0]["service"], "gum_audio"); self.assertIn("depend on gum_audio", row["message"])


class ServiceRefusalTests(CompositionFixture):
    def table_module(self, mid, body):
        d = self.module(mid)
        (d / "animstatedefs").mkdir(exist_ok=True)
        (d / "animstatedefs" / "zm_factory_basic.asd").write_text(body)
        recipe = json.loads((d / "project.json").read_text())
        recipe["assets"] = [{"source": "animstatedefs/zm_factory_basic.asd", "target": "animstatedefs/zm_factory_basic.asd", "type": "rawfile"}]
        (d / "project.json").write_text(json.dumps(recipe))
        return d

    def test_two_members_replacing_a_map_owned_table_refuse_naming_the_service(self):
        self.table_module("wavegun", "zm_death_zap"); self.table_module("winters_howl", "zm_death_freeze")
        code, row = invoke(["module", "plan", str(self.composition(["wavegun", "winters_howl"], name="stock_anim_test")), "--output", self.out()])
        self.assertEqual(code, 1, row)
        refusal = row["details"]["refusals"][0]
        self.assertEqual(refusal["kind"], "service"); self.assertEqual(refusal["collision"], "animstatedefs/zm_factory_basic.asd")
        self.assertEqual(refusal["modules"], ["wavegun", "winters_howl"]); self.assertIsNone(refusal["service"])
        self.assertEqual(row["details"].get("undecided"), [], "a service refusal is not also an owner decision")
        self.module("factory_wonder_animations", provides={"rawfiles": ["animstatedefs/zm_factory_basic.asd", "animtrees/zm_factory_basic.atr"]})
        code, row = invoke(["module", "plan", str(self.composition(["wavegun", "winters_howl"], name="stock_anim_test")), "--workspace", str(self.root), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["details"]["refusals"][0]["service"], "factory_wonder_animations")
        self.assertIn("depend on factory_wonder_animations", row["message"])

    def test_identical_table_bytes_stay_a_deduped_decision(self):
        self.table_module("a", "same"); self.table_module("b", "same")
        code, row = invoke(["module", "plan", str(self.composition(["a", "b"], name="stock_same_test")), "--output", self.out()])
        self.assertEqual(code, 0, row)

    def test_a_native_weapondef_registration_is_a_service_refusal(self):
        self.module("tesla", provides={"weapons": ["tesla_gun_zm", "halo_new_zm"]})
        listing = self.root / "packs" / "base" / "zm_factory-list.txt"
        listing.parent.mkdir(parents=True, exist_ok=True)
        listing.write_text("weapon, tesla_gun_zm\n")
        comp = self.composition(["tesla"], name="stock_native_test", base_owned=["../base/zm_factory-list.txt"])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 1, row)
        refusal = row["details"]["refusals"][0]
        self.assertEqual(refusal["what"], "native WeaponDef"); self.assertEqual(refusal["weapons"], ["tesla_gun_zm"]); self.assertEqual(refusal["modules"], ["tesla"])


class RefusalsAsDataTests(CompositionFixture):
    def test_every_refusal_is_reported_in_one_run_with_its_kind_and_modules(self):
        self.module("alpha", dependencies=["gamma"], bases=["b2"])
        self.module("delta", conflicts=["alpha"], maps=["zm_buried"])
        self.module("one", dependencies=["two"]); self.module("two", dependencies=["one"])
        comp = self.composition(["alpha", "delta", "one", "two"], budget={"threads": 1, "entities": 0, "hud": 0, "network_fields": 0})
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertTrue(row["message"].startswith("alpha depends on gamma, which is not in the composition"), row["message"])
        self.assertIn("more refusal", row["message"])
        refusals = row["details"]["refusals"]
        self.assertEqual([r["kind"] for r in refusals], ["missing_dependency", "unqualified_base", "conflict", "unqualified_map", "cycle", "budget"])
        self.assertEqual(refusals[0]["modules"], ["alpha", "gamma"]); self.assertEqual(refusals[0]["dependency"], "gamma"); self.assertEqual(refusals[0]["by"], "alpha")
        self.assertEqual(refusals[1]["declared"], ["b2"]); self.assertEqual(refusals[1]["wanted"], "stock")
        self.assertEqual(refusals[2]["modules"], ["alpha", "delta"])
        self.assertEqual(sorted(refusals[4]["modules"]), ["one", "two"])
        self.assertEqual(refusals[5]["field"], "/budget/threads"); self.assertEqual(refusals[5]["total"], 4)
        receipt = json.loads(Path(row["receipt"]).read_text())
        self.assertEqual(receipt["steps"], [])

    def test_a_single_refusal_keeps_its_own_code_message_and_hint(self):
        self.module("alpha", resource_contract={"threads": 3, "entities": 0, "hud": 0, "network_fields": 0})
        comp = self.composition(["alpha"], budget={"threads": 1, "entities": 0, "hud": 0, "network_fields": 0})
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(row["error_code"], "input_limit"); self.assertEqual(row["message"], "Resource budget exceeded: threads 3 > 1")
        self.assertEqual(row["details"]["refusals"][0]["kind"], "budget"); self.assertIn("Raise the budget", row["hint"])

    def test_check_failures_are_a_refusal_row_naming_contributors(self):
        rows = [{"source": f"model_export/m{i}.glb", "target": f"model_export/m{i}.glb", "type": "rawfile"} for i in range(600)]
        d = self.module("wavegun")
        for r in rows:
            (d / r["source"]).parent.mkdir(parents=True, exist_ok=True); (d / r["source"]).write_bytes(b"x")
        recipe = json.loads((d / "project.json").read_text()); recipe["assets"] = rows; (d / "project.json").write_text(json.dumps(recipe))
        code, row = invoke(["module", "plan", str(self.composition(["wavegun"], name="stock_pool_test")), "--output", self.out()])
        self.assertEqual(code, 1, row)
        refusal = row["details"]["refusals"][0]
        self.assertEqual(refusal["kind"], "checks"); self.assertEqual(refusal["modules"], ["wavegun"]); self.assertEqual(refusal["failed"], ["pool:rawfile-assets"])
        self.assertTrue(row["message"].startswith("Offline checks failed"))
