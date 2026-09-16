"""``module verify-declaration``: a module's declared promises beside what its own bytes say.

The executable half of docs/MODULES.md, "What a checker can verify, kind by kind": every row's
method and its honest ceiling. Fixtures are synthetic modules built the way
``tests/test_compositions.py`` builds them; nothing here reads a game, a base or a private bank.
"""
import json
from pathlib import Path

from tests.test_compositions import CompositionFixture, declaration
from tests.test_dev_routes import invoke

ROOT = Path(__file__).resolve().parents[1]

LISTING = "rawfile, animtrees/zm_transit_basic.atr\n"
SCHEMA = json.loads((ROOT / "schemas/module-verify-v1.schema.json").read_text()) if (ROOT / "schemas/module-verify-v1.schema.json").is_file() else {}


class ModuleVerifyFixture(CompositionFixture):
    def verify(self, directory, *extra, expect=0):
        code, row = invoke(["module", "verify-declaration", str(directory), "--json", *extra])
        self.assertEqual(code, expect, row)
        return row["result"] if expect == 0 else row["details"]["report"]

    def rows(self, result, field, outcome=None):
        return [r for r in result["rows"] if r["field"] == field and (outcome is None or r["outcome"] == outcome)]

    def one(self, result, field, outcome):
        found = self.rows(result, field, outcome)
        self.assertEqual(len(found), 1, f"{field} {outcome}: {self.rows(result, field)}")
        return found[0]

    def listings(self, text=LISTING, name="zm_transit-list.txt"):
        directory = self.root / "listings"
        directory.mkdir(exist_ok=True)
        (directory / name).write_text(text)
        return str(directory)

    def redeclare(self, directory, mid, **overrides):
        (directory / "module.json").write_text(json.dumps(declaration(mid, **overrides), indent=2))
        return directory


class ProvidesTests(ModuleVerifyFixture):
    def test_declared_scripts_agree_with_the_targets_the_recipe_compiles(self):
        directory = self.module("alpha", provides={"scripts": ["scripts/zm/alpha.gsc"]})
        result = self.verify(directory)
        self.assertEqual(result["protocol"], "pat.module-verify/1")
        self.assertEqual((result["module"], result["payload"]), ("alpha", "recipe"))
        row = self.one(result, "/provides/scripts", "agrees")
        self.assertEqual((row["declared"], row["observed"]), (["scripts/zm/alpha.gsc"], ["scripts/zm/alpha.gsc"]))

    def test_a_declared_script_no_recipe_produces_is_declared_not_observed(self):
        directory = self.module("alpha", provides={"scripts": ["scripts/zm/alpha.gsc", "scripts/zm/absent.gsc"]})
        result = self.verify(directory)
        self.assertEqual(self.one(result, "/provides/scripts", "declared_not_observed")["declared"], ["scripts/zm/absent.gsc"])
        self.assertEqual(self.one(result, "/provides/scripts", "agrees")["observed"], ["scripts/zm/alpha.gsc"])

    def test_a_staged_rawfile_the_declaration_omits_is_observed_not_declared(self):
        directory = self.module_with_assets("alpha", [{"source": "assets/notes.txt", "target": "loot/notes.txt", "type": "rawfile"}])
        result = self.verify(directory)
        row = self.one(result, "/provides/rawfiles", "observed_not_declared")
        self.assertEqual((row["declared"], row["observed"]), ([], ["loot/notes.txt"]))

    def test_weapons_come_from_the_recipe_row_and_the_registration_literal_and_stay_partial(self):
        source = 'main()\n{\n    include_zombie_weapon("x_zm");\n    // include_zombie_weapon("commented_zm");\n}\n'
        directory = self.module_with_assets("alpha", [{"source": "assets/wpn.gdt", "target": "weapons/other_zm",
                                                       "type": "weapon", "name": "other_zm"}], script=source)
        self.redeclare(directory, "alpha", provides={"weapons": ["x_zm", "other_zm"]})
        result = self.verify(directory)
        row = self.one(result, "/provides/weapons", "partial")
        self.assertEqual(row["observed"], ["other_zm", "x_zm"])
        self.assertIn("computed name", row["note"])
        self.assertFalse(any("commented_zm" in json.dumps(r) for r in result["rows"]), "a commented registration is not one")

    def test_localize_comes_from_the_str_reference_lines_and_from_the_ampersand_literal(self):
        source = 'main()\n{\n    self setText(&"ALPHA_HINT");\n    // &"COMMENTED_HINT"\n}\n'
        directory = self.module_with_assets("alpha", [{"source": "assets/alpha.str", "target": "english/localizedstrings/alpha.str",
                                                       "type": "localize", "name": "alpha"}], script=source)
        (directory / "assets" / "alpha.str").write_text('VERSION "1"\nREFERENCE ALPHA_NAME\nLANG_ENGLISH "Alpha"\n')
        self.redeclare(directory, "alpha", provides={"localize": ["ALPHA_NAME", "ALPHA_HINT"]})
        result = self.verify(directory)
        self.assertEqual(self.one(result, "/provides/localize", "agrees")["observed"], ["ALPHA_HINT", "ALPHA_NAME"])
        self.assertFalse(any("COMMENTED_HINT" in json.dumps(r) for r in result["rows"]))

    def test_a_perk_id_is_partial_when_the_literal_is_there_and_missing_when_it_is_not(self):
        source = 'main()\n{\n    level thread give("speed_cola");\n}\n'
        directory = self.module_with_assets("alpha", [], script=source)
        self.redeclare(directory, "alpha", provides={"perks": ["speed_cola", "absent_perk"]})
        result = self.verify(directory)
        row = self.one(result, "/provides/perks", "partial")
        self.assertEqual(row["declared"], ["speed_cola"])
        self.assertIn("not proof it was registered", row["note"])
        self.assertEqual(self.one(result, "/provides/perks", "declared_not_observed")["declared"], ["absent_perk"])


