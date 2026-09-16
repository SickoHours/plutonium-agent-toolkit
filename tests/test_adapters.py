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

    def adapter(self, mid, weapons=("halo_gum_x_eat_zm",), bank="halo_gum_x.all", rawfiles=(), localize=None, aliases=("hsp_s_shared",), prepared=True, exclude_aliases=None, **overrides):
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
            if exclude_aliases is not None:
                recipe["soundbank"]["exclude_aliases"] = exclude_aliases
        if prepared:
            prep = self.root / "prepared" / mid
            (prep / "assets" / "soundbank").mkdir(parents=True, exist_ok=True)
            (prep / "assets" / "soundbank" / "new.aliases.csv").write_text("Name,FileSource,Storage\n" + "".join(f"{a},raw/sound/x/{a}.wav,loaded\n" for a in aliases))
            (prep / "prepared.json").write_text(json.dumps({"entries": [{"id": w, "clips": {"idle": f"{mid}_idle"}} for w in weapons]}))
            recipe["prepared"] = str(prep)
        (d / "recipe.json").write_text(json.dumps(recipe, indent=2))
        decl = declaration(mid, recipe="recipe.json", distribution="private", **{"category": "gobblegums", **overrides})
        (d / "module.json").write_text(json.dumps(decl, indent=2))
        return d

    def recut(self, directory, name="recipe-b2.json", foundation="dlc5-beta2", map_id="zm_factory", **overrides):
        """A second cut of the same donor conversion beside the first: the workspace builder's
        own output for another target, which differs only in revision, foundation, map and profile."""
        recipe = json.loads((directory / "recipe.json").read_text())
        mid = recipe["module"]
        recipe.update(revision="b2-v1", foundation=foundation, map=map_id, profile=f"b2_{mid}_test", **overrides)
        (directory / name).write_text(json.dumps(recipe, indent=2))
        return directory / name

    def _workspace(self):
        (self.root / "foundations").mkdir(exist_ok=True)
        (self.root / "foundations" / "bo2-stock.json").write_text(json.dumps({"schema": 1, "id": "bo2-stock", "profile_prefix": "stock", "maps": {"zm_transit": {}}}))
        (self.root / "foundations" / "dlc5-beta2.json").write_text(json.dumps({"schema": 1, "id": "dlc5-beta2", "profile_prefix": "b2", "maps": {"zm_factory": {}}}))
        (self.root / "toolchain").mkdir(exist_ok=True)
        (self.root / "toolchain" / "pat-adapter-build.py").write_bytes((FAKES / "fake_adapter_builder.py").read_bytes())
        os.environ.pop("PAT_BACKEND_ADAPTER_BUILDER", None)

    def _builder_argv(self, result):
        receipt = json.loads((Path(result["output"]) / "receipt.json").read_text())
        return next(step["argv"] for step in receipt["steps"] if "--output" in step["argv"] and str(Path(result["output"]) / "adapters") in " ".join(step["argv"]))


