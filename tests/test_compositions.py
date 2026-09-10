"""``module plan|build``: composition of declared modules against the fake backends.

The formats are specified in docs/MODULES.md; these tests are the executable half of that page.
"""
import json
from pathlib import Path

from tests.test_dev_routes import DevRouteFixture, invoke

ROOT = Path(__file__).resolve().parents[1]


def declaration(mid, **overrides):
    row = {"schema": 1, "id": mid, "version": "0.1.0", "title": mid, "category": "scripts", "recipe": "project.json",
           "bases": ["stock"], "maps": ["*"], "dependencies": [], "conflicts": [],
           "resource_contract": {"threads": 1, "entities": 0, "hud": 0, "network_fields": 0}}
    row.update(overrides)
    return row


class CompositionFixture(DevRouteFixture):
    def module(self, mid, script_target=None, **overrides):
        """A module directory: project.json with one script, and a module.json declaration."""
        d = self.root / "modules" / mid
        (d / "scripts").mkdir(parents=True, exist_ok=True)
        (d / "scripts" / f"{mid}.gsc").write_text(f"main()\n{{\n    level thread {mid}();\n}}\n\n{mid}()\n{{\n    wait 1;\n}}\n")
        recipe = {"schema": 1, "game": "t6", "mode": "zm", "name": mid,
                  "scripts": [{"source": f"scripts/{mid}.gsc", "target": script_target or f"scripts/zm/{mid}.gsc", "instance": "server"}],
                  "assets": [], "loads": []}
        (d / "project.json").write_text(json.dumps(recipe, indent=2))
        (d / "module.json").write_text(json.dumps(declaration(mid, **overrides), indent=2))
        return d

    def composition(self, modules, name="stock_pack_test", base="stock", map_id="zm_transit", budget=None, **extra):
        d = self.root / "packs" / name
        d.mkdir(parents=True, exist_ok=True)
        row = {"schema": 1, "name": name, "base": base, "map": map_id,
               "modules": [Path("../../modules") / m for m in modules], "loads": []}
        row["modules"] = [p.as_posix() for p in row["modules"]]
        if budget is not None:
            row["budget"] = budget
        row.update(extra)
        path = d / "composition.json"
        path.write_text(json.dumps(row, indent=2))
        return path