class ReplacementTests(ModuleVerifyFixture):
    SOURCE = ("main()\n{\n"
              "    // replaceFunc(maps\\mp\\zombies\\_zm::prose_only, ::x) in a comment is prose\n"
              "    replaceFunc(maps\\mp\\zombies\\_zm::round_think, ::x);\n}\n")

    def test_replaced_functions_are_read_in_both_directions_and_a_comment_does_not_count(self):
        directory = self.module_with_assets("alpha", [], script=self.SOURCE)
        self.redeclare(directory, "alpha", provides={"scripts": ["scripts/zm/alpha.gsc"]},
                       replaces={"functions": ["maps/mp/zombies/_zm::round_think", "maps/mp/zombies/_zm::declared_only"], "files": []})
        result = self.verify(directory)
        self.assertEqual(self.one(result, "/replaces/functions", "agrees")["observed"], ["maps/mp/zombies/_zm::round_think"])
        self.assertEqual(self.one(result, "/replaces/functions", "declared_not_observed")["declared"],
                         ["maps/mp/zombies/_zm::declared_only"])
        self.assertFalse(any("prose_only" in json.dumps(r) for r in result["rows"]))

    def test_a_source_replacement_the_declaration_omits_is_observed_not_declared(self):
        directory = self.module_with_assets("alpha", [], script=self.SOURCE)
        self.redeclare(directory, "alpha", provides={"scripts": ["scripts/zm/alpha.gsc"]})
        result = self.verify(directory)
        self.assertEqual(self.one(result, "/replaces/functions", "observed_not_declared")["observed"],
                         ["maps/mp/zombies/_zm::round_think"])

    def test_a_base_owned_table_a_listing_names_is_observed_not_declared_with_its_evidence(self):
        directory = self.module_with_assets("alpha", [{"source": "assets/tree.atr", "target": "animtrees/zm_transit_basic.atr",
                                                       "type": "rawfile"}])
        result = self.verify(directory, "--base-listings", self.listings())
        row = self.one(result, "/replaces/files", "observed_not_declared")
        self.assertEqual(row["observed"], ["animtrees/zm_transit_basic.atr"])
        self.assertEqual(result["stages"]["base_owned"],
                         [{"path": "animtrees/zm_transit_basic.atr", "owner": "base", "evidence": "listing"}])

    def test_without_a_listing_or_a_target_a_base_namespace_path_is_not_counted_with_the_evidence_that_would_decide_it(self):
        directory = self.module_with_assets("alpha", [{"source": "assets/tree.atr", "target": "animtrees/zm_transit_basic.atr",
                                                       "type": "rawfile"}])
        result = self.verify(directory)
        row = self.one(result, "/replaces/files", "not_counted")
        self.assertEqual(row["observed"], ["animtrees/zm_transit_basic.atr"])
        self.assertIn("--base-listings", row["note"])
        self.assertIn("--target", row["note"])
        self.assertEqual(result["stages"]["base_owned"], [])
        self.assertEqual(result["stages"]["new_in_base_namespace"], ["animtrees/zm_transit_basic.atr"])

    def test_the_shipped_per_map_table_decides_a_staged_stock_script_for_the_named_target(self):
        directory = self.module("alpha", script_target="maps/mp/zombies/_zm_weapons.gsc",
                                provides={"scripts": ["maps/mp/zombies/_zm_weapons.gsc"]})
        result = self.verify(directory, "--target", "stock/zm_transit")
        self.assertEqual(self.one(result, "/replaces/files", "observed_not_declared")["observed"],
                         ["maps/mp/zombies/_zm_weapons.gsc"])
        self.assertEqual(result["stages"]["base_owned"],
                         [{"path": "maps/mp/zombies/_zm_weapons.gsc", "owner": "map", "evidence": "table"}])

    def test_a_declared_file_the_evidence_confirms_agrees_and_an_accuracy_table_is_never_a_refusal(self):
        directory = self.module_with_assets("alpha", [
            {"source": "assets/tree.atr", "target": "animtrees/zm_transit_basic.atr", "type": "rawfile"},
            {"source": "assets/pistol.accu", "target": "accuracy/aivsplayer/pistol.accu", "type": "rawfile"}])
        self.redeclare(directory, "alpha", replaces={"functions": [], "files": ["animtrees/zm_transit_basic.atr"]})
        result = self.verify(directory, "--base-listings", self.listings())
        self.assertEqual(self.one(result, "/replaces/files", "agrees")["declared"], ["animtrees/zm_transit_basic.atr"])
        self.assertEqual(self.rows(result, "/replaces/files", "observed_not_declared"), [])
        self.assertEqual([row["path"] for row in result["stages"]["engine_tables"]], ["accuracy/aivsplayer/pistol.accu"])
        self.assertIn("search path", result["stages"]["engine_tables"][0]["note"])
        self.assertNotIn("accuracy/aivsplayer/pistol.accu", [row["path"] for row in result["stages"]["base_owned"]])


