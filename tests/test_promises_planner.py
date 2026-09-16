"""The planner half of what a module promises: the `exclusive` and `ownership` refusals.

docs/MODULES.md, "What a module promises", specifies both. `exclusive` fires when two members
claim a role a pack has room for one owner of; `ownership` fires when one member stages a path the
base's own listings or the shipped per-map tables say the base or the map already carries and does
not declare it under `replaces.files`. One member is enough for `ownership`, because the overwrite
does not wait for a second one, and the evidence is always a listing or a table: `MAP_OWNED_PREFIXES`
is a guess about ownership and never refuses a single member on its own.

Every fixture here is synthetic. The listings are two hand-written rows apiece, not a capture.
"""
import json
import unittest
from pathlib import Path

from tests.test_adapters import AdapterFixture
from tests.test_compositions import CompositionFixture, SeedFixture
from tests.test_dev_routes import invoke

MAP_TABLE = "animtrees/zm_transit_basic.atr"       # the map's own zone carries this rawfile
MAP_SCRIPT = "maps/mp/zombies/_zm_weapons.gsc"     # knowledge/map-scripts.json carries this on stock
BASE_VISION = "vision/zombie.vision"               # a shared base zone carries this one
NEW_TABLE = "animtrees/halo_new_thing.atr"         # under MAP_OWNED_PREFIXES and owned by nobody


class PlannerFixture(CompositionFixture):
    """setUp and helpers only, so the subclasses do not re-run each other."""

    def listings(self):
        """Two synthetic base listings: the map's own zone, and a zone the whole base loads."""
        directory = self.root / "packs" / "listings"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "zm_transit-list.txt").write_text(
            'Loaded zone "zm_transit" (T6)\nrawfile, ' + MAP_TABLE + "\nscript, aitype/zm_transit_basic.gsc\n")
        (directory / "common_zm-list.txt").write_text("rawfile, " + BASE_VISION + "\n")
        return ["../listings/zm_transit-list.txt", "../listings/common_zm-list.txt"]

    def declare(self, directory, **overrides):
        """Rewrite a module's declaration in place, so a staged module can also promise."""
        path = directory / "module.json"
        data = json.loads(path.read_text())
        data.update(overrides)
        path.write_text(json.dumps(data, indent=2))
        return directory

    def stages(self, mid, target, deliver=True, replaces=None, **overrides):
        """A module that delivers (or withholds) one rawfile at ``target``."""
        row = {"source": f"assets/{mid}.bin", "target": target, "type": "rawfile"}
        if not deliver:
            row["deliver"] = False
        directory = self.module_with_assets(mid, [row])
        if replaces is not None:
            overrides["replaces"] = {"functions": [], "files": replaces}
        return self.declare(directory, **overrides) if overrides else directory

    def service_module(self, mid, owns, **overrides):
        """A shelf module that exists to own a shared file, in this workspace's ``modules/``."""
        return self.module(mid, service=True, provides={"rawfiles": [owns]}, **overrides)

    def plan(self, comp, *extra):
        return invoke(["module", "plan", str(comp), "--output", self.out(), *extra])

    def rows(self, result, kind):
        return [r for r in result["details"]["refusals"] if r["kind"] == kind]

    def warnings_of(self, result):
        output = result.get("result", {}).get("output") or Path(result["receipt"]).parent
        return json.loads((Path(output) / "plan.json").read_text())["warnings"]


