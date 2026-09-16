"""``module qualify``: one module built alone on one target, and the records written from its receipts.

The route is specified in docs/MODULES.md; these tests are the executable half of that section.
Everything runs against the fake backends, so a "build" here is the fake linker's JSON package:
what is under test is the loop, the refusals and the four records, not the linker.
"""
import json
from pathlib import Path

from tests.test_adapters import AdapterFixture
from tests.test_compositions import declaration
from tests.test_dev_routes import invoke

FOUNDATION = "test-b2"
TARGET = f"{FOUNDATION}/zm_factory"


class QualifyFixture(AdapterFixture):
    """A workspace: one foundation staging one map, a modules shelf, a bindings registry."""

    def setUp(self):
        super().setUp()
        (self.root / "modules").mkdir(parents=True, exist_ok=True)
        self.load = self.root / "base" / "common_zm.ff"
        self.load.parent.mkdir(parents=True, exist_ok=True)
        self.load.write_text(json.dumps({"zone": "common_zm", "assets": [], "rawfiles": {}}))

    def foundation(self, private_descriptor=False, maps=("zm_factory",)):
        directory = self.root / "foundations"
        directory.mkdir(parents=True, exist_ok=True)
        header = [">game,T6", ">name,mod", ">level.ipak_read,zm_transit"]
        loads = {m: [str(self.load)] for m in maps}
        record = {"schema": 1, "id": FOUNDATION, "profile_prefix": "b2",
                  "maps": {m: {"runtime_zones": ["common_zm"], "link_loads": ["common_zm"]} for m in maps},
                  "mod_zone_header": header}
        if private_descriptor:
            (directory / "private.json").write_text(json.dumps({"schema": 1, "id": FOUNDATION, "link_loads": loads}, indent=2))
            record["private_descriptor"] = "private.json"
        else:
            record["link_loads"] = loads
        (directory / f"{FOUNDATION}.json").write_text(json.dumps(record, indent=2))
        return directory / f"{FOUNDATION}.json"

    def bindings(self, *ids):
        path = self.root / "registry" / "module-recipes.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema": 1, "recipes": [{"id": i, "recipe": f"modules/{i}/project.json"} for i in ids]}, indent=2) + "\n")
        return path

    def entry(self, result, index=0):
        return result["modules"][index]

    def qualify(self, *arguments):
        return invoke(["module", "qualify", *arguments, "--target", TARGET, "--workspace", str(self.root), "--output", self.out()])

    def read(self, path):
        return Path(path).read_bytes()


