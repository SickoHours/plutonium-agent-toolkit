"""``script-reach``: a compiled script is only run if it is packed under a root the client loads.

The engine fact these tests encode, measured on Plutonium T6 (``docs/knowledge/gsc.md``): a mod's
scripts are registered out of ``scripts/zm/`` and nowhere else. A load prints one
``Overridden rawfile: scripts/zm/<name> from zone mod`` per accepted script and none for a rawfile
rooted elsewhere; the first qualified call into such a path prints
``Could not load scriptparsetree "<path>"`` and the load ends in ``SV_Shutdown``. Compiling and a
byte-perfect readback both pass for a script that can never run, so the root is checked here.
"""
import json
from pathlib import Path

from plutonium_agent_toolkit.dev import checks
from tests.test_adapters import AdapterFixture
from tests.test_compositions import CompositionFixture
from tests.test_dev_routes import invoke


class ScriptReachRow(CompositionFixture):
    def test_a_target_outside_the_loaded_root_fails_with_the_console_line_and_the_remedy(self):
        row = checks.script_reach("maps/mp/halo/cr35_buildables.gsc")[0]
        self.assertEqual(row["outcome"], "failed")
        self.assertEqual(row["id"], "script-reach:maps/mp/halo/cr35_buildables.gsc")
        # The engine fact, the line a load prints, and the retarget with the caller rewrite.
        self.assertIn("scripts/zm/", row["detail"])
        self.assertIn('Could not load scriptparsetree "maps/mp/halo/cr35_buildables.gsc"', row["detail"])
        self.assertIn("Retarget to scripts/zm/cr35_buildables.gsc", row["detail"])
        self.assertIn(r"maps\mp\halo\cr35_buildables:: becomes scripts\zm\cr35_buildables::", row["detail"])
        self.assertIn("never registered", row["detail"])

    def test_a_target_under_the_loaded_root_passes_for_either_vm(self):
        for target in ("scripts/zm/halo_probe.gsc", "scripts/zm/halo_probe.csc"):
            self.assertEqual(checks.script_reach(target)[0]["outcome"], "passed", target)

    def test_the_iw5_root_is_the_flat_scripts_namespace(self):
        self.assertEqual(checks.script_reach("scripts/hello.gsc", "iw5")[0]["outcome"], "passed")
        row = checks.script_reach("maps/mp/gametypes/war.gsc", "iw5")[0]
        self.assertEqual(row["outcome"], "failed")
        self.assertIn("Retarget to scripts/war.gsc", row["detail"])
        # T6's root is not IW5's: the check reads the title, never a hardcoded prefix.
        self.assertEqual(checks.script_reach("scripts/zm/x.gsc", "iw5")[0]["outcome"], "passed")
        self.assertEqual(checks.script_reach("scripts/hello.gsc", "t6")[0]["outcome"], "failed")

    def test_a_stock_path_the_map_tables_carry_is_an_override_and_stays_uncounted(self):
        """Every measured case was a module-owned path with nothing to override. Whether a mod
        zone's rawfile overrides a stock scriptparsetree is untested here, so it is not refused --
        and the remedy for an override is not a retarget, which would stop it being one."""
        row = checks.script_reach("maps/mp/zombies/_zm_weapons.gsc")[0]
        self.assertEqual(row["outcome"], "not_counted")
        self.assertIn("override", row["detail"])
        self.assertIn("replacefunc", row["detail"])
        # A module-owned path in the same namespace is not a stock path and still fails.
        self.assertEqual(checks.script_reach("maps/mp/zombies/halo_mine.gsc")[0]["outcome"], "failed")

    def test_case_and_separators_do_not_smuggle_a_path_past_the_root(self):
        for target in ("MAPS/MP/halo/x.gsc", "Scripts/ZM/x.gsc"):
            self.assertEqual(checks.loads_script(target), target.lower().startswith("scripts/zm/"), target)