class ExclusiveRole(PlannerFixture):
    """Two members that own the same role, and the two honest ways out of it."""

    def test_two_owners_refuse_with_the_role_the_order_and_the_resolutions(self):
        self.module("alpha", exclusive=["hud"])
        self.module("beta", exclusive=["hud"])
        code, row = self.plan(self.composition(["alpha", "beta"], name="stock_hud_test"))
        self.assertEqual(code, 1, row)
        [refusal] = self.rows(row, "exclusive")
        self.assertEqual(refusal["role"], "hud")
        self.assertEqual(refusal["modules"], ["alpha", "beta"])
        self.assertEqual(refusal["message"], "two members own hud: alpha, beta")
        self.assertEqual(refusal["hint"], "A pack has one owner per role. Keep one, or drop the other from the composition.")
        self.assertEqual(refusal["resolutions"],
                         [{"kind": "replace", "keep": "beta", "drop": ["alpha"]}, {"kind": "refuse"}])
        self.assertEqual(refusal["field"], "/modules/1/exclusive", "the pointer names the last owner")

    def test_modules_is_composition_order_and_not_dependency_or_sorted_order(self):
        # Reversing the member list reverses the row: `resolve` reads the flattened member list,
        # which `flatten` fills in composition order. Sorted order or the plan's dependency order
        # (alpha first, since `_order` breaks ties by id) would both read alpha, beta here.
        self.module("alpha", exclusive=["box"])
        self.module("beta", exclusive=["box"])
        code, row = self.plan(self.composition(["beta", "alpha"], name="stock_box_test"))
        self.assertEqual(code, 1, row)
        [refusal] = self.rows(row, "exclusive")
        self.assertEqual(refusal["modules"], ["beta", "alpha"])
        self.assertEqual(refusal["resolutions"][0], {"kind": "replace", "keep": "alpha", "drop": ["beta"]})
        self.assertEqual(refusal["field"], "/modules/1/exclusive")

    def test_three_owners_keep_the_newest_and_drop_the_other_two(self):
        for mid in ("alpha", "beta", "gamma"):
            self.module(mid, exclusive=["loadscreen"])
        code, row = self.plan(self.composition(["alpha", "beta", "gamma"], name="stock_load_test"))
        self.assertEqual(code, 1, row)
        [refusal] = self.rows(row, "exclusive")
        self.assertEqual(refusal["modules"], ["alpha", "beta", "gamma"])
        self.assertEqual(refusal["message"], "two members own loadscreen: alpha, beta, gamma")
        self.assertEqual(refusal["resolutions"][0], {"kind": "replace", "keep": "gamma", "drop": ["alpha", "beta"]})
        self.assertEqual(refusal["field"], "/modules/2/exclusive")

    def test_two_roles_one_owner_each_and_a_single_owner_both_plan(self):
        self.module("alpha", exclusive=["hud"])
        self.module("beta", exclusive=["box", "perk-art"])
        code, row = self.plan(self.composition(["alpha", "beta"], name="stock_roles_test"))
        self.assertEqual(code, 0, row)
        code, row = self.plan(self.composition(["alpha"], name="stock_one_role_test"))
        self.assertEqual(code, 0, row)

    def test_one_role_owned_twice_per_role_is_one_row_each(self):
        self.module("alpha", exclusive=["hud", "box"])
        self.module("beta", exclusive=["hud", "box"])
        code, row = self.plan(self.composition(["alpha", "beta"], name="stock_two_roles_test"))
        self.assertEqual(code, 1, row)
        self.assertEqual([r["role"] for r in self.rows(row, "exclusive")], ["box", "hud"])

    def test_the_role_refusal_is_collected_beside_a_missing_dependency_in_one_run(self):
        self.module("alpha", exclusive=["boss"])
        self.module("beta", exclusive=["boss"], dependencies=["absent_module"])
        code, row = self.plan(self.composition(["alpha", "beta"], name="stock_both_test"))
        self.assertEqual(code, 1, row)
        kinds = [r["kind"] for r in row["details"]["refusals"]]
        self.assertIn("exclusive", kinds)
        self.assertIn("missing_dependency", kinds)
        self.assertEqual([r["role"] for r in self.rows(row, "exclusive")], ["boss"])