class DependencyTests(ModuleVerifyFixture):
    def shelf(self):
        self.module("dep_bank", script_target="scripts/zm/dep_util.gsc",
                    provides={"scripts": ["scripts/zm/dep_util.gsc"], "powerups": ["zap_all"]})
        return str(self.root)

    def dependent(self, source, dependencies):
        directory = self.module_with_assets("alpha", [], script=source)
        self.redeclare(directory, "alpha", provides={"scripts": ["scripts/zm/alpha.gsc"]}, dependencies=dependencies)
        return directory

    def test_a_call_edge_agrees_when_the_source_calls_a_script_the_dependency_provides(self):
        workspace = self.shelf()
        directory = self.dependent("main()\n{\n    dep_util::setup();\n}\n", [{"id": "dep_bank", "kind": "call"}])
        row = self.one(self.verify(directory, "--workspace", workspace), "/dependencies/0", "agrees")
        self.assertIn("call", row["observed"])

    def test_a_name_edge_agrees_on_a_powerup_literal_the_dependency_registers(self):
        workspace = self.shelf()
        directory = self.dependent('main()\n{\n    give("zap_all");\n}\n', [{"id": "dep_bank", "kind": "name"}])
        row = self.one(self.verify(directory, "--workspace", workspace), "/dependencies/0", "agrees")
        self.assertIn("name", row["observed"])

    def test_an_edge_nothing_justifies_is_declared_not_observed_and_an_entry_with_no_kind_reports_what_it_found(self):
        workspace = self.shelf()
        directory = self.dependent("main()\n{\n    wait 1;\n}\n", [{"id": "dep_bank", "kind": "call"}])
        self.assertEqual(self.one(self.verify(directory, "--workspace", workspace), "/dependencies/0",
                                  "declared_not_observed")["observed"], [])
        directory = self.dependent("main()\n{\n    dep_util::setup();\n}\n", ["dep_bank"])
        row = self.one(self.verify(directory, "--workspace", workspace), "/dependencies/0", "agrees")
        self.assertEqual(row["declared"], [])
        self.assertIn("call", row["observed"])

    def test_a_runtime_edge_is_declaration_only_and_no_workspace_counts_nothing(self):
        workspace = self.shelf()
        directory = self.dependent("main()\n{\n    wait 1;\n}\n",
                                   [{"id": "dep_bank", "kind": "runtime", "why": "reads level.dep_ready from that module's init"}])
        row = self.one(self.verify(directory, "--workspace", workspace), "/dependencies/0", "not_counted")
        self.assertIn("declaration-only", row["note"])
        directory = self.dependent("main()\n{\n    dep_util::setup();\n}\n", [{"id": "dep_bank", "kind": "call"}])
        self.assertIn("--workspace", self.one(self.verify(directory), "/dependencies/0", "not_counted")["note"])