class AdapterPayloadTests(AdapterFixture):
    def _adapter_with_client_script(self, mid, body):
        """An adapter whose stage produces a loose client script under scripts/zm, beside its
        server one. The stage's scripts never enter `compiled`, so only the package-wide source
        set sees them."""
        d = self.adapter(mid)
        (d / "src" / f"{mid}.csc").write_text(body)
        recipe = json.loads((d / "recipe.json").read_text())
        recipe["loose_scripts"] = [recipe.pop("loose_script"),
                                   {"source": f"src/{mid}.csc", "target": f"scripts/zm/halo_{mid}.csc", "instance": "client"}]
        (d / "recipe.json").write_text(json.dumps(recipe, indent=2))
        return d

    def test_an_adapter_staged_client_script_that_works_in_main_is_refused(self):
        self._adapter_with_client_script("gum_a", "main()\n{\n    gum_register();\n}\n\ngum_register()\n{\n}\n")
        code, row = invoke(["module", "plan", str(self.composition(["gum_a"], name="stock_adapter_test")), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertIn("csc-main-body:scripts/zm/halo_gum_a.csc", row["details"]["failed"])
        check = next(c for c in row["details"]["checks"] if c["id"] == "csc-main-body:scripts/zm/halo_gum_a.csc")
        self.assertEqual(check["outcome"], "failed")
        self.assertIn("init()", check["detail"])

    def test_an_adapter_staged_client_script_with_an_empty_main_plans(self):
        self._adapter_with_client_script("gum_a", "main()\n{\n}\n\ninit()\n{\n    level.gum = 1;\n}\n")
        code, row = invoke(["module", "plan", str(self.composition(["gum_a"], name="stock_adapter_test")), "--output", self.out()])
        self.assertEqual(code, 0, row)
        rows = {c["id"]: c["outcome"] for c in row["result"]["checks"] if c["id"].startswith("csc-main-body:")}
        self.assertEqual(rows["csc-main-body:scripts/zm/halo_gum_a.csc"], "passed")
        self.assertEqual(rows["csc-main-body:scripts/zm/halo_gum_a.gsc"], "not_counted", "the stage's server script is not judged")

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
        adapter_out = Path(result["output"]) / "adapters" / "gum_a"
        self.assertEqual((adapter_out / "readback" / "builder-listing.txt").read_text(), "builder-owned\n", "the builder's own readback directory is left alone")
        self.assertTrue((adapter_out.parent / "gum_a.readback" / "receipt.json").is_file(), "the toolkit's readback job lives beside the builder's output, not inside it")
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


class ExcludedAliasTests(AdapterFixture):
    """``soundbank.exclude_aliases``: the rows a partial sharer hands to the bank module that owns
    them. The gum shape (delete the whole soundbank block) only fits a member whose bank is
    exactly the shared alias; a weapon whose bank carries its own rows too needs a subset."""

    def owner(self, mid="rw_audio", bank="halo_rw_shared.all", aliases=("owned_a", "owned_b")):
        """The bank module: it carries the shared rows and nothing else, and says so."""
        return self.adapter(mid, weapons=(), bank=bank, aliases=aliases, localize={},
                            category="audio", kind="bank", tags=["shared-service"],
                            provides={"soundbanks": [bank], "aliases": list(aliases)})

    def test_the_planner_credits_a_member_with_its_table_minus_the_rows_it_gave_up(self):
        self.adapter("rw_acr", aliases=("owned_a", "owned_b", "acr_fire", "acr_reload"), exclude_aliases=["owned_a", "owned_b"])
        code, row = invoke(["module", "plan", str(self.composition(["rw_acr"], name="stock_exclude_test")), "--output", self.out()])
        self.assertEqual(code, 0, row)
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        self.assertEqual(plan["adapters"][0]["aliases"], ["acr_fire", "acr_reload"])
        self.assertEqual(plan["adapters"][0]["excluded_aliases"], ["owned_a", "owned_b"])
        self.assertEqual(plan["modules"][0]["adapter"]["aliases"], ["acr_fire", "acr_reload"])
        self.assertEqual(plan["modules"][0]["adapter"]["excluded_aliases"], ["owned_a", "owned_b"])
        self.assertEqual(plan["modules"][0]["provides"]["soundbanks"], ["halo_gum_x.all"], "the bank is still the member's; only the rows moved")

    def test_an_excluded_name_the_alias_table_does_not_carry_is_refused(self):
        self.adapter("rw_acr", aliases=("owned_a", "acr_fire"), exclude_aliases=["owned_a", "owned_gone"])
        code, row = invoke(["module", "plan", str(self.composition(["rw_acr"], name="stock_exclude_test")), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("owned_gone", row["message"]); self.assertIn("does not carry", row["message"])

    def test_a_malformed_exclusion_is_refused_before_anything_is_read(self):
        for value in ([], "owned_a", [""], ["ok", 7], ["x" * 257], [f"a{i}" for i in range(257)]):
            with self.subTest(value=value):
                self.adapter("rw_acr", aliases=("owned_a", "acr_fire"), exclude_aliases=value)
                code, row = invoke(["module", "plan", str(self.composition(["rw_acr"], name="stock_exclude_test")), "--output", self.out()])
                self.assertEqual(code, 1, row)
                self.assertEqual(row["error_code"], "input_invalid")
                self.assertIn("exclude_aliases is a list of 1 to 256 alias names", row["message"])

    def test_an_owner_bank_and_a_member_that_gave_the_owned_rows_up_plan_with_no_service_refusal(self):
        self.owner()
        self.adapter("rw_acr", bank="halo_rw_acr.all", aliases=("owned_a", "owned_b", "acr_fire"), exclude_aliases=["owned_a", "owned_b"],
                     dependencies=["rw_audio"])
        code, row = invoke(["module", "plan", str(self.composition(["rw_audio", "rw_acr"], name="stock_owner_test")), "--output", self.out()])
        self.assertEqual(code, 0, row)  # a plan that refuses returns 1 with the refusals under details
        self.assertEqual(row["result"]["undecided"], [], "the shared rows are not an owner decision either")
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        by_id = {a["id"]: a for a in plan["adapters"]}
        self.assertEqual(by_id["rw_audio"]["aliases"], ["owned_a", "owned_b"])
        self.assertEqual(by_id["rw_acr"]["aliases"], ["acr_fire"], "the shared rows are the owner's alone")

    def test_the_same_pack_without_the_exclusion_still_refuses_on_every_shared_row(self):
        self.owner()
        self.adapter("rw_acr", bank="halo_rw_acr.all", aliases=("owned_a", "owned_b", "acr_fire"), dependencies=["rw_audio"])
        code, row = invoke(["module", "plan", str(self.composition(["rw_audio", "rw_acr"], name="stock_owner_test")), "--output", self.out()])
        self.assertEqual(code, 1, row)
        refusals = [r for r in row["details"]["refusals"] if r["kind"] == "service"]
        self.assertEqual([r["collision"] for r in refusals], ["alias:owned_a", "alias:owned_b"])
        self.assertEqual(refusals[0]["modules"], ["rw_acr", "rw_audio"])


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


class AdapterTargetTests(AdapterFixture):
    """A recipe names the foundation and map it was first cut for; a pack on another target
    tells the builder that target so the member is cut alone there (Phase B of the stitching plan)."""

    def test_same_target_passes_no_flags(self):
        self._workspace()
        self.adapter("gum_a")
        comp = self.composition(["gum_a"], name="stock_adapter_test")
        code, row = invoke(["module", "build", str(comp), "--workspace", str(self.root), "--output", self.out()])
        self.assertEqual(code, 0, row)
        argv = self._builder_argv(row["result"])
        self.assertNotIn("--foundation", argv); self.assertNotIn("--map", argv)
        report = row["result"]["adapters"][0]
        self.assertFalse(report["retargeted"]); self.assertEqual(report["built_target"], {"foundation": "bo2-stock", "map": "zm_transit"})

    def test_another_target_is_passed_to_the_builder_in_workspace_foundation_ids(self):
        self._workspace()
        self.adapter("gum_a", bases=["stock", "b2"], maps=["zm_transit", "zm_factory"])
        comp = self.composition(["gum_a"], name="b2_adapter_test", base="b2", map_id="zm_factory")
        code, row = invoke(["module", "build", str(comp), "--workspace", str(self.root), "--output", self.out()])
        self.assertEqual(code, 0, row)
        argv = self._builder_argv(row["result"])
        self.assertEqual(argv[argv.index("--foundation") + 1], "dlc5-beta2", "the workspace's foundation id, never the base token")
        self.assertEqual(argv[argv.index("--map") + 1], "zm_factory")
        report = row["result"]["adapters"][0]
        self.assertTrue(report["retargeted"])
        self.assertEqual(report["recipe_target"], {"foundation": "bo2-stock", "map": "zm_transit"})
        self.assertEqual(report["built_target"], {"foundation": "dlc5-beta2", "map": "zm_factory"})

    def test_without_a_workspace_only_the_map_is_retargeted(self):
        # An environment builder with no workspace has no foundation ids to translate a base token
        # into, so the builder hears the map only and keeps the recipe's own foundation.
        self.adapter("gum_a", bases=["stock"], maps=["zm_transit", "zm_buried"])
        comp = self.composition(["gum_a"], name="stock_adapter_test", map_id="zm_buried")
        code, row = invoke(["module", "build", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        argv = self._builder_argv(row["result"])
        self.assertNotIn("--foundation", argv); self.assertEqual(argv[argv.index("--map") + 1], "zm_buried")


class AdapterPerTargetRecipeTests(AdapterFixture):
    """A declaration may name one cut per target. `recipes` maps `<foundation>/<map>` to the
    recipe cut for it and `recipe` stays the default, so a pack gets the cut it is for instead
    of the first one retargeted."""

    B2 = {"dlc5-beta2/zm_factory": "recipe-b2.json"}

    def test_a_pack_on_the_second_target_plans_from_that_target_s_recipe(self):
        self._workspace()
        d = self.adapter("gum_a", bases=["stock", "b2"], maps=["zm_transit", "zm_factory"], recipes=self.B2)
        self.recut(d)
        comp = self.composition(["gum_a"], name="b2_adapter_test", base="b2", map_id="zm_factory")
        code, row = invoke(["module", "plan", str(comp), "--workspace", str(self.root), "--output", self.out()])
        self.assertEqual(code, 0, row)
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        adapter = plan["adapters"][0]
        self.assertEqual(Path(adapter["recipe"]).name, "recipe-b2.json")
        self.assertEqual(adapter["recipe_key"], "dlc5-beta2/zm_factory")
        self.assertEqual((adapter["foundation"], adapter["map"]), ("dlc5-beta2", "zm_factory"))
        member = plan["modules"][0]
        self.assertEqual(member["recipes"], ["dlc5-beta2/zm_factory"])
        self.assertEqual(member["adapter"]["profile"], "b2_gum_a_test")
        self.assertEqual(member["recipe_sha256"], __import__("hashlib").sha256((d / "recipe-b2.json").read_bytes()).hexdigest(),
                         "the plan hashes the recipe it read the footprint from")

    def test_the_chosen_recipe_is_already_on_target_so_the_builder_hears_no_overrides(self):
        self._workspace()
        d = self.adapter("gum_a", bases=["stock", "b2"], maps=["zm_transit", "zm_factory"], recipes=self.B2)
        self.recut(d)
        comp = self.composition(["gum_a"], name="b2_adapter_test", base="b2", map_id="zm_factory")
        code, row = invoke(["module", "build", str(comp), "--workspace", str(self.root), "--output", self.out()])
        self.assertEqual(code, 0, row)
        argv = self._builder_argv(row["result"])
        # The builder reads the resolved copy, so the cut it was given is named by that copy's own
        # target and by the report's `recipe`, not by the file name on the command line.
        given = Path(argv[argv.index("--output") - 1])
        self.assertEqual(given.name, "gum_a.recipe.resolved.json")
        self.assertEqual((json.loads(given.read_text())["foundation"], json.loads(given.read_text())["map"]),
                         ("dlc5-beta2", "zm_factory"))
        self.assertNotIn("--foundation", argv); self.assertNotIn("--map", argv)
        report = row["result"]["adapters"][0]
        self.assertEqual(Path(report["recipe"]).name, "recipe-b2.json")
        self.assertEqual(Path(report["recipe_resolved"]), given)
        self.assertFalse(report["retargeted"])
        self.assertEqual(report["recipe_target"], {"foundation": "dlc5-beta2", "map": "zm_factory"})
        self.assertEqual(report["built_target"], {"foundation": "dlc5-beta2", "map": "zm_factory"})

    def test_a_pack_on_the_default_target_still_uses_the_default_recipe(self):
        self._workspace()
        d = self.adapter("gum_a", bases=["stock", "b2"], maps=["zm_transit", "zm_factory"], recipes=self.B2)
        self.recut(d)
        comp = self.composition(["gum_a"], name="stock_adapter_test")
        code, row = invoke(["module", "build", str(comp), "--workspace", str(self.root), "--output", self.out()])
        self.assertEqual(code, 0, row)
        argv = self._builder_argv(row["result"])
        self.assertEqual(Path(argv[argv.index("--output") - 1]).name, "gum_a.recipe.resolved.json")
        self.assertNotIn("--foundation", argv); self.assertNotIn("--map", argv)
        report = row["result"]["adapters"][0]
        self.assertEqual(Path(report["recipe"]).name, "recipe.json", "the default cut is the one resolved and built")
        self.assertEqual(report["recipe_target"], {"foundation": "bo2-stock", "map": "zm_transit"})
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        self.assertIsNone(plan["adapters"][0]["recipe_key"], "the default cut is not one of the recipes keys")

    def test_an_unnamed_target_keeps_the_override_behaviour(self):
        # Only the default cut exists for zm_buried: the pack retargets it, as before `recipes`.
        self._workspace()
        d = self.adapter("gum_a", bases=["stock", "b2"], maps=["zm_transit", "zm_factory", "zm_buried"], recipes=self.B2)
        self.recut(d)
        comp = self.composition(["gum_a"], name="stock_adapter_test", map_id="zm_buried")
        code, row = invoke(["module", "build", str(comp), "--workspace", str(self.root), "--output", self.out()])
        self.assertEqual(code, 0, row)
        argv = self._builder_argv(row["result"])
        self.assertEqual(Path(argv[argv.index("--output") - 1]).name, "gum_a.recipe.resolved.json")
        self.assertEqual(Path(row["result"]["adapters"][0]["recipe"]).name, "recipe.json")
        self.assertEqual(argv[argv.index("--map") + 1], "zm_buried")
        self.assertTrue(row["result"]["adapters"][0]["retargeted"])

    def test_a_key_whose_recipe_was_cut_for_another_target_is_refused(self):
        self._workspace()
        d = self.adapter("gum_a", bases=["stock", "b2"], maps=["zm_transit", "zm_factory"], recipes=self.B2)
        self.recut(d, foundation="dlc5-beta1")
        for name, base, map_id in (("b2_adapter_test", "b2", "zm_factory"), ("stock_adapter_test", "stock", "zm_transit")):
            comp = self.composition(["gum_a"], name=name, base=base, map_id=map_id)
            code, row = invoke(["module", "plan", str(comp), "--workspace", str(self.root), "--output", self.out()])
            self.assertEqual(code, 1, row)
            self.assertIn("was cut for dlc5-beta1/zm_factory", row["message"])

    def test_a_recipes_entry_must_name_an_adapter_recipe_that_exists(self):
        self._workspace()
        d = self.adapter("gum_a", bases=["stock", "b2"], maps=["zm_transit", "zm_factory"], recipes=self.B2)
        comp = self.composition(["gum_a"], name="b2_adapter_test", base="b2", map_id="zm_factory")
        code, row = invoke(["module", "plan", str(comp), "--workspace", str(self.root), "--output", self.out()])
        self.assertEqual(code, 1, row); self.assertIn("recipes[dlc5-beta2/zm_factory] is missing", row["message"])
        (d / "recipe-b2.json").write_text(json.dumps({"schema": 1, "game": "t6", "name": "gum_a", "scripts": [], "assets": [], "loads": []}))
        code, row = invoke(["module", "plan", str(comp), "--workspace", str(self.root), "--output", self.out()])
        self.assertEqual(code, 1, row); self.assertIn("is not an adapter recipe", row["message"])


class NativeWeaponTableTests(CompositionFixture):
    """The native-WeaponDef rule as a declaration check: the shipped per-map table names what the
    map already registers, so no base listing is needed to refuse the precache crash."""

    def test_a_native_weapondef_on_a_tabled_map_is_refused_without_a_base_listing(self):
        self.module("tesla", provides={"weapons": ["tesla_gun_zm", "halo_new_zm"]}, bases=["b2"], maps=["zm_factory"])
        comp = self.composition(["tesla"], name="b2_native_test", base="b2", map_id="zm_factory")
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 1, row)
        refusal = row["details"]["refusals"][0]
        self.assertEqual(refusal["kind"], "service"); self.assertEqual(refusal["what"], "native WeaponDef")
        self.assertEqual(refusal["weapons"], ["tesla_gun_zm"]); self.assertEqual(refusal["modules"], ["tesla"])

    def test_a_new_name_on_a_tabled_map_passes_and_a_stock_map_uses_its_own_table(self):
        self.module("newgun", provides={"weapons": ["halo_new_zm"]}, bases=["b2"], maps=["zm_factory"])
        comp = self.composition(["newgun"], name="b2_native_test", base="b2", map_id="zm_factory")
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.module("ray", provides={"weapons": ["ray_gun_zm"]})
        code, row = invoke(["module", "plan", str(self.composition(["ray"], name="stock_native_test")), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["details"]["refusals"][0]["weapons"], ["ray_gun_zm"], "TranZit's own table applies on stock")

    def test_an_untabled_map_keeps_the_rule_to_base_listings(self):
        self.module("ray", provides={"weapons": ["ray_gun_zm"]}, maps=["zm_unknown"])
        comp = self.composition(["ray"], name="stock_native_test", map_id="zm_unknown")
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)


class WithheldStagingTests(CompositionFixture):
    """``deliver: false`` rows are staged for the linker (a model's export, a bank's WAV, a
    WeaponDef's accuracy graph is read by the path the compiled asset names) without a zone line,
    and two members withholding the same path are a file collision like any other."""

    def test_withheld_inputs_are_staged_under_raw_without_a_zone_line(self):
        rows = [{"source": "accuracy/pistol.accu", "target": "accuracy/aivsplayer/pistol.accu", "type": "rawfile", "deliver": False},
                {"source": "x.accu", "target": "accuracy/x.accu", "type": "rawfile"}]
        self.module_with_assets("gun", rows)
        comp = self.composition(["gun"], name="stock_withheld_test")
        code, row = invoke(["module", "build", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        out = Path(row["result"]["output"])
        self.assertTrue((out / "project" / "raw" / "accuracy" / "aivsplayer" / "pistol.accu").is_file(), "staged for the linker's search path")
        zone = (out / "project" / "zone_source" / "mod.zone").read_text()
        self.assertNotIn("pistol.accu", zone); self.assertIn("rawfile,accuracy/x.accu", zone)
        self.assertEqual(row["result"]["withheld_staged"], 1)
        package = json.loads((out / "packages" / "mod.ff").read_text())
        self.assertNotIn("accuracy/aivsplayer/pistol.accu", package["rawfiles"])

    def test_two_members_withholding_different_bytes_at_one_path_is_a_decision(self):
        row = {"source": "pistol.accu", "target": "accuracy/aivsplayer/pistol.accu", "type": "rawfile", "deliver": False}
        self.module_with_assets("gun_a", [dict(row)])
        d = self.module_with_assets("gun_b", [dict(row)])
        (d / "pistol.accu").write_bytes(b"a different graph")
        comp = self.composition(["gun_a", "gun_b"], name="stock_withheld_test")
        code, plan = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, plan)
        self.assertEqual([u["collision"] for u in plan["result"]["undecided"]], ["accuracy/aivsplayer/pistol.accu"])
        (d / "pistol.accu").write_bytes((self.root / "modules" / "gun_a" / "pistol.accu").read_bytes())
        code, plan = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, plan)
        self.assertEqual(plan["result"]["undecided"], [], "identical bytes dedupe with no decision")
        comp = self.composition(["gun_a", "gun_b"], name="stock_withheld_test",
                                decisions=[{"collision": "accuracy/aivsplayer/pistol.accu", "owner": "gun_a", "reason": "same graph"}])
        code, row = invoke(["module", "build", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row); self.assertEqual(row["result"]["withheld_staged"], 1)


class PreparedPathTests(AdapterFixture):
    """Where a relative `prepared` points, and the one copy of the recipe both halves agree on.

    An adapter recipe names its converted inputs with `prepared`. A relative one used to be tested
    against the caller's working directory by the planner and against the job's output directory by
    the builder, so the same recipe planned as "prepared absent" and then failed the build, and
    which it did depended on where `pat` happened to be run from.
    """

    def prepared_at(self, mid, target, value):
        """Move the fixture's prepared inputs to ``target`` and point the recipe at ``value``."""
        directory = self.root / "modules" / mid
        target.parent.mkdir(parents=True, exist_ok=True)
        (self.root / "prepared" / mid).rename(target)
        recipe = json.loads((directory / "recipe.json").read_text())
        recipe["prepared"] = value
        (directory / "recipe.json").write_text(json.dumps(recipe, indent=2))
        return directory

    def adapter_row(self, *arguments, action="plan", code=0):
        code_out, row = invoke(["module", action, str(self.composition(["gum_a"], name="stock_prepared_test")),
                                *arguments, "--output", self.out()])
        self.assertEqual(code_out, code, row)
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        return row, plan, plan["adapters"][0]

    def test_an_absolute_prepared_path_is_read_as_the_recipe_gave_it(self):
        self.adapter("gum_a")
        _, plan, adapter = self.adapter_row()
        self.assertTrue(adapter["prepared_present"])
        self.assertEqual(adapter["prepared_source"], "recipe")
        self.assertEqual(adapter["prepared_resolved"], str(self.root / "prepared" / "gum_a"))
        self.assertEqual(adapter["aliases"], ["hsp_s_shared"], "the alias table is read through the resolved path")
        self.assertEqual(plan["modules"][0]["adapter"]["prepared_source"], "recipe")

    def test_a_prepared_path_relative_to_the_module_directory_resolves(self):
        self.adapter("gum_a")
        directory = self.prepared_at("gum_a", self.root / "modules" / "gum_a" / "prepared", "prepared")
        _, _, adapter = self.adapter_row()
        self.assertTrue(adapter["prepared_present"])
        self.assertEqual(adapter["prepared_source"], "module-dir")
        self.assertEqual(adapter["prepared_resolved"], str(directory / "prepared"))
        self.assertIn("xanim,gum_a_idle", adapter["roots"], "the prepared record is read from the resolved path")

    def test_a_prepared_path_relative_to_the_workspace_resolves_only_with_a_workspace(self):
        self.adapter("gum_a")
        self.prepared_at("gum_a", self.root / "converted" / "gum_a", "converted/gum_a")
        _, _, alone = self.adapter_row()
        self.assertFalse(alone["prepared_present"], "without --workspace the module directory is the only base")
        self.assertIsNone(alone["prepared_source"])
        self.assertEqual(alone["prepared_candidates"], [str(self.root / "modules" / "gum_a" / "converted" / "gum_a")])
        self._workspace()
        _, _, found = self.adapter_row("--workspace", str(self.root))
        self.assertTrue(found["prepared_present"])
        self.assertEqual(found["prepared_source"], "workspace")
        self.assertEqual(found["prepared_resolved"], str(self.root / "converted" / "gum_a"))
        self.assertEqual(found["aliases"], ["hsp_s_shared"])

    def test_a_prepared_path_neither_base_resolves_names_both_candidates(self):
        self.adapter("gum_a")
        self.prepared_at("gum_a", self.root / "converted" / "gum_a", "nowhere/gum_a")
        self._workspace()
        _, _, adapter = self.adapter_row("--workspace", str(self.root))
        self.assertFalse(adapter["prepared_present"])
        self.assertIsNone(adapter["prepared_resolved"])
        self.assertIsNone(adapter["prepared_source"])
        self.assertEqual(adapter["prepared_candidates"],
                         [str(self.root / "modules" / "gum_a" / "nowhere" / "gum_a"), str(self.root / "nowhere" / "gum_a")])
        self.assertEqual(adapter["aliases"], [], "nothing is read from a prepared directory that is not here")

    def test_the_builder_is_given_a_resolved_copy_of_the_recipe(self):
        self.adapter("gum_a", rawfiles=["animtrees/halo_gum.atr"])
        directory = self.prepared_at("gum_a", self.root / "converted" / "gum_a", "converted/gum_a")
        self._workspace()
        code, row = invoke(["module", "build", str(self.composition(["gum_a"], name="stock_prepared_test")),
                            "--workspace", str(self.root), "--output", self.out()])
        self.assertEqual(code, 0, row)
        output = Path(row["result"]["output"])
        copy = output / "adapters" / "gum_a.recipe.resolved.json"
        self.assertEqual(self._builder_argv(row["result"])[-3], str(copy), "the builder is given the resolved copy")
        self.assertTrue(copy.is_file())
        self.assertFalse((output / "adapters" / "gum_a" / "recipe.resolved.json").exists(),
                         "the copy is a sibling: the builder owns its own output directory and creates it itself")
        resolved = json.loads(copy.read_text())
        self.assertEqual(resolved["prepared"], str(self.root / "converted" / "gum_a"))
        self.assertTrue(Path(resolved["prepared"]).is_absolute())
        plan = json.loads((output / "plan.json").read_text())
        self.assertEqual(plan["adapters"][0]["recipe_resolved"], str(copy))
        self.assertEqual(plan["adapter_builds"][0]["recipe_resolved"], str(copy))

    def test_the_resolved_copy_carries_absolute_loose_script_sources(self):
        # The recipe moves out of the module directory, so every path it states relative to that
        # directory has to travel with it; a builder reading `recipe.parent / source` is unaffected,
        # because joining an absolute path returns it unchanged.
        self.adapter("gum_a")
        directory = self.prepared_at("gum_a", self.root / "converted" / "gum_a", "converted/gum_a")
        self._workspace()
        code, row = invoke(["module", "build", str(self.composition(["gum_a"], name="stock_prepared_test")),
                            "--workspace", str(self.root), "--output", self.out()])
        self.assertEqual(code, 0, row)
        copy = Path(row["result"]["output"]) / "adapters" / "gum_a.recipe.resolved.json"
        source = json.loads(copy.read_text())["loose_script"]["source"]
        self.assertTrue(Path(source).is_absolute())
        self.assertEqual(source, str((directory / "src" / "gum_a.gsc").resolve()))
        self.assertEqual(Path(copy.parent / source), Path(source), "recipe.parent / an absolute source is that source")
        self.assertIn("scripts/zm/halo_gum_a.gsc", row["result"]["loose_scripts"],
                      "the builder found the script through the resolved copy")

    def test_the_resolved_copy_is_absolute_even_when_the_inputs_are_not_here(self):
        # The build fails either way — the converted inputs are not on this machine — but the copy
        # must not hand the builder a relative path: its working directory is the job's, so the
        # path would name something inside the job that nobody wrote.
        self.adapter("gum_a")
        directory = self.prepared_at("gum_a", self.root / "converted" / "gum_a", "nowhere/gum_a")
        self._workspace()
        _, _, adapter = self.adapter_row("--workspace", str(self.root))
        self.assertFalse(adapter["prepared_present"])
        code, row = invoke(["module", "build", str(self.composition(["gum_a"], name="stock_prepared_test")),
                            "--workspace", str(self.root), "--output", self.out()])
        # The fixture builder does not read prepared; the copy is what is under test.
        self.assertEqual(code, 0, row)
        copy = Path(row["result"]["output"]) / "adapters" / "gum_a.recipe.resolved.json"
        prepared = json.loads(copy.read_text())["prepared"]
        self.assertTrue(Path(prepared).is_absolute())
        self.assertEqual(prepared, str(directory / "nowhere" / "gum_a"), "the module-directory reading, the first candidate")
        self.assertEqual(prepared, adapter["prepared_candidates"][0])

    def test_a_plan_records_no_resolved_copy_because_none_was_written(self):
        self.adapter("gum_a")
        _, _, adapter = self.adapter_row()
        self.assertIsNone(adapter["recipe_resolved"])