class ProjectRecipeReach(CompositionFixture):
    """`pat project plan` is where a module built alone is judged, so it refuses there too."""

    def recipe(self, target, name="alone", game="t6", instance="server"):
        d = self.root / "recipes" / name
        (d / "scripts").mkdir(parents=True, exist_ok=True)
        suffix = ".csc" if instance == "client" else ".gsc"
        (d / "scripts" / f"src{suffix}").write_text("main()\n{\n    wait 1;\n}\n")
        (d / "project.json").write_text(json.dumps(
            {"schema": 1, "game": game, "name": name,
             "scripts": [{"source": f"scripts/src{suffix}", "target": target, "instance": instance}],
             "assets": [], "loads": []}))
        return d / "project.json"

    def test_a_maps_target_refuses_the_plan_with_the_remedy_in_the_detail(self):
        recipe = self.recipe("maps/mp/halo/cr35_buildables.gsc")
        code, row = invoke(["project", "plan", str(recipe), "--output", self.out(), "--json"])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertEqual(row["details"]["failed"], ["script-reach:maps/mp/halo/cr35_buildables.gsc"])
        self.assertIn("Retarget to scripts/zm/cr35_buildables.gsc", row["details"]["checks"][0]["detail"])

    def test_the_same_recipe_is_refused_at_build_before_a_backend_runs(self):
        recipe = self.recipe("maps/mp/halo/cr35_buildables.gsc")
        code, row = invoke(["project", "build", str(recipe), "--output", self.out(), "--json"])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["details"]["failed"], ["script-reach:maps/mp/halo/cr35_buildables.gsc"])

    def test_a_scripts_zm_target_plans_and_records_the_passed_row(self):
        out = self.out()
        code, row = invoke(["project", "plan", str(self.recipe("scripts/zm/halo_probe.gsc")), "--output", out, "--json"])
        self.assertEqual(code, 0, row)
        self.assertEqual([c["outcome"] for c in row["result"]["checks"]], ["passed"])
        plan = json.loads((Path(out) / "plan.json").read_text())
        self.assertEqual(plan["checks"][0]["id"], "script-reach:scripts/zm/halo_probe.gsc")

    def test_an_iw5_recipe_is_judged_against_its_own_root(self):
        code, row = invoke(["project", "plan", str(self.recipe("scripts/hello.gsc", name="iw5_ok", game="iw5")),
                            "--output", self.out(), "--json"])
        self.assertEqual(code, 0, row)
        code, row = invoke(["project", "plan", str(self.recipe("maps/mp/gametypes/war.gsc", name="iw5_bad", game="iw5")),
                            "--output", self.out(), "--json"])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["details"]["failed"], ["script-reach:maps/mp/gametypes/war.gsc"])