class QualifyProjectTests(QualifyFixture):
    def test_a_project_module_qualifies_and_its_records_are_written_with_matching_hashes(self):
        self.foundation(private_descriptor=True)
        directory = self.module("alpha", bases=["stock"], maps=["zm_transit"])
        self.bindings("alpha")
        code, row = self.qualify(str(directory))
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertEqual(result["qualified"], 1)
        self.assertEqual(result["refused"], 0)
        entry = result["modules"][0]
        self.assertEqual(entry["outcome"], "qualified")
        self.assertFalse(entry["already_declared"])
        # Both builds produced the same package: a declaration is metadata the package does not carry.
        self.assertTrue(entry["package_identical"])
        self.assertEqual(sorted(entry["receipts"]),
                         ["build-qualified", "build-unqualified", "plan-qualified", "plan-unqualified",
                          "verify-qualified", "verify-unqualified"])
        for relative in entry["receipts"].values():
            receipt = json.loads((self.root / relative).read_text())
            self.assertEqual(receipt["status"], "succeeded", relative)

        # (1) the declaration, widened by exactly this target
        widened = json.loads((directory / "module.json").read_text())
        self.assertEqual(widened["bases"], ["stock", "b2"])
        self.assertEqual(widened["maps"], ["zm_transit", "zm_factory"])
        self.assertNotIn("recipes", widened, "a project recipe is compiled for whatever the pack targets")

        # (2) docs/TEST.md cites every receipt by relative path and sha256
        test_record = (directory / "docs" / "TEST.md").read_text()
        self.assertIn(f"## Build 01 — {FOUNDATION} / zm_factory qualification", test_record)
        self.assertIn(entry["package_sha256"], test_record)
        for name, relative in entry["receipts"].items():
            self.assertIn(relative, test_record, name)
            digest = json.loads((self.root / entry["job"] / "qualify.json").read_text())["steps"][name]["receipt_sha256"]
            self.assertIn(digest, test_record, name)
        self.assertIn("player accepted **no**", test_record)

        # (3) the built-alone row, through the ledger's own validator
        from plutonium_agent_toolkit.dev import ledger
        book = json.loads((directory / "evidence.json").read_text())
        normalized, diagnostics = ledger.validate(book)
        self.assertEqual(diagnostics, [])
        built = [r for r in normalized["rows"] if r["type"] == "built-alone"]
        self.assertEqual(len(built), 1)
        self.assertEqual(built[0]["scope"], {"base": "b2", "foundation": FOUNDATION, "maps": ["zm_factory"]})
        self.assertEqual(built[0]["package_sha256"], entry["package_sha256"])
        self.assertEqual(built[0]["receipt"]["path"], entry["receipts"]["build-qualified"])

        # (4) the workspace binding row
        binding = json.loads((self.root / "registry" / "module-recipes.json").read_text())["recipes"][0]["builds"][0]
        self.assertEqual(binding["sha256"], entry["package_sha256"])
        self.assertEqual(binding["foundation"], FOUNDATION)
        self.assertEqual(binding["map"], "zm_factory")
        self.assertEqual([binding["offline_verified"], binding["installed"], binding["runtime_verified"], binding["player_accepted"]],
                         [True, False, False, False])
        # A workspace may key its entries by directory name; its own validator wants the entry's id
        # in the row, not the declaration's.
        self.assertEqual(binding["modules"], ["alpha"])
        self.assertEqual(sorted(binding), ["foundation", "id", "installed", "map", "modules", "offline_verified",
                                           "player_accepted", "receipt", "runtime_verified", "sha256"])

    def test_the_binding_row_names_the_entry_id_when_the_registry_keys_by_directory(self):
        # A declaration id is underscored; a workspace often names the directory with hyphens and
        # keys its registry by that. The catalog's own rule is that the entry id is in the row.
        self.foundation()
        made = self.module("acid_kit", bases=["stock"], maps=["zm_transit"])
        directory = made.parent / "acid-kit"
        made.rename(directory)
        path = self.root / "registry" / "module-recipes.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema": 1, "recipes": [{"id": "acid-kit", "recipe": "modules/acid-kit/project.json"}]}, indent=2) + "\n")
        code, row = self.qualify(str(directory))
        self.assertEqual(code, 0, row)
        binding = json.loads(path.read_text())["recipes"][0]["builds"][0]
        self.assertEqual(binding["modules"], ["acid-kit"])
        self.assertEqual(row["result"]["modules"][0]["id"], "acid_kit")
        self.assertEqual(row["result"]["modules"][0]["records"]["binding"], "acid-kit")

    def test_a_target_the_workspace_does_not_stage_is_refused_before_anything_is_built(self):
        self.foundation(maps=("zm_prototype",))
        directory = self.module("alpha", bases=["stock"], maps=["zm_transit"])
        before = self.read(directory / "module.json")
        code, row = self.qualify(str(directory))
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_missing")
        self.assertIn("does not stage zm_factory", row["message"])
        self.assertEqual(self.read(directory / "module.json"), before)

    def test_a_dependency_that_is_not_declared_for_the_target_refuses_and_names_it(self):
        self.foundation()
        self.module("core", bases=["stock"], maps=["zm_transit"])
        directory = self.module("alpha", bases=["stock"], maps=["zm_transit"], dependencies=["core"])
        before = self.read(directory / "module.json")
        code, row = self.qualify(str(directory))
        self.assertEqual(code, 1, row)
        refusal = row["details"]["refusals"][0]
        self.assertEqual(refusal["kind"], "dependency-unqualified")
        self.assertEqual(refusal["modules"], ["core"])
        self.assertIn("pat module qualify", refusal["hint"])
        self.assertEqual(self.read(directory / "module.json"), before)

    def test_a_refused_module_leaves_its_declaration_byte_identical(self):
        self.foundation()
        self.bindings("alpha")
        directory = self.module("alpha", bases=["stock"], maps=["zm_transit"])
        (directory / "scripts" / "alpha.gsc").write_text("main() { FAIL_COMPILE }\n")
        before = {name: self.read(directory / name) for name in ("module.json", "project.json")}
        bindings_before = self.read(self.root / "registry" / "module-recipes.json")
        code, row = self.qualify(str(directory))
        self.assertEqual(code, 1, row)
        refusal = row["details"]["refusals"][0]
        self.assertEqual(refusal["kind"], "build-failed")
        self.assertEqual(row["details"]["modules"][0]["outcome"], "refused")
        for name, data in before.items():
            self.assertEqual(self.read(directory / name), data, name)
        self.assertFalse((directory / "evidence.json").exists())
        self.assertFalse((directory / "docs" / "TEST.md").exists())
        self.assertEqual(self.read(self.root / "registry" / "module-recipes.json"), bindings_before)
        # The refusal is in the job directory, with the receipts of the steps that did run.
        job = json.loads((self.root / row["details"]["modules"][0]["job"] / "qualify.json").read_text())
        self.assertEqual(job["refusals"][0]["kind"], "build-failed")
        self.assertTrue(job["steps"]["plan-unqualified"]["ok"])
        self.assertFalse(job["steps"]["build-unqualified"]["ok"])

    def test_a_module_already_declared_for_the_target_is_re_receipted_not_refused(self):
        self.foundation()
        self.bindings("alpha")
        directory = self.module("alpha", bases=["stock", "b2"], maps=["zm_transit", "zm_factory"])
        code, row = self.qualify(str(directory))
        self.assertEqual(code, 0, row)
        entry = row["result"]["modules"][0]
        self.assertTrue(entry["already_declared"])
        self.assertEqual(entry["outcome"], "qualified")
        self.assertEqual(json.loads((directory / "module.json").read_text())["bases"], ["stock", "b2"])
        self.assertIn("## Build 01", (directory / "docs" / "TEST.md").read_text())