class OwnershipFromAListing(PlannerFixture):
    """The base's own asset listings are the first source of ownership, and they say which zone."""

    def test_a_staged_map_table_refuses_and_names_the_map_the_path_and_the_evidence(self):
        self.stages("alpha", MAP_TABLE)
        comp = self.composition(["alpha"], name="stock_own_map_test", base_owned=self.listings())
        code, row = self.plan(comp)
        self.assertEqual(code, 1, row)
        [refusal] = self.rows(row, "ownership")
        self.assertEqual(refusal["modules"], ["alpha"])
        self.assertEqual(refusal["path"], MAP_TABLE)
        self.assertEqual(refusal["owner"], "map", "the listing's zone stem starts with the map's name")
        self.assertEqual(refusal["evidence"], "listing")
        self.assertIsNone(refusal["service"])
        self.assertEqual(refusal["field"], "/modules/0/replaces/files")
        self.assertEqual(refusal["message"],
                         f"alpha stages {MAP_TABLE}, which the map already carries, and does not declare it under replaces.files")
        self.assertEqual(refusal["hint"], "Declare the path under replaces.files if this module is meant to overwrite it, "
                                          "or drop the file from the recipe.")

    def test_a_zone_the_whole_base_loads_is_the_base_not_the_map(self):
        self.stages("alpha", BASE_VISION)
        comp = self.composition(["alpha"], name="stock_own_base_test", base_owned=self.listings())
        code, row = self.plan(comp)
        self.assertEqual(code, 1, row)
        [refusal] = self.rows(row, "ownership")
        self.assertEqual((refusal["owner"], refusal["evidence"], refusal["path"]), ("base", "listing", BASE_VISION))
        self.assertIn("which the base already carries", refusal["message"])

    def test_declaring_the_path_under_replaces_files_plans(self):
        self.stages("alpha", MAP_TABLE, replaces=[MAP_TABLE])
        comp = self.composition(["alpha"], name="stock_declared_test", base_owned=self.listings())
        code, row = self.plan(comp)
        self.assertEqual(code, 0, row)
        self.assertEqual(self.warnings_of(row), [], "a declared path the listing carries warns about nothing")

    def test_a_withheld_row_at_the_same_path_overwrites_nothing_and_does_not_refuse(self):
        # `deliver: false` stages the file under raw/ with no zone line, so the base's copy stays.
        self.stages("alpha", MAP_TABLE, deliver=False)
        comp = self.composition(["alpha"], name="stock_withheld_test", base_owned=self.listings())
        code, row = self.plan(comp)
        self.assertEqual(code, 0, row)
        self.assertEqual([w["target"] for w in json.loads(
            (Path(row["result"]["output"]) / "plan.json").read_text())["withheld"]], [MAP_TABLE])

    def test_a_new_file_under_the_prefix_list_is_not_base_owned_and_never_refuses(self):
        # animtrees/ is in MAP_OWNED_PREFIXES, and a prefix is a guess: a module's own new table
        # matches it and overwrites nothing. Only a listing or a table refuses one member.
        self.stages("alpha", NEW_TABLE)
        comp = self.composition(["alpha"], name="stock_new_table_test", base_owned=self.listings())
        code, row = self.plan(comp)
        self.assertEqual(code, 0, row)

    def test_a_weapondef_the_listing_carries_is_read_from_the_listing(self):
        listings = self.listings()
        directory = self.root / "packs" / "listings"
        (directory / "common_zm-list.txt").write_text("rawfile, " + BASE_VISION + "\nweapon, alpha_example_zm\n")
        self.stages("alpha", "weapons/alpha_example_zm")
        comp = self.composition(["alpha"], name="stock_listed_gun_test", base_owned=listings)
        code, row = self.plan(comp)
        self.assertEqual(code, 1, row)
        [refusal] = self.rows(row, "ownership")
        self.assertEqual((refusal["path"], refusal["owner"], refusal["evidence"]),
                         ("weapons/alpha_example_zm", "base", "listing"))

    def test_a_compiled_script_the_listing_carries_refuses_like_a_rawfile(self):
        self.module("alpha", script_target="aitype/zm_transit_basic.gsc")
        comp = self.composition(["alpha"], name="stock_own_script_test", base_owned=self.listings())
        code, row = self.plan(comp)
        self.assertEqual(code, 1, row)
        [refusal] = self.rows(row, "ownership")
        self.assertEqual((refusal["path"], refusal["owner"], refusal["evidence"]),
                         ("aitype/zm_transit_basic.gsc", "map", "listing"))