class PackReach(CompositionFixture):
    def test_a_member_outside_the_root_refuses_the_composition(self):
        self.module("alpha", script_target="maps/mp/halo/alpha.gsc")
        comp = self.composition(["alpha"])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out(), "--json"])
        self.assertEqual(code, 1, row)
        self.assertIn("script-reach:maps/mp/halo/alpha.gsc", row["details"]["failed"])

    def test_a_pack_cannot_vouch_for_a_script_it_ships_where_nothing_opens_it(self):
        """The false pass the old ``provided`` set produced: member B ships the path as a rawfile
        the engine never registers, and B's presence used to make A's call into it 'carried'."""
        a = self.module("alpha")
        (a / "scripts" / "alpha.gsc").write_text(
            "main()\n{\n    maps\\mp\\halo\\beta::init();\n}\n")
        self.module("beta", script_target="maps/mp/halo/beta.gsc")
        comp = self.composition(["alpha", "beta"], name="b2_reach_test", base="b2", map_id="zm_factory")
        code, row = invoke(["module", "plan", str(comp), "--allow-unqualified", "--output", self.out(), "--json"])
        self.assertEqual(code, 1, row)
        failed = row["details"]["failed"]
        self.assertIn("map-scripts:scripts/zm/alpha.gsc", failed)
        self.assertIn("script-reach:maps/mp/halo/beta.gsc", failed)
        detail = row["details"]["refusals"][0]["message"]
        self.assertIn("maps/mp/halo/beta", detail)

    def test_the_map_scripts_detail_names_the_path_and_points_at_the_script_reach_row(self):
        row = checks.map_script_externals(
            "scripts/zm/alpha.gsc", "main()\n{\n    maps\\mp\\halo\\beta::init();\n}\n",
            "zm_factory", "dlc5-beta2", "t6", set(), {"maps/mp/halo/beta.gsc"})[0]
        self.assertEqual(row["outcome"], "failed")
        self.assertIn("maps/mp/halo/beta", row["detail"])
        self.assertIn("script-reach:maps/mp/halo/beta.gsc", row["detail"])
        self.assertEqual(row["unreachable"], ["maps/mp/halo/beta.gsc"])

    def test_a_script_zone_row_a_seed_already_roots_still_carries_the_path(self):
        """A ``script,`` row is a scriptparsetree asset, the one form outside the loaded roots the
        engine does open. It stays in ``provided``; only the rawfile deliveries are filtered."""
        text = "main()\n{\n    maps\\mp\\halo\\penetrator::init();\n}\n"
        row = checks.map_script_externals("scripts/zm/alpha.gsc", text, "zm_factory", "dlc5-beta2", "t6",
                                          {"maps/mp/halo/penetrator.gsc"}, set())[0]
        self.assertEqual(row["outcome"], "passed", row)


class ScriptsRootNarrowing(CompositionFixture):
    """The loose delivery beside the package used to copy everything under ``scripts/`` and now
    copies only what is under the title's loaded roots. The two paths a ``scripts/foo.gsc`` can
    reach that filter by are a compiled script target and a ``rawfile`` asset row; neither may
    stop travelling without a row saying so, and the roots are not widened back."""

    def test_a_compiled_script_at_scripts_foo_is_refused_before_delivery(self):
        self.module("alpha", script_target="scripts/foo.gsc")
        for action in ("plan", "build"):
            code, row = invoke(["module", action, str(self.composition(["alpha"])), "--output", self.out(), "--json"])
            self.assertEqual(code, 1, row)
            self.assertIn("script-reach:scripts/foo.gsc", row["details"]["failed"])
        # The remedy names the loaded root's path, not the packed one, and rewrites the callers.
        detail = checks.script_reach("scripts/foo.gsc")[0]["detail"]
        self.assertIn("Retarget to scripts/zm/foo.gsc", detail)
        self.assertIn(r"scripts\foo:: becomes scripts\zm\foo::", detail)

    def test_a_rawfile_asset_row_at_scripts_foo_is_refused_where_the_recipe_can_be_changed(self):
        """A recipe's own ``rawfile`` row is the other thing in the delivery loop. It is rooted by
        this pack, so the refusal is the honest answer: the path can be changed here."""
        self.module_with_assets("beta", [{"source": "raw/foo.gsc", "target": "scripts/foo.gsc", "type": "rawfile"}])
        code, row = invoke(["module", "plan", str(self.composition(["beta"])), "--output", self.out(), "--json"])
        self.assertEqual(code, 1, row)
        self.assertIn("script-reach:scripts/foo.gsc", row["details"]["failed"])
        # And alone, where `pat module qualify` judges a module: same row, same root.
        d = self.root / "modules" / "beta"
        code, row = invoke(["project", "plan", str(d / "project.json"), "--output", self.out(), "--json"])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["details"]["failed"], ["script-reach:scripts/foo.gsc"])

    def test_a_rawfile_row_under_the_loaded_root_still_travels_loose(self):
        self.module_with_assets("beta", [{"source": "raw/foo.gsc", "target": "scripts/zm/foo.gsc", "type": "rawfile"}])
        code, row = invoke(["module", "build", str(self.composition(["beta"])), "--output", self.out(), "--json"])
        self.assertEqual(code, 0, row)
        self.assertEqual(sorted(row["result"]["loose_scripts"]), ["scripts/zm/beta.gsc", "scripts/zm/foo.gsc"])