class RoleServiceAndContractTests(ModuleVerifyFixture):
    HUD = 'main()\n{\n    level.counter = newHudElem();\n    level.label = createFontString("default", 1.5);\n}\n'

    def test_a_hud_footprint_without_the_role_is_observed_not_declared_and_with_it_is_partial(self):
        directory = self.module_with_assets("alpha", [], script=self.HUD)
        self.redeclare(directory, "alpha", provides={"scripts": ["scripts/zm/alpha.gsc"]})
        row = self.one(self.verify(directory), "/exclusive", "observed_not_declared")
        self.assertEqual(row["observed"], ["hud"])
        self.assertIn("looks like a hud owner", row["note"])

        self.redeclare(directory, "alpha", provides={"scripts": ["scripts/zm/alpha.gsc"]}, exclusive=["hud"])
        row = self.one(self.verify(directory), "/exclusive", "partial")
        self.assertEqual((row["declared"], row["observed"]), (["hud"], ["hud"]))
        self.assertIn("author's promise", row["note"])

    def test_a_declared_role_with_no_footprint_is_declared_not_observed(self):
        directory = self.module("alpha", provides={"scripts": ["scripts/zm/alpha.gsc"]}, exclusive=["box"])
        self.assertEqual(self.one(self.verify(directory), "/exclusive", "declared_not_observed")["declared"], ["box"])

    def test_a_service_that_shares_something_and_registers_no_weapon_agrees(self):
        directory = self.module("alpha", provides={"scripts": ["scripts/zm/alpha.gsc"]}, service=True)
        row = self.one(self.verify(directory), "/service", "agrees")
        self.assertIn("intent is declaration-only", row["note"])

    def test_the_hud_contract_is_a_floor_and_a_declared_zero_with_constructors_is_observed_not_declared(self):
        directory = self.module_with_assets("alpha", [], script=self.HUD)
        self.redeclare(directory, "alpha", provides={"scripts": ["scripts/zm/alpha.gsc"]})
        row = self.one(self.verify(directory), "/resource_contract/hud", "observed_not_declared")
        self.assertEqual((row["declared"], row["observed"]), ([0], [2]))
        self.assertIn("floor", row["note"])

        self.redeclare(directory, "alpha", provides={"scripts": ["scripts/zm/alpha.gsc"]},
                       resource_contract={"threads": 1, "entities": 0, "hud": 4, "network_fields": 0})
        self.assertEqual(self.one(self.verify(directory), "/resource_contract/hud", "partial")["observed"], [2])

    def test_every_field_this_route_reads_nothing_for_says_so_with_its_reason(self):
        result = self.verify(self.module("alpha", provides={"scripts": ["scripts/zm/alpha.gsc"]}))
        for field in ("/menu_route", "/tags", "/placements", "/parameters", "/bases", "/maps"):
            self.assertTrue(self.rows(result, field, "not_counted")[0]["note"], field)