class OwnershipFromATable(PlannerFixture):
    """With no listing on the machine, the shipped per-map tables answer."""

    def test_a_script_the_map_carries_refuses_on_the_tables_alone(self):
        self.module("alpha", script_target=MAP_SCRIPT)
        code, row = self.plan(self.composition(["alpha"], name="stock_table_test"))
        self.assertEqual(code, 1, row)
        [refusal] = self.rows(row, "ownership")
        self.assertEqual((refusal["path"], refusal["owner"], refusal["evidence"]), (MAP_SCRIPT, "map", "table"))
        self.assertEqual(refusal["field"], "/modules/0/replaces/files")

    def test_declaring_it_plans_and_says_nothing_about_a_listing_it_does_not_have(self):
        directory = self.module("alpha", script_target=MAP_SCRIPT)
        self.declare(directory, replaces={"functions": [], "files": [MAP_SCRIPT]})
        code, row = self.plan(self.composition(["alpha"], name="stock_table_ok_test"))
        self.assertEqual(code, 0, row)
        self.assertEqual(self.warnings_of(row), [], "with no listing the plan cannot judge a declared path")

    def test_a_weapondef_file_for_a_native_name_is_the_same_overwrite(self):
        # A staged weapons/<name> for a name the map's zones already register overwrites the
        # native WeaponDef; the shipped native-weapons table is the evidence.
        self.stages("alpha", "weapons/ak74u_zm")
        code, row = self.plan(self.composition(["alpha"], name="stock_native_file_test"))
        self.assertEqual(code, 1, row)
        [refusal] = self.rows(row, "ownership")
        self.assertEqual((refusal["path"], refusal["owner"], refusal["evidence"]),
                         ("weapons/ak74u_zm", "map", "table"))
        self.stages("beta", "weapons/alpha_new_gun_zm")
        code, row = self.plan(self.composition(["beta"], name="stock_new_gun_test"))
        self.assertEqual(code, 0, f"a new WeaponDef name overwrites nothing: {row}")

    def test_a_map_the_tables_do_not_cover_refuses_nothing(self):
        self.module("alpha", script_target=MAP_SCRIPT, maps=["*"])
        comp = self.composition(["alpha"], name="stock_untabled_test", map_id="zm_untabled_example")
        code, row = self.plan(comp)
        self.assertEqual(code, 0, row)