class CarriedNotDelivered(AdapterFixture):
    """A ``rawfile,scripts/foo.gsc`` row already inside a member's own package. This pack does not
    root it, so there is nothing to retarget and it is not refused -- but it is not delivered loose
    either, and that is now a row on the plan instead of an absence from ``loose_scripts``."""

    def test_an_embedded_rawfile_script_is_not_delivered_loose_and_is_named_in_a_row(self):
        self.adapter("civil", rawfiles=["scripts/foo.gsc"])
        out = self.out()
        code, row = invoke(["module", "build", str(self.composition(["civil"], name="stock_adapter_test")),
                            "--output", out, "--json"])
        self.assertEqual(code, 0, row)
        # Not delivered: only the adapter's own staged script, which is under the loaded root.
        self.assertEqual(row["result"]["loose_scripts"], ["scripts/zm/halo_civil.gsc"])
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        carried = [c for c in plan["checks"] if c["id"] == "script-reach:scripts/foo.gsc"]
        self.assertEqual([c["outcome"] for c in carried], ["not_counted"], plan["checks"])
        detail = carried[0]["detail"]
        self.assertIn("scripts/foo.gsc", detail)
        self.assertIn("does not travel loose beside the package", detail)
        self.assertIn("scripts/zm/", detail)
        self.assertIn("no target to retarget", detail)
        # The row is the only thing that names this drop: `map-scripts` judges the stock namespaces
        # only, so a caller into a `scripts/...` path of this kind raises no row of its own.
        caller = checks.map_script_externals("scripts/zm/alpha.gsc", "main()\n{\n    scripts\\foo::init();\n}\n",
                                             "zm_transit", "bo2-stock", "t6", set(), {"scripts/foo.gsc"})[0]
        self.assertEqual(caller["outcome"], "not_counted", "scripts/ is not a stock namespace map-scripts judges")
        # And the roots are not widened to reach it: it is still absent from the loose delivery.
        self.assertNotIn("scripts/foo.gsc", row["result"]["loose_scripts"])

    def test_an_embedded_rawfile_script_under_the_loaded_root_is_not_named_unreachable(self):
        self.adapter("civil", rawfiles=["scripts/zm/civil_extra.gsc"])
        code, row = invoke(["module", "plan", str(self.composition(["civil"], name="stock_adapter_test")),
                            "--output", self.out(), "--json"])
        self.assertEqual(code, 0, row)
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        self.assertEqual([c["id"] for c in plan["checks"] if c["id"].startswith("script-reach:")
                          and "civil_extra" in c["id"]], [])


class LooseDelivery(CompositionFixture):
    def test_only_a_script_under_a_loaded_root_travels_loose_beside_the_package(self):
        a = self.module("alpha")
        recipe = json.loads((a / "project.json").read_text())
        # main() stays empty: the client VM runs it before its own rows exist (`csc-main-body`).
        (a / "scripts" / "alpha.csc").write_text("main()\n{\n}\n\ninit()\n{\n    wait 1;\n}\n")
        recipe["scripts"].append({"source": "scripts/alpha.csc", "target": "scripts/zm/alpha.csc", "instance": "client"})
        (a / "project.json").write_text(json.dumps(recipe))
        code, row = invoke(["module", "build", str(self.composition(["alpha"])), "--output", self.out(), "--json"])
        self.assertEqual(code, 0, row)
        # Both VMs' scripts are delivered: the root decides, not the suffix.
        self.assertEqual(sorted(row["result"]["loose_scripts"]), ["scripts/zm/alpha.csc", "scripts/zm/alpha.gsc"])