class QualifyAdapterTests(QualifyFixture):
    def test_an_adapter_module_gets_its_per_target_recipe_and_a_recipes_entry(self):
        self.foundation()
        self.bindings("gum_a")
        directory = self.adapter("gum_a", bases=["stock"], maps=["zm_transit"])
        code, row = self.qualify(str(directory))
        self.assertEqual(code, 0, row)
        entry = row["result"]["modules"][0]
        self.assertEqual(entry["outcome"], "qualified")
        self.assertEqual(entry["records"]["recipe"], "recipe-b2.json")
        self.assertFalse(entry["records"]["recipe_reused"])

        cut = json.loads((directory / "recipe-b2.json").read_text())
        original = json.loads((directory / "recipe.json").read_text())
        self.assertEqual(cut["foundation"], FOUNDATION)
        self.assertEqual(cut["map"], "zm_factory")
        self.assertEqual(cut["profile"], "b2_gum_a_test")
        self.assertEqual(cut["revision"], "b2-zm_factory-qualify-v1")
        changed = {k for k in set(cut) | set(original) if cut.get(k) != original.get(k)}
        self.assertEqual(changed, {"foundation", "map", "profile", "revision"},
                         "only the target, profile and revision differ between the two cuts")

        widened = json.loads((directory / "module.json").read_text())
        self.assertEqual(widened["recipes"], {TARGET: "recipe-b2.json"})
        self.assertEqual(widened["bases"], ["stock", "b2"])
        self.assertEqual(widened["maps"], ["zm_transit", "zm_factory"])
        # The recipe the pack picks on this target is the new cut, and the plan says so.
        plan = json.loads((self.root / entry["receipts"]["plan-qualified"]).parent.joinpath("plan.json").read_text())
        self.assertEqual(plan["adapters"][0]["recipe_key"], TARGET)
        self.assertTrue(str(plan["adapters"][0]["recipe"]).endswith("recipe-b2.json"))
        # The cut the workspace builder produced is its own artifact, recorded beside the pack's.
        cut = entry["adapter_cuts"][0]
        self.assertEqual(cut["id"], "gum_a")
        self.assertEqual(cut["recipe_key"], TARGET)
        self.assertFalse(cut["retargeted"], "a per-target recipe already names the target; the builder hears no override")
        record = (directory / "docs" / "TEST.md").read_text()
        self.assertIn("recipe-b2.json", record)
        self.assertIn(cut["mod_ff_sha256"], record)
        self.assertIn(cut["mod_ff_sha256"], json.loads((directory / "evidence.json").read_text())["rows"][-1]["note"])

    def test_an_existing_cut_recorded_under_recipes_is_reused_and_never_overwritten(self):
        self.foundation()
        directory = self.adapter("gum_a", bases=["stock"], maps=["zm_transit"])
        original = json.loads((directory / "recipe.json").read_text())
        (directory / "recipe-b2.json").write_text(json.dumps(dict(original, foundation=FOUNDATION, map="zm_factory",
                                                                  profile="b2_gum_a_test", revision="by-hand"), indent=2) + "\n")
        declared = json.loads((directory / "module.json").read_text())
        declared["recipes"] = {TARGET: "recipe-b2.json"}
        (directory / "module.json").write_text(json.dumps(declared, indent=2))
        before = self.read(directory / "recipe-b2.json")
        code, row = self.qualify(str(directory))
        self.assertEqual(code, 0, row)
        self.assertTrue(row["result"]["modules"][0]["records"]["recipe_reused"])
        self.assertEqual(self.read(directory / "recipe-b2.json"), before, "this route never rewrites a recipe")

    def test_a_cut_on_disk_that_recipes_does_not_name_is_refused_rather_than_overwritten(self):
        self.foundation()
        directory = self.adapter("gum_a", bases=["stock"], maps=["zm_transit"])
        (directory / "recipe-b2.json").write_text("{}\n")
        before = self.read(directory / "recipe-b2.json")
        code, row = self.qualify(str(directory))
        self.assertEqual(code, 1, row)
        self.assertEqual(row["details"]["refusals"][0]["kind"], "adapter-recipe-single-target-without-recipes")
        self.assertEqual(self.read(directory / "recipe-b2.json"), before)