class OwnershipNamesTheService(PlannerFixture):
    """A file two members would both overwrite is owned by a service, never by either member."""

    def test_the_refusal_names_the_shelf_service_and_its_hint_says_to_depend_on_it(self):
        self.service_module("owner_svc", MAP_TABLE)
        self.stages("alpha", MAP_TABLE)
        comp = self.composition(["alpha"], name="stock_svc_test", base_owned=self.listings())
        code, row = self.plan(comp, "--workspace", str(self.root))
        self.assertEqual(code, 1, row)
        [refusal] = self.rows(row, "ownership")
        self.assertEqual(refusal["service"], "owner_svc")
        self.assertEqual(refusal["hint"], "Depend on owner_svc and ship no copy: a file two members would both overwrite "
                                          "is owned by a service module.")

    def test_a_path_the_ownership_row_reported_is_not_also_a_map_owned_table_service_row(self):
        self.service_module("owner_svc", MAP_TABLE)
        self.stages("alpha", MAP_TABLE)
        self.stages("beta", MAP_TABLE)
        comp = self.composition(["alpha", "beta"], name="stock_svc_once_test", base_owned=self.listings())
        code, row = self.plan(comp, "--workspace", str(self.root))
        self.assertEqual(code, 1, row)
        self.assertEqual([(r["modules"], r["service"]) for r in self.rows(row, "ownership")],
                         [(["alpha"], "owner_svc"), (["beta"], "owner_svc")])
        self.assertEqual([r["collision"] for r in self.rows(row, "service") if r["what"] == "map-owned table"], [],
                         "the ownership rows already named that path and its service")

    def test_the_service_itself_is_never_named_as_its_own_fix(self):
        # The service module in the pack stages what it provides; no row tells it to depend on
        # itself, and it must still declare the overwrite like anyone else.
        self.stages("owner_svc", MAP_TABLE, service=True, provides={"rawfiles": [MAP_TABLE]})
        comp = self.composition(["owner_svc"], name="stock_self_svc_test", base_owned=self.listings())
        code, row = self.plan(comp, "--workspace", str(self.root))
        self.assertEqual(code, 1, row)
        [refusal] = self.rows(row, "ownership")
        self.assertIsNone(refusal["service"])

    def test_the_legacy_tag_is_honoured_once_and_asks_for_the_typed_field(self):
        self.module("tagged_svc", tags=["shared-service"], provides={"rawfiles": [MAP_TABLE]})
        self.stages("alpha", MAP_TABLE)
        comp = self.composition(["alpha"], name="stock_tag_svc_test", base_owned=self.listings())
        code, row = self.plan(comp, "--workspace", str(self.root))
        self.assertEqual(code, 1, row)
        [refusal] = self.rows(row, "ownership")
        self.assertEqual(refusal["service"], "tagged_svc")
        self.assertIn({"module": "tagged_svc",
                       "message": "The shared-service tag is read as service: true for one release; declare service: true"},
                      self.warnings_of(row))


class TwoMembersOnOnePath(PlannerFixture):
    """Undeclared on both sides is two ownership rows; declared on both is the hard refusal."""

    def test_neither_declaring_is_one_ownership_row_per_member(self):
        self.stages("alpha", MAP_TABLE)
        self.stages("beta", MAP_TABLE)
        comp = self.composition(["alpha", "beta"], name="stock_both_stage_test", base_owned=self.listings())
        code, row = self.plan(comp)
        self.assertEqual(code, 1, row)
        rows = self.rows(row, "ownership")
        self.assertEqual([(r["modules"], r["path"], r["owner"], r["evidence"]) for r in rows],
                         [(["alpha"], MAP_TABLE, "map", "listing"), (["beta"], MAP_TABLE, "map", "listing")])
        self.assertEqual([r["field"] for r in rows], ["/modules/0/replaces/files", "/modules/1/replaces/files"])

    def test_both_declaring_is_the_replacement_refusal_whose_collision_carries_the_service(self):
        self.service_module("owner_svc", MAP_TABLE)
        self.stages("alpha", MAP_TABLE, replaces=[MAP_TABLE])
        self.stages("beta", MAP_TABLE, replaces=[MAP_TABLE])
        comp = self.composition(["alpha", "beta"], name="stock_both_declare_test", base_owned=self.listings())
        code, row = self.plan(comp, "--workspace", str(self.root))
        self.assertEqual(code, 1, row)
        self.assertEqual(self.rows(row, "ownership"), [], "a declared overwrite is not an ownership refusal")
        [replacement] = self.rows(row, "replacement")
        self.assertEqual([(c["collision"], c["service"]) for c in replacement["collisions"]],
                         [("file:" + MAP_TABLE, "owner_svc")])
        code, row = self.plan(comp)
        self.assertEqual(code, 1, row)
        [replacement] = self.rows(row, "replacement")
        self.assertIsNone(replacement["collisions"][0]["service"], "no shelf, no module to name")

    def test_a_member_party_to_the_collision_is_never_its_own_service(self):
        self.stages("owner_svc", MAP_TABLE, service=True, provides={"rawfiles": [MAP_TABLE]},
                    replaces=[MAP_TABLE])
        self.stages("beta", MAP_TABLE, replaces=[MAP_TABLE])
        comp = self.composition(["owner_svc", "beta"], name="stock_party_test", base_owned=self.listings())
        code, row = self.plan(comp, "--workspace", str(self.root))
        self.assertEqual(code, 1, row)
        [replacement] = self.rows(row, "replacement")
        self.assertIsNone(replacement["collisions"][0]["service"])