class AdapterReach(AdapterFixture):
    """``adapters.py`` harvests an adapter stage's loose scripts by walking ``stage/scripts`` only.
    A staged ``maps/mp/...`` or ``clientscripts/mp/...`` script is therefore dropped on compose --
    no loose copy, no zone row, an empty ``loose_scripts`` on the receipt, and nothing said. The
    harvest is not widened, because the roots it would be widened to are the ones the engine does
    not register; the silent drop is refused instead."""

    def adapter_with_script(self, mid, target):
        d = self.adapter(mid)
        recipe = json.loads((d / "recipe.json").read_text())
        recipe["loose_script"] = {"source": f"src/{mid}.gsc", "target": target, "instance": "server"}
        (d / "recipe.json").write_text(json.dumps(recipe, indent=2))
        return d

    def test_an_adapter_script_outside_the_roots_is_refused_rather_than_dropped(self):
        self.adapter_with_script("civil", "maps/mp/halo/civil_events.gsc")
        comp = self.composition(["civil"], name="stock_adapter_test")
        code, row = invoke(["module", "plan", str(comp), "--output", self.out(), "--json"])
        self.assertEqual(code, 1, row)
        self.assertIn("script-reach:maps/mp/halo/civil_events.gsc", row["details"]["failed"])

    def test_an_adapter_script_under_the_root_plans_and_keeps_its_loose_delivery(self):
        self.adapter_with_script("civil", "scripts/zm/halo_civil.gsc")
        comp = self.composition(["civil"], name="stock_adapter_test")
        out = self.out()
        code, row = invoke(["module", "build", str(comp), "--output", out, "--json"])
        self.assertEqual(code, 0, row)
        self.assertIn("scripts/zm/halo_civil.gsc", row["result"]["loose_scripts"])
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        reach = [c for c in plan["checks"] if c["id"] == "script-reach:scripts/zm/halo_civil.gsc"]
        self.assertEqual([c["outcome"] for c in reach], ["passed"])


class AdaptPattern(CompositionFixture):
    def test_a_member_whose_every_script_is_unreachable_is_a_port_not_a_widening(self):
        from plutonium_agent_toolkit.dev import compositions as c
        comp = {"base": "b2", "map": "zm_factory"}
        modules = [{"id": "kill_feedback", "directory": "/m/kill_feedback", "dependencies": [],
                    "provides": {"scripts": ["maps/mp/halo/cr35_hud.gsc"]}}]
        unqualified = [{"id": "kill_feedback", "declared_bases": ["stock"], "declared_maps": ["zm_transit"]}]
        checks_rows = checks.script_reach("maps/mp/halo/cr35_hud.gsc")
        row = c.adapt_rows(comp, modules, unqualified, "dlc5-beta2", checks_rows)[0]
        self.assertEqual(row["pattern"], "script-unreachable")
        self.assertIn("maps/mp/halo/cr35_hud.gsc", row["detail"])

    def test_a_member_with_one_reachable_script_keeps_the_pattern_the_plan_can_see(self):
        from plutonium_agent_toolkit.dev import compositions as c
        comp = {"base": "b2", "map": "zm_factory"}
        modules = [{"id": "timeslip", "directory": "/m/timeslip", "dependencies": [],
                    "provides": {"scripts": ["scripts/zm/halo_timeslip.gsc", "maps/mp/halo/halo_timeslip_box.gsc"]}}]
        unqualified = [{"id": "timeslip", "declared_bases": ["stock"], "declared_maps": ["zm_transit"]}]
        rows = checks.script_reach("maps/mp/halo/halo_timeslip_box.gsc")
        self.assertEqual(c.adapt_rows(comp, modules, unqualified, "dlc5-beta2", rows)[0]["pattern"], "unknown")