class GateAndProposalTests(ModuleVerifyFixture):
    def test_strict_exits_one_on_a_difference_and_zero_when_every_row_agrees(self):
        clean = self.module("alpha", provides={"scripts": ["scripts/zm/alpha.gsc"]})
        result = self.verify(clean, "--strict")
        self.assertEqual(result["summary"]["declared_not_observed"], 0)
        self.assertEqual(result["summary"]["observed_not_declared"], 0)

        drifted = self.module("beta", provides={"scripts": ["scripts/zm/beta.gsc", "scripts/zm/absent.gsc"]})
        report = self.verify(drifted, "--strict", expect=1)
        self.assertEqual(report["module"], "beta")
        self.assertTrue(self.rows(report, "/provides/scripts", "declared_not_observed"))

    def test_propose_fills_replaces_files_and_dependency_kinds_and_removes_no_declared_name(self):
        self.module("dep_bank", script_target="scripts/zm/dep_util.gsc", provides={"scripts": ["scripts/zm/dep_util.gsc"]})
        directory = self.module_with_assets("alpha", [{"source": "assets/tree.atr", "target": "animtrees/zm_transit_basic.atr",
                                                       "type": "rawfile"}],
                                            script="main()\n{\n    dep_util::setup();\n}\n")
        self.redeclare(directory, "alpha", dependencies=["dep_bank"],
                       provides={"scripts": ["scripts/zm/alpha.gsc"], "perks": ["kept_perk"]})
        result = self.verify(directory, "--workspace", str(self.root), "--base-listings", self.listings(), "--propose")
        self.assertEqual(result["proposal"]["replaces"]["files"], ["animtrees/zm_transit_basic.atr"])
        self.assertEqual(result["proposal"]["dependencies"], [{"id": "dep_bank", "kind": "call"}])
        self.assertIn("animtrees/zm_transit_basic.atr", result["proposal"]["provides"]["rawfiles"])
        self.assertEqual(result["proposal"]["provides"]["perks"], ["kept_perk"], "a proposal never removes a declared name")
        self.assertIn("exclusive and service are not proposed", " ".join(result["proposal_notes"]))
        self.assertEqual(json.loads((directory / "module.json").read_text())["provides"]["perks"], ["kept_perk"])