class QualifySetTests(QualifyFixture):
    def test_a_set_runs_in_dependency_order_continues_past_failures_and_reports_each(self):
        self.foundation()
        self.bindings("core", "alpha", "broken")
        core = self.module("core", bases=["stock"], maps=["zm_transit"])
        alpha = self.module("alpha", bases=["stock"], maps=["zm_transit"], dependencies=["core"])
        broken = self.module("broken", bases=["stock"], maps=["zm_transit"])
        (broken / "scripts" / "broken.gsc").write_text("main() { FAIL_COMPILE }\n")
        listing = self.root / "set.txt"
        # Deliberately out of order, and with a comment: the route sorts by declared dependencies.
        listing.write_text(f"# the set\n{alpha}\n{broken}\n{core}\n")
        code, row = self.qualify("--set", str(listing))
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertEqual([m["id"] for m in result["modules"]], ["core", "alpha", "broken"])
        self.assertEqual([m["outcome"] for m in result["modules"]], ["qualified", "qualified", "refused"])
        self.assertEqual((result["qualified"], result["refused"]), (2, 1))
        self.assertEqual(result["modules"][2]["refusal"]["kind"], "build-failed")
        # alpha's dependency was qualified in this same run, so alpha was not refused for it.
        self.assertEqual(json.loads((alpha / "module.json").read_text())["bases"], ["stock", "b2"])
        self.assertEqual(json.loads((core / "module.json").read_text())["bases"], ["stock", "b2"])
        self.assertEqual(json.loads((broken / "module.json").read_text())["bases"], ["stock"])
        table = json.loads((Path(result["results"] if Path(result["results"]).is_absolute()
                                 else self.root / result["modules"][0]["job"]).parent / "results.json").read_text())
        self.assertEqual([m["id"] for m in table["modules"]], ["core", "alpha", "broken"])
        self.assertEqual(table["target"], TARGET)

    def test_a_job_directory_outside_the_workspace_is_refused_before_any_build(self):
        # A ledger receipt pointer is relative to the workspace root and never climbs out of it,
        # so records could not cite receipts written elsewhere.
        self.foundation()
        directory = self.module("alpha", bases=["stock"], maps=["zm_transit"])
        before = self.read(directory / "module.json")
        outside = Path(self.temp.name).parent / f"outside-{id(self)}"
        code, row = invoke(["module", "qualify", str(directory), "--target", TARGET, "--workspace", str(self.root),
                            "--output", str(outside)])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("must be inside the workspace", row["message"])
        self.assertEqual(self.read(directory / "module.json"), before)

    def test_naming_both_a_module_and_a_set_is_a_usage_refusal(self):
        self.foundation()
        directory = self.module("alpha")
        listing = self.root / "set.txt"
        listing.write_text(f"{directory}\n")
        code, row = self.qualify(str(directory), "--set", str(listing))
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")