class PayloadsOtherThanARecipe(SeedFixture, AdapterFixture, PlannerFixture):
    """A seed and an adapter stage paths too, and are judged on what their pack roots."""

    def test_a_seed_root_at_a_base_owned_path_refuses(self):
        # A root is what the pack claims the name for; an embedded row that is not a root is a
        # copy the linker took from the base and is left alone.
        self.seed_module("alpha", roots=["weapon,halo_penetrator_zm", "rawfile,scripts/zm/alpha_seeded.gsc"])
        directory = self.root / "packs" / "listings"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "common_zm-list.txt").write_text("rawfile, scripts/zm/alpha_seeded.gsc\n")
        comp = self.composition(["alpha"], name="stock_seed_root_test", base_owned=["../listings/common_zm-list.txt"])
        code, row = self.plan(comp)
        self.assertEqual(code, 1, row)
        [refusal] = self.rows(row, "ownership")
        self.assertEqual((refusal["modules"], refusal["path"], refusal["owner"], refusal["evidence"]),
                         (["alpha"], "scripts/zm/alpha_seeded.gsc", "base", "listing"))

    def test_an_adapter_rawfile_at_a_base_owned_path_refuses(self):
        self.adapter("alpha", rawfiles=[MAP_TABLE])
        comp = self.composition(["alpha"], name="stock_adapter_own_test", base_owned=self.listings())
        code, row = self.plan(comp)
        self.assertEqual(code, 1, row)
        [refusal] = self.rows(row, "ownership")
        self.assertEqual((refusal["path"], refusal["owner"], refusal["evidence"]), (MAP_TABLE, "map", "listing"))


class DeclaredButNotOwned(PlannerFixture):
    """A declared overwrite of a path no evidence says the base carries is a warning, not a refusal."""

    def test_with_a_listing_present_the_plan_warns_and_still_plans(self):
        self.stages("alpha", NEW_TABLE, replaces=["scripts/zm/not_owned.gsc"])
        comp = self.composition(["alpha"], name="stock_not_owned_test", base_owned=self.listings())
        code, row = self.plan(comp)
        self.assertEqual(code, 0, row)
        self.assertIn({"module": "alpha", "target": "scripts/zm/not_owned.gsc",
                       "message": "Declared replaced file is not carried by the base's listings or the map's tables"},
                      self.warnings_of(row))

    def test_with_no_listing_the_plan_says_nothing(self):
        self.stages("alpha", NEW_TABLE, replaces=["scripts/zm/not_owned.gsc"])
        comp = self.composition(["alpha"], name="stock_no_listing_test")
        code, row = self.plan(comp)
        self.assertEqual(code, 0, row)
        self.assertEqual(self.warnings_of(row), [])

    def test_a_path_the_tables_carry_is_not_warned_about(self):
        directory = self.module("alpha", script_target=MAP_SCRIPT)
        self.declare(directory, replaces={"functions": [], "files": [MAP_SCRIPT]})
        comp = self.composition(["alpha"], name="stock_table_declared_test", base_owned=self.listings())
        code, row = self.plan(comp)
        self.assertEqual(code, 0, row)
        self.assertEqual(self.warnings_of(row), [])


if __name__ == "__main__":
    unittest.main()