class InertnessTests(ModuleVerifyFixture):
    def test_the_route_writes_nothing_and_takes_no_output_directory(self):
        directory = self.module("alpha", provides={"scripts": ["scripts/zm/alpha.gsc"]})
        before = sorted(p.relative_to(directory).as_posix() for p in directory.rglob("*"))
        self.verify(directory)
        self.assertEqual(sorted(p.relative_to(directory).as_posix() for p in directory.rglob("*")), before)
        self.assertFalse((self.root / "job-001").exists())
        code, row = invoke(["module", "verify-declaration", str(directory), "--json", "--output", self.out()])
        self.assertEqual((code, row["error_code"]), (2, "invalid_arguments"), row)
        self.assertIn("--output", row["message"])
        self.assertFalse(Path(self.root / "job-001").exists(), "a refused --output creates nothing")

    def test_the_producer_schema_required_fields_match_the_result_and_every_row(self):
        result = self.verify(self.module("alpha", provides={"scripts": ["scripts/zm/alpha.gsc"]}), "--propose")
        report = SCHEMA["$defs"]["report"]
        self.assertEqual(set(result), set(report["required"]) | {"proposal", "proposal_notes"})
        self.assertFalse(report["additionalProperties"])
        self.assertEqual(set(result["stages"]), set(report["properties"]["stages"]["required"]))
        self.assertEqual(set(result["summary"]), set(report["properties"]["summary"]["required"]))
        self.assertEqual(set(result["inputs"]), set(report["properties"]["inputs"]["required"]))
        outcomes = set(SCHEMA["$defs"]["row"]["properties"]["outcome"]["enum"])
        self.assertEqual(outcomes, set(result["summary"]))
        for row in result["rows"]:
            self.assertEqual(set(row) - {"note"}, set(SCHEMA["$defs"]["row"]["required"]), row)
            self.assertIn(row["outcome"], outcomes)
        self.assertEqual(report["properties"]["protocol"]["const"], result["protocol"])

    def test_the_manifest_lists_the_route_as_an_implemented_inert_one(self):
        code, row = invoke(["manifest"])
        self.assertEqual(code, 0, row)
        route = next(r for r in row["result"]["routes"] if r["id"] == "module.verify-declaration")
        self.assertEqual((route["effect"], route["status"], route["available_here"]), ("inert", "implemented", True))
        self.assertIn("pat.module-verify/1", route["notes"])
        self.assertTrue((Path(__file__).resolve().parents[1] / "schemas/module-verify-v1.schema.json").is_file())


class RegistrationTests(ModuleVerifyFixture):
    """The registration line: `self` needs the literal in source, `entry` needs the entry field,
    `none` must print nothing, and an absent field is reported and proposed, never invented."""

    def printing(self, mid, **over):
        d = self.module(mid, **over)
        (d / "scripts" / f"{mid}.gsc").write_text(
            f'main()\n{{\n    println("{mid} >> registered");\n}}\n')
        return d

    def test_self_with_the_literal_is_partial_and_without_it_is_declared_not_observed(self):
        row = self.one(self.verify(self.printing("alpha", registration="self")), "/registration", "partial")
        self.assertEqual(row["observed"], ["self"])
        self.one(self.verify(self.module("beta", registration="self")), "/registration", "declared_not_observed")

    def test_a_commented_line_does_not_count(self):
        d = self.module("alpha", registration="self")
        (d / "scripts" / "alpha.gsc").write_text('main()\n{\n    // println("alpha >> registered");\n}\n')
        self.one(self.verify(d), "/registration", "declared_not_observed")

    def test_none_agrees_when_silent_and_is_observed_not_declared_when_it_prints(self):
        self.one(self.verify(self.module("alpha", registration="none")), "/registration", "agrees")
        self.one(self.verify(self.printing("beta", registration="none")), "/registration", "observed_not_declared")

    def test_entry_agrees_on_the_entry_field_alone(self):
        d = self.module("alpha", registration="entry",
                        entry={"replace": "scripts/zm/alpha::alpha_replace", "register": "scripts/zm/alpha::alpha_register"})
        (d / "scripts" / "alpha.gsc").write_text("alpha_replace()\n{\n}\n\nalpha_register()\n{\n}\n")
        self.assertEqual(self.one(self.verify(d), "/registration", "agrees")["observed"], ["entry"])

    def test_absent_is_not_counted_when_silent_and_observed_when_it_prints_and_propose_fills_the_word(self):
        row = self.one(self.verify(self.module("alpha")), "/registration", "not_counted")
        self.assertIn("does not say", row["note"])
        result = self.verify(self.printing("beta"), "--propose")
        self.one(result, "/registration", "observed_not_declared")
        self.assertEqual(result["proposal"]["registration"], "self")

    def test_another_spelling_is_reported_and_does_not_match(self):
        d = self.module("alpha", registration="self")
        (d / "scripts" / "alpha.gsc").write_text('main()\n{\n    println("ALPHA >> registered (stock module)");\n}\n')
        row = self.one(self.verify(d), "/registration", "declared_not_observed")
        self.assertIn("ALPHA >> registered", row["note"])