class CompositionTests(CompositionFixture):
    def test_plan_and_build_two_modules_into_one_mod_ff(self):
        self.module("alpha")
        self.module("beta", dependencies=["alpha"])
        comp = self.composition(["beta", "alpha"])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertTrue(result["backends_available"])
        self.assertEqual([m["id"] for m in result["modules"]], ["alpha", "beta"], "dependency order, not listing order")
        self.assertEqual(result["resource_totals"], {"threads": 2, "entities": 0, "hud": 0, "network_fields": 0})
        self.assertEqual(result["scripts"], 2)
        plan = json.loads((Path(result["output"]) / "plan.json").read_text())
        self.assertEqual(plan["order"], ["alpha", "beta"])
        self.assertEqual(plan["base"], "stock")
        self.assertEqual(plan["map"], "zm_transit")
        for module in plan["modules"]:
            self.assertRegex(module["declaration_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(module["recipe_sha256"], r"^[0-9a-f]{64}$")
        receipt = json.loads((Path(result["output"]) / "receipt.json").read_text())
        self.assertEqual(receipt["status"], "succeeded")
        self.assertEqual(receipt["steps"], [], "plan runs no backend")
        declared = {Path(k).name for k in receipt["inputs"]}
        self.assertTrue({"composition.json", "module.json", "project.json", "alpha.gsc", "beta.gsc"} <= declared, declared)

        code, row = invoke(["module", "build", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertEqual(result["mod_ff"], "packages/mod.ff")
        self.assertEqual(result["rawfiles_verified"], 2)
        self.assertEqual(result["name"], "stock_pack_test")
        build = Path(result["output"])
        package = json.loads((build / "packages" / "mod.ff").read_text())
        self.assertEqual(package["zone"], "mod")
        self.assertEqual(sorted(package["rawfiles"]), ["scripts/zm/alpha.gsc", "scripts/zm/beta.gsc"])
        receipt = json.loads((build / "receipt.json").read_text())
        self.assertEqual(receipt["status"], "succeeded")
        self.assertIn("packages/mod.ff", receipt["outputs"])
        self.assertIn("install-mod", result["install_hint"])

        code, row = invoke(["project", "verify", str(build / "receipt.json"), "--inputs", "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertTrue(row["result"]["inputs"]["verified"])

    def test_bundled_example_composition_plans(self):
        code, row = invoke(["module", "plan", str(ROOT / "examples/hello-pack/composition.json"), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual([m["id"] for m in row["result"]["modules"]], ["hello_zm", "round_announcer"])
        self.assertEqual(row["result"]["budget"]["threads"], 4)

    def test_missing_dependency_conflict_and_cycle_are_refused_before_any_backend(self):
        self.module("alpha", dependencies=["gamma"])
        code, row = invoke(["module", "plan", str(self.composition(["alpha"])), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("gamma", row["message"])
        self.assertIn("Add the module directory", row["hint"])

        self.module("delta", conflicts=["alpha"])
        self.module("alpha")
        code, row = invoke(["module", "plan", str(self.composition(["alpha", "delta"], name="stock_conflict_test")), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("conflict", row["message"])

        self.module("one", dependencies=["two"])
        self.module("two", dependencies=["one"])
        code, row = invoke(["module", "plan", str(self.composition(["one", "two"], name="stock_cycle_test")), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertIn("cycle", row["message"])
        receipt = json.loads((Path(row["receipt"])).read_text())
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["steps"], [])

    def test_base_map_fit_and_target_collisions_are_refused(self):
        self.module("alpha", bases=["b2"])
        code, row = invoke(["module", "plan", str(self.composition(["alpha"])), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertIn("not for 'stock'", row["message"])

        self.module("alpha", maps=["zm_factory"])
        code, row = invoke(["module", "plan", str(self.composition(["alpha"])), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertIn("not for 'zm_transit'", row["message"])

        self.module("alpha")
        self.module("beta", script_target="scripts/zm/alpha.gsc")
        code, row = invoke(["module", "plan", str(self.composition(["alpha", "beta"])), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertIn("both produce scripts/zm/alpha.gsc", row["message"])

    def test_budget_and_naming_rules(self):
        self.module("alpha", resource_contract={"threads": 3, "entities": 0, "hud": 0, "network_fields": 0})
        self.module("beta", resource_contract={"threads": 2, "entities": 0, "hud": 0, "network_fields": 0})
        comp = self.composition(["alpha", "beta"], budget={"threads": 4, "entities": 0, "hud": 0, "network_fields": 0})
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_limit")
        self.assertIn("threads 5 > 4", row["message"])
        # Without a budget the totals are reported, not enforced.
        code, row = invoke(["module", "plan", str(self.composition(["alpha", "beta"])), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["resource_totals"]["threads"], 5)
        self.assertIsNone(row["result"]["budget"])
        # The composition name must follow <base>_<feature>_<stage> with the composition's base.
        for bad in ("hello_pack", "b2_hello_pack", "stock_hello_latest"):
            code, row = invoke(["module", "plan", str(self.composition(["alpha"], name=bad)), "--output", self.out()])
            self.assertEqual(code, 1, bad)
            self.assertIn("<base>_<feature>_<stage>", row["message"])

    def test_declaration_shape_is_validated(self):
        d = self.module("alpha")
        for broken in (declaration("Alpha"), declaration("alpha", schema=2), declaration("alpha", bases=[]),
                       declaration("alpha", maps=["Bad Map"]), declaration("alpha", dependencies=["alpha"]),
                       declaration("alpha", resource_contract={"threads": -1}), declaration("alpha", recipe="../escape.json"),
                       declaration("alpha", source={"repository": "http://insecure.example"}),
                       declaration("alpha", source={"repository": "https://example.invalid/r", "commit": "short"}),
                       {**declaration("alpha"), "unknown_field": 1}):
            (d / "module.json").write_text(json.dumps(broken))
            code, row = invoke(["module", "plan", str(self.composition(["alpha"])), "--output", self.out()])
            self.assertEqual(code, 1, broken)
            self.assertIn(row["error_code"], ("input_invalid", "input_missing"), broken)
        (d / "module.json").unlink()
        code, row = invoke(["module", "plan", str(self.composition(["alpha"])), "--output", self.out()])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "input_missing")
        self.assertIn("module.json", row["message"])

    def test_module_directories_must_be_relative_real_directories(self):
        self.module("alpha")
        comp = self.composition(["alpha"])
        data = json.loads(comp.read_text())
        data["modules"] = [str(self.root / "modules" / "alpha")]
        comp.write_text(json.dumps(data))
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "input_invalid")
        data["modules"] = ["../../modules/nowhere"]
        comp.write_text(json.dumps(data))
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "input_missing")
        data["modules"] = ["../../modules/alpha", "../../modules/alpha"]
        comp.write_text(json.dumps(data))
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 1)
        self.assertIn("twice", row["message"])

    def test_manifest_lists_the_routes_as_available_with_the_linux_receipt(self):
        # available only because docs/SUPPORT.md links a native Linux receipt for both steps.
        support = (ROOT / "docs/SUPPORT.md").read_text(encoding="utf-8")
        self.assertIn("`module build hello-pack (real gsc-tool + OAT)`", support)
        code, row = invoke(["manifest"])
        by_id = {r["id"]: r for r in row["result"]["routes"]}
        for rid in ("module.plan", "module.build"):
            self.assertEqual(by_id[rid]["status"], "available", rid)
            self.assertEqual(by_id[rid]["effect"], "writes-output")