class AdaptOutcomeTests(QualifyFixture):
    def test_module_plan_emits_a_work_order_for_every_member_not_declared_for_the_target(self):
        self.foundation()
        self.module("core", bases=["stock"], maps=["zm_transit"])
        self.module("alpha", bases=["stock"], maps=["zm_transit"], dependencies=["core"])
        comp = self.composition(["alpha", "core"], name="b2_example_test", base="b2", map_id="zm_factory")
        code, row = invoke(["module", "plan", str(comp), "--allow-unqualified", "--workspace", str(self.root), "--output", self.out()])
        self.assertEqual(code, 0, row)
        adapt = {r["module"]: r for r in row["result"]["adapt"]}
        self.assertEqual(sorted(adapt), ["alpha", "core"])
        self.assertEqual(adapt["alpha"]["target"], TARGET)
        self.assertEqual(adapt["alpha"]["pattern"], "dependency-unqualified")
        self.assertEqual(adapt["core"]["pattern"], "unknown")
        self.assertTrue(adapt["core"]["work_order"].startswith("pat module qualify "))
        self.assertIn(f"--target {TARGET}", adapt["core"]["work_order"])
        self.assertEqual(adapt["core"]["declared_maps"], ["zm_transit"])

    def test_a_refused_plan_carries_the_same_work_orders_as_data(self):
        self.foundation()
        self.module("alpha", bases=["stock"], maps=["zm_transit"])
        comp = self.composition(["alpha"], name="b2_example_test", base="b2", map_id="zm_factory")
        code, row = invoke(["module", "plan", str(comp), "--workspace", str(self.root), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertEqual([r["kind"] for r in row["details"]["refusals"]], ["unqualified_base", "unqualified_map"])
        self.assertEqual([r["module"] for r in row["details"]["adapt"]], ["alpha"])
        self.assertEqual(row["details"]["unqualified"][0]["id"], "alpha")

    def test_a_member_guarded_on_its_donor_map_is_a_port_not_a_widening(self):
        # The guard names the map the module was written for; widening the declaration would not
        # make it run on the target, so the work order says port, and the pattern says why.
        self.foundation()
        directory = self.module("alpha", bases=["stock"], maps=["zm_transit"],
                                provides={"scripts": ["scripts/zm/alpha.gsc"]})
        (directory / "scripts" / "alpha.gsc").write_text(
            'main()\n{\n    if ( getdvar( "mapname" ) != "zm_transit" )\n        return;\n    level thread alpha();\n}\n\nalpha()\n{\n    wait 1;\n}\n')
        comp = self.composition(["alpha"], name="b2_example_test", base="b2", map_id="zm_factory")
        code, row = invoke(["module", "plan", str(comp), "--allow-unqualified", "--workspace", str(self.root), "--output", self.out()])
        self.assertEqual(code, 1, row)  # a failed map-guard row refuses like every failed check
        adapt = {r["module"]: r for r in row["details"]["adapt"]}
        self.assertEqual(adapt["alpha"]["pattern"], "map-guard")
        self.assertIn("zm_transit", adapt["alpha"]["detail"])

    def test_an_adapter_cut_for_another_target_is_named_as_its_own_pattern(self):
        self.foundation()
        self.adapter("gum_a", bases=["stock"], maps=["zm_transit"])
        comp = self.composition(["gum_a"], name="b2_example_test", base="b2", map_id="zm_factory")
        code, row = invoke(["module", "plan", str(comp), "--allow-unqualified", "--workspace", str(self.root), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["adapt"][0]["pattern"], "adapter-recipe-single-target-without-recipes")
        self.assertIn("bo2-stock/zm_transit", row["result"]["adapt"][0]["detail"])

    def test_a_pack_whose_members_are_all_declared_emits_no_work_orders(self):
        self.foundation()
        self.module("alpha", bases=["stock"], maps=["zm_transit"])
        comp = self.composition(["alpha"], name="stock_example_test", base="stock", map_id="zm_transit")
        code, row = invoke(["module", "plan", str(comp), "--workspace", str(self.root), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["adapt"], [])


class QualifyBaseListingTests(QualifyFixture):
    """A module qualified alone is judged on its package bytes.

    Two checks stood between every donor-loading module and its receipt, and neither was about the
    package. `donor-shadowing` refused because the synthesized composition passed no base listings,
    even though the foundation names them; `loose-overrides` then refused on files in this machine's
    global `storage/t6/images`, which no package contains and no build can change.
    """

    def donor_module(self, mid="alpha", **overrides):
        """A module whose own recipe loads a zone the foundation does not name as base."""
        directory = self.module(mid, bases=["stock"], maps=["zm_transit"], **overrides)
        donor = directory / "donor" / "zm_moon_patch.ff"
        donor.parent.mkdir(parents=True, exist_ok=True)
        donor.write_text(json.dumps({"zone": "zm_moon_patch", "assets": [], "rawfiles": {}}))
        recipe = json.loads((directory / "project.json").read_text())
        recipe["loads"] = ["donor/zm_moon_patch.ff"]
        (directory / "project.json").write_text(json.dumps(recipe, indent=2))
        return directory

    def listing(self, *rows):
        """A `<zone>-list.txt` for the base zone, in the directory the link loads live in."""
        rows = rows or ("image, camo_zombies_nml", "material, mtl_stock")
        path = self.load.parent / "common_zm-list.txt"
        path.write_text("".join(f"{row}\n" for row in rows))
        return path

    def test_without_a_listing_a_donor_loading_module_refuses_before_it_is_built(self):
        self.foundation()
        code, row = self.qualify(str(self.donor_module()))
        self.assertEqual(code, 1, row)
        refusal = row["details"]["modules"][0]["refusal"]
        self.assertEqual(refusal["kind"], "plan-refused")
        self.assertIn("donor-shadowing", refusal["message"])
        self.assertIn("no base listing says which image and material names the base owns", refusal["message"])

    def test_a_listing_beside_the_link_loads_is_read_and_the_module_qualifies(self):
        self.foundation()
        self.listing()
        directory = self.donor_module()
        code, row = self.qualify(str(directory))
        self.assertEqual(code, 0, row)
        entry = row["result"]["modules"][0]
        self.assertEqual(entry["outcome"], "qualified")
        self.assertEqual(entry["base_listings"], [str(self.load.parent)])
        qualified = json.loads((self.root / entry["job"] / "qualify.json").read_text())
        self.assertEqual(qualified["base_listings"], [str(self.load.parent)])

    def test_the_modules_own_recipe_load_is_what_the_build_links_against(self):
        """The synthesized composition names the foundation's link loads and nothing else; the
        donor zone reaches the linker because the module's own recipe names it, and a composition
        links against every member's loads (docs/MODULES.md, a recipe's `loads`)."""
        self.foundation()
        self.listing()
        directory = self.donor_module()
        code, row = self.qualify(str(directory))
        self.assertEqual(code, 0, row)
        entry = row["result"]["modules"][0]
        self.assertEqual(entry["outcome"], "qualified")
        qualified = json.loads((self.root / entry["job"] / "qualify.json").read_text())
        composition = json.loads((self.root / qualified["composition"]).read_text())
        self.assertEqual([Path(load).name for load in composition["loads"]], ["common_zm.ff"],
                         "the route writes the foundation's link loads and nothing else")
        for phase in ("unqualified", "qualified"):
            receipt = json.loads((self.root / entry["receipts"][f"build-{phase}"]).read_text())
            loaded = [a for step in receipt["steps"] for a in step["argv"] if str(a).endswith(".ff")]
            self.assertTrue(any(a.endswith("zm_moon_patch.ff") for a in loaded), f"{phase}: {loaded}")
            self.assertTrue(any(a.endswith("common_zm.ff") for a in loaded), f"{phase}: {loaded}")
            plan = json.loads((self.root / Path(entry["receipts"][f"plan-{phase}"]).parent / "plan.json").read_text())
            self.assertEqual([Path(load).name for load in plan["modules"][0]["recipe_loads"]], ["zm_moon_patch.ff"])
            self.assertEqual((plan["donor_loads"], plan["base_loads"]), (["zm_moon_patch"], ["common_zm"]))
            # The staged shelf is what both builds read; the module directory is never linked from.
            self.assertNotIn(str(directory / "donor" / "zm_moon_patch.ff"), plan["loads"])

    def test_a_foundation_that_names_its_listings_directory_is_read_too(self):
        path = self.foundation()
        record = json.loads(path.read_text())
        listings = self.root / "listings"
        listings.mkdir(parents=True, exist_ok=True)
        (listings / "common_zm-list.txt").write_text("image, camo_zombies_nml\n")
        record["base_listings"] = ["listings"]
        path.write_text(json.dumps(record, indent=2))
        code, row = self.qualify(str(self.donor_module()))
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["modules"][0]["base_listings"], [str(listings)])


class QualifyLooseOverrideTests(QualifyFixture):
    """`loose-overrides` is machine state: a file in Plutonium's global `storage/t6/images` that no
    package contains, that every mod folder and the bare game read, and that no build can change.
    A module qualified alone is judged on its package bytes, so the row is recorded, not refusing.
    `module plan` and `module build` invoked directly are unchanged and still refuse."""

    def setUp(self):
        super().setUp()
        self.foundation()
        (self.load.parent / "common_zm-list.txt").write_text("image, camo_zombies_nml\nmaterial, mtl_stock\n")
        storage = self.root / "storage" / "t6"
        (storage / "images").mkdir(parents=True, exist_ok=True)
        (storage / "images" / "camo_zombies_nml.iwi").write_bytes(b"IWi\x0d" + b"\0" * 32)
        code, row = invoke(["configure", "--plutonium-storage-t6", str(storage)])
        self.assertEqual(code, 0, row)

    def donor_module(self, mid="alpha"):
        directory = self.module(mid, bases=["stock"], maps=["zm_transit"])
        donor = directory / "donor" / "zm_moon_patch.ff"
        donor.parent.mkdir(parents=True, exist_ok=True)
        donor.write_text(json.dumps({"zone": "zm_moon_patch", "assets": [], "rawfiles": {}}))
        recipe = json.loads((directory / "project.json").read_text())
        recipe["loads"] = ["donor/zm_moon_patch.ff"]
        (directory / "project.json").write_text(json.dumps(recipe, indent=2))
        return directory

    def test_a_loose_shadowing_file_is_a_warning_on_the_module_not_a_refusal(self):
        directory = self.donor_module()
        code, row = self.qualify(str(directory))
        self.assertEqual(code, 0, row)
        entry = row["result"]["modules"][0]
        self.assertEqual(entry["outcome"], "qualified")
        self.assertEqual([w["id"] for w in entry["warnings"]], ["loose-overrides", "loose-overrides:camo_zombies_nml"])
        self.assertTrue(all(w["outcome"] == "failed" for w in entry["warnings"]))
        qualified = json.loads((self.root / entry["job"] / "qualify.json").read_text())
        self.assertEqual([w["id"] for w in qualified["warnings"]], [w["id"] for w in entry["warnings"]])
        book = json.loads((directory / "evidence.json").read_text())
        note = next(r for r in book["rows"] if r["type"] == "built-alone")["note"]
        self.assertIn("loose-overrides: 1 loose global textures shadow base names on this machine "
                      "(not a package fact)", note)

    def test_module_plan_invoked_directly_on_the_same_composition_still_refuses(self):
        code, row = self.qualify(str(self.donor_module()))
        self.assertEqual(code, 0, row)
        entry = row["result"]["modules"][0]
        composition = self.root / json.loads(
            (self.root / entry["job"] / "qualify.json").read_text())["composition"]
        # The same composition, the same listings: only the caller differs.
        code, row = invoke(["module", "plan", str(composition), "--workspace", str(self.root),
                            *sum((["--base-listings", d] for d in entry["base_listings"]), []),
                            "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertIn("loose-overrides:camo_zombies_nml", row["message"])


class QualifyPortStatusTests(QualifyFixture):
    """An unfinished port is composed knowingly or not at all. `qualify` writes the composition on
    the caller's behalf, so `--accept` is the only place the caller can name the status that a
    hand-written composition names under a member's own `accept`."""

    def module_row(self, row, index=0):
        return row.get("result", row.get("details", {}))["modules"][index]

    def composition_of(self, row, index=0):
        entry = self.module_row(row, index)
        return json.loads((self.root / json.loads(
            (self.root / entry["job"] / "qualify.json").read_text())["composition"]).read_text())

    def test_a_loads_but_wrong_module_is_refused_with_the_planners_port_status_row(self):
        self.foundation()
        directory = self.module("alpha", bases=["stock"], maps=["zm_transit"], port_status="loads-but-wrong")
        before = self.read(directory / "module.json")
        code, row = self.qualify(str(directory))
        self.assertEqual(code, 1, row)
        refusal = self.module_row(row)["refusal"]
        self.assertEqual(refusal["kind"], "plan-refused")
        inner = [r for r in refusal["refusals"] if r["kind"] == "port_status"]
        self.assertEqual(len(inner), 1, refusal)
        self.assertEqual(inner[0]["modules"], ["alpha"])
        self.assertIn("is loads-but-wrong and this composition does not accept it", inner[0]["message"])
        # Every member of the synthesized composition is the plain path it has always been.
        self.assertTrue(all(isinstance(m, str) for m in self.composition_of(row)["modules"]))
        self.assertEqual(self.read(directory / "module.json"), before)

    def test_accepting_the_status_qualifies_it_and_the_records_say_what_was_accepted(self):
        self.foundation()
        self.bindings("alpha")
        directory = self.module("alpha", bases=["stock"], maps=["zm_transit"], port_status="loads-but-wrong")
        code, row = self.qualify(str(directory), "--accept", "loads-but-wrong")
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["accept"], ["loads-but-wrong"])
        entry = self.module_row(row)
        self.assertEqual(entry["outcome"], "qualified")
        self.assertEqual(entry["accept"], ["loads-but-wrong"])
        self.assertEqual(entry["port_status"], "loads-but-wrong")
        self.assertEqual(entry["accepted_members"], [{"id": "alpha", "port_status": "loads-but-wrong"}])

        # The member is an object naming the acceptance, which is what the planner reads.
        member = self.composition_of(row)["modules"][0]
        self.assertEqual(member["accept"], ["loads-but-wrong"])
        self.assertTrue(member["path"].endswith("alpha"), member)
        qualified = json.loads((self.root / entry["job"] / "qualify.json").read_text())
        self.assertEqual(qualified["accept"], ["loads-but-wrong"])

        # The declaration is widened by the target and says exactly what it said about the port.
        widened = json.loads((directory / "module.json").read_text())
        self.assertEqual(widened["port_status"], "loads-but-wrong")
        self.assertEqual(widened["bases"], ["stock", "b2"])

        note = next(r for r in json.loads((directory / "evidence.json").read_text())["rows"]
                    if r["type"] == "built-alone")["note"]
        self.assertIn("port_status loads-but-wrong accepted for this build; the row says the package "
                      "builds, not that the port is finished.", note)
        self.assertIn("--accept loads-but-wrong", (directory / "docs" / "TEST.md").read_text())

    def test_accepting_another_status_does_not_admit_this_one(self):
        self.foundation()
        directory = self.module("alpha", bases=["stock"], maps=["zm_transit"], port_status="loads-but-wrong")
        code, row = self.qualify(str(directory), "--accept", "not-ported")
        self.assertEqual(code, 1, row)
        refusal = self.module_row(row)["refusal"]
        self.assertEqual([r["kind"] for r in refusal["refusals"]], ["port_status"])
        # The member was written with what the caller named, and it was not this member's status.
        self.assertEqual(self.composition_of(row)["modules"][0]["accept"], ["not-ported"])
        self.assertEqual(json.loads((directory / "module.json").read_text())["bases"], ["stock"])

    def test_a_word_that_is_not_a_takeable_status_is_refused_at_the_argument(self):
        self.foundation()
        directory = self.module("alpha", bases=["stock"], maps=["zm_transit"], port_status="loads-but-wrong")
        code, row = self.qualify(str(directory), "--accept", "finished")
        self.assertEqual(code, 2, row)
        self.assertEqual(row["error_code"], "invalid_arguments")
        self.assertIn("--accept", row["message"])
        code, row = self.qualify(str(directory), "--accept", "mostly-works")
        self.assertEqual(code, 2, row)
        self.assertEqual(row["error_code"], "invalid_arguments")
        # The bounds are a member's own: 1 to 2 distinct statuses, so the same word twice is not a list.
        code, row = self.qualify(str(directory), "--accept", "not-ported", "--accept", "not-ported")
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("distinct statuses", row["message"])
        self.assertEqual(json.loads((directory / "module.json").read_text())["bases"], ["stock"])

    def test_a_dependency_of_an_unfinished_port_is_accepted_the_same_way(self):
        self.foundation()
        self.bindings("alpha")
        dep = self.module("dep", bases=["b2"], maps=["*"], port_status="loads-but-wrong")
        directory = self.module("alpha", bases=["stock"], maps=["zm_transit"], dependencies=["dep"])
        code, row = self.qualify(str(directory))
        self.assertEqual(code, 1, row)
        self.assertEqual([r["modules"] for r in self.module_row(row)["refusal"]["refusals"]
                          if r["kind"] == "port_status"], [["dep"]])

        code, row = self.qualify(str(directory), "--accept", "loads-but-wrong")
        self.assertEqual(code, 0, row)
        entry = self.module_row(row)
        self.assertEqual(entry["port_status"], "finished")
        self.assertEqual(entry["accepted_members"], [{"id": "dep", "port_status": "loads-but-wrong"}])
        members = {Path(m["path"] if isinstance(m, dict) else m).name: m for m in self.composition_of(row)["modules"]}
        self.assertEqual(members["dep"]["accept"], ["loads-but-wrong"])
        self.assertIsInstance(members["alpha"], str, "a finished member stays the plain path")
        note = next(r for r in json.loads((directory / "evidence.json").read_text())["rows"]
                    if r["type"] == "built-alone")["note"]
        self.assertIn("Accepted in the closure: dep (loads-but-wrong).", note)
        self.assertNotIn("port_status finished", note)
        self.assertEqual(json.loads((dep / "module.json").read_text())["port_status"], "loads-but-wrong")
