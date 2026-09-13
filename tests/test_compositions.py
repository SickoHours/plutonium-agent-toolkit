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
               "modules": [(Path("../../modules") / m).as_posix() if isinstance(m, str) else m for m in modules], "loads": []}
        if budget is not None:
            row["budget"] = budget
        row.update(extra)
        path = d / "composition.json"
        path.write_text(json.dumps(row, indent=2))
        return path


class CompositionTests(CompositionFixture):
    def test_invalid_payload_paths_fail_before_plan_and_build_resolve_them(self):
        directory = self.module("alpha")
        comp = self.composition(["alpha"])
        for payload, path in (("recipe", "D:payload.json"), ("seed", "../other/seed.json"),
                              ("seed", "D:seed.json")):
            data = declaration("alpha", distribution="private")
            data.pop("recipe")
            data[payload] = path
            (directory / "module.json").write_text(json.dumps(data))
            for action in ("plan", "build"):
                with self.subTest(payload=payload, path=path, action=action):
                    code, row = invoke(["module", action, str(comp), "--output", self.out()])
                    self.assertEqual(code, 1, row)
                    self.assertEqual(row["error_code"], "input_invalid", row)
                    self.assertEqual(row["details"]["field"], "/" + payload)
        data["seed"] = "nested/seed.json"
        (directory / "module.json").write_text(json.dumps(data))
        for action in ("plan", "build"):
            code, row = invoke(["module", action, str(comp), "--output", self.out()])
            self.assertEqual(code, 1, row)
            self.assertEqual(row["error_code"], "input_missing", row)

    def test_inspect_and_plan_accept_a_symlinked_parent_but_refuse_a_final_link(self):
        import hashlib

        directory = self.module("alpha")
        comp = self.composition(["alpha"])
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        for path in (comp, directory / "module.json"):
            through_alias = alias / path.relative_to(self.root)
            code, row = invoke(["module", "inspect", str(through_alias), "--json"])
            self.assertEqual(code, 0, row)
            self.assertEqual(row["result"]["file"], str(through_alias))
            self.assertEqual(row["result"]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        code, row = invoke(["module", "plan", str(alias / comp.relative_to(self.root)), "--output", self.out()])
        self.assertEqual(code, 0, row)
        final_link = self.root / "composition.json"
        final_link.symlink_to(comp)
        for action in ("inspect", "plan"):
            args = ["module", action, str(final_link), "--json"]
            if action == "plan":
                args += ["--output", self.out()]
            code, row = invoke(args)
            self.assertEqual(code, 1, row)
            self.assertEqual(row["error_code"], "input_missing")
            if action == "inspect":
                self.assertIsNone(row["details"]["inspection"]["sha256"])

    def test_plan_and_build_restore_member_directory_context_for_metadata_errors(self):
        for field, value in (("schema", 2), ("game", "unknown"), ("id", "BAD")):
            with self.subTest(field=field):
                directory = self.module("alpha")
                path = directory / "module.json"
                data = json.loads(path.read_text())
                data[field] = value
                path.write_text(json.dumps(data))
                comp = self.composition(["alpha"])
                for action in ("plan", "build"):
                    code, row = invoke(["module", action, str(comp), "--output", self.out()])
                    self.assertEqual(code, 1, row)
                    self.assertTrue(row["message"].startswith("module.json in alpha: "), row)
                    self.assertEqual(row["details"]["field"], "/" + field)
                code, row = invoke(["module", "inspect", str(path)])
                self.assertEqual(code, 1, row)
                self.assertTrue(row["message"].startswith("module.json: "), row)

    def test_plan_uses_the_same_metadata_validation_as_inspect_before_payload_resolution(self):
        from plutonium_agent_toolkit.dev import compositions
        from unittest.mock import patch

        directory = self.module("alpha", dependencies=["BAD"])
        (directory / "project.json").unlink()
        comp = self.composition(["alpha"])
        with patch.object(compositions, "validate_declaration_metadata",
                          wraps=compositions.validate_declaration_metadata) as validate:
            code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 1, row)
        validate.assert_called_once()
        self.assertEqual(row["details"]["field"], "/dependencies/0")
        inspect_code, inspection = invoke(["module", "inspect", str(directory / "module.json"), "--json"])
        self.assertEqual(inspect_code, code)
        self.assertEqual(inspection["message"], row["message"])
        self.assertEqual(inspection["details"]["inspection"]["diagnostics"][0]["field"], row["details"]["field"])
        broken = self.composition([{"path": "../../missing", "role": "invalid"}])
        with patch.object(compositions, "validate_composition_metadata",
                          wraps=compositions.validate_composition_metadata) as validate:
            code, row = invoke(["module", "plan", str(broken), "--output", self.out()])
        self.assertEqual(code, 1, row)
        validate.assert_called_once()
        self.assertEqual(row["details"]["field"], "/modules/0/role")

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

        # A file collision is a decision, not a refusal: plan lists it, build refuses until it is recorded.
        self.module("alpha")
        self.module("beta", script_target="scripts/zm/alpha.gsc")
        code, row = invoke(["module", "plan", str(self.composition(["alpha", "beta"])), "--output", self.out()])
        self.assertEqual(code, 0, row)
        undecided = row["result"]["undecided"]
        self.assertEqual([(u["collision"], u["modules"]) for u in undecided], [("scripts/zm/alpha.gsc", ["alpha", "beta"])])
        self.assertEqual(row["result"]["decisions"], [])
        code, row = invoke(["module", "build", str(self.composition(["alpha", "beta"])), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("no recorded decision", row["message"])
        self.assertEqual(row["details"]["undecided"][0]["collision"], "scripts/zm/alpha.gsc")
        receipt = json.loads(Path(row["receipt"]).read_text())
        self.assertEqual(receipt["steps"], [], "refused before any backend ran")

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


class DecisionTests(CompositionFixture):
    def test_recorded_decision_stages_the_owner_and_identical_bytes_dedupe(self):
        self.module("alpha")
        self.module("beta", script_target="scripts/zm/alpha.gsc")
        comp = self.composition(["alpha", "beta"], decisions=[{"collision": "scripts/zm/alpha.gsc", "owner": "beta", "reason": "beta's copy is newer"}])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["undecided"], [])
        self.assertEqual(row["result"]["decisions"][0]["owner"], "beta")
        self.assertEqual(row["result"]["decisions"][0]["resolution"], "recorded decision")
        code, row = invoke(["module", "build", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        build = Path(row["result"]["output"])
        package = json.loads((build / "packages" / "mod.ff").read_text())
        self.assertEqual(sorted(package["rawfiles"]), ["scripts/zm/alpha.gsc"], "one copy of the collided target")
        self.assertEqual(row["result"]["rawfiles_verified"], 1)
        # The owner's bytes won: the fake compiler emits COMPILED:<sha256 of the source>, and the
        # packed rawfile carries beta's source hash, not alpha's.
        import base64
        import hashlib
        packed = base64.b64decode(package["rawfiles"]["scripts/zm/alpha.gsc"]).decode()
        beta_source = (self.root / "modules" / "beta" / "scripts" / "beta.gsc").read_text()
        self.assertEqual(packed, "COMPILED:" + hashlib.sha256(beta_source.encode()).hexdigest())
        # A decision naming a module outside the collision is refused.
        comp = self.composition(["alpha", "beta"], name="stock_bad_test", decisions=[{"collision": "scripts/zm/alpha.gsc", "owner": "alpha"}])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)  # alpha is a party to the collision
        comp = self.composition(["alpha", "beta"], name="stock_bad2_test", decisions=[{"collision": "scripts/zm/alpha.gsc", "owner": "gamma"}])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertIn("gamma", row["message"])
        # Identical bytes under the same target: no decision needed.
        d_alpha = self.root / "modules" / "alpha"
        d_beta = self.root / "modules" / "beta"
        (d_beta / "scripts" / "beta.gsc").write_bytes((d_alpha / "scripts" / "alpha.gsc").read_bytes())
        code, row = invoke(["module", "plan", str(self.composition(["alpha", "beta"], name="stock_same_test")), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["undecided"], [])
        self.assertEqual(row["result"]["decisions"][0]["resolution"], "identical bytes; one copy is packed")

    def test_provides_name_collisions_are_decisions(self):
        self.module("gun_a", provides={"weapons": ["ray_gun_zm"]})
        self.module("gun_b", provides={"weapons": ["ray_gun_zm"]})
        code, row = invoke(["module", "plan", str(self.composition(["gun_a", "gun_b"])), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["undecided"][0]["collision"], "weapons:ray_gun_zm")
        self.assertEqual(row["result"]["undecided"][0]["kind"], "name")
        comp = self.composition(["gun_a", "gun_b"], decisions=[{"collision": "weapons:ray_gun_zm", "owner": "gun_a", "reason": "a is the tested one"}])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["undecided"], [])


class TaxonomyTests(CompositionFixture):
    def test_category_kind_tags_and_distribution_are_validated_and_carried_into_the_plan(self):
        self.module("alpha", category="weapons", kind="melee", tags=["saints-row", "bat"])
        code, row = invoke(["module", "plan", str(self.composition(["alpha"])), "--output", self.out()])
        self.assertEqual(code, 0, row)
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        self.assertEqual(plan["modules"][0]["kind"], "melee")
        self.assertEqual(plan["modules"][0]["tags"], ["saints-row", "bat"])
        self.assertEqual(plan["modules"][0]["distribution"], "source")
        self.assertEqual(plan["modules"][0]["payload"], "recipe")
        for broken in (declaration("alpha", category="weapons", kind="perk"), declaration("alpha", tags=["Bad Tag"]),
                       declaration("alpha", distribution="unknown"), declaration("alpha", provides={"nope": ["x"]}),
                       declaration("alpha", provides={"weapons": ["a", "a"]}), {**declaration("alpha"), "seed": "seed.json"}):
            (self.root / "modules" / "alpha" / "module.json").write_text(json.dumps(broken))
            code, row = invoke(["module", "plan", str(self.composition(["alpha"])), "--output", self.out()])
            self.assertEqual(code, 1, broken)
            self.assertEqual(row["error_code"], "input_invalid", broken)

    def test_private_recipe_plans_locally_but_missing_payloads_still_fail(self):
        directory = self.module("alpha", distribution="private")
        composition = self.composition(["alpha"])
        code, row = invoke(["module", "plan", str(composition), "--output", self.out()])
        self.assertEqual(code, 0, row)
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        self.assertEqual(plan["modules"][0]["distribution"], "private")
        self.assertEqual(plan["modules"][0]["payload"], "recipe")
        (directory / "scripts" / "alpha.gsc").unlink()
        code, row = invoke(["module", "plan", str(composition), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_missing")
        (directory / "project.json").unlink()
        for action in ("plan", "build"):
            code, row = invoke(["module", action, str(composition), "--output", self.out()])
            self.assertEqual(code, 1, row)
            self.assertEqual(row["error_code"], "input_missing")
            self.assertIn("recipe is missing", row["message"])

    def test_composition_title_and_tags(self):
        self.module("alpha")
        comp = self.composition(["alpha"], title="Saints Row weapons", tags=["saints-row"])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["title"], "Saints Row weapons")
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        self.assertEqual(plan["tags"], ["saints-row"])

    def test_origin_and_donor_are_validated_and_carried_into_the_plan(self):
        # Origin is the game the identity comes from and drives the title; donor is who the bytes came
        # from and drives the credit line. Both are optional, neither affects resolution.
        self.module("alpha", title="ICR-1 (Black Ops III)", origin="bo3",
                    donor="Chronicles Reawakened v3.5 (Kosmoes) T5 conversion; T6 conversion by the pack's own converter")
        self.module("beta", origin="unverified")
        self.module("gamma")
        comp = self.composition(["alpha", "beta", "gamma"], origin="bo3", donor="two conversions and one original script")
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        rows = {m["id"]: m for m in plan["modules"]}
        self.assertEqual(rows["alpha"]["origin"], "bo3")
        self.assertTrue(rows["alpha"]["donor"].startswith("Chronicles Reawakened"))
        self.assertEqual(rows["beta"]["origin"], "unverified")
        self.assertIsNone(rows["beta"]["donor"])
        self.assertIsNone(rows["gamma"]["origin"], "absent stays absent; the planner never fills an origin in")
        self.assertEqual(plan["origin"], "bo3")
        self.assertEqual(plan["donor"], "two conversions and one original script")
        for broken in (declaration("alpha", origin="Black Ops III"), declaration("alpha", origin=["bo3"]), declaration("alpha", origin=""),
                       declaration("alpha", donor="x" * 401), declaration("alpha", donor="two\nlines"), declaration("alpha", donor=7),
                       declaration("alpha", donor="   ")):
            (self.root / "modules" / "alpha" / "module.json").write_text(json.dumps(broken))
            code, row = invoke(["module", "plan", str(self.composition(["alpha"])), "--output", self.out()])
            self.assertEqual(code, 1, broken)
            self.assertEqual(row["error_code"], "input_invalid", broken)
        self.module("alpha")
        for broken in ({"origin": "Bad Origin"}, {"donor": ""}, {"donor": ["a"]}):
            comp = self.composition(["alpha"], **broken)
            code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
            self.assertEqual(code, 1, broken)
            self.assertEqual(row["error_code"], "input_invalid", broken)


class SeedFixture(CompositionFixture):
    def seed_module(self, mid, weapons=("halo_penetrator_zm",), banks=("halo_penetrator.all.sabl",), roots=None, **overrides):
        """A seed module: a fake mod.ff (JSON the fakes understand), banks, a manifest and a declaration."""
        import base64
        d = self.root / "modules" / mid
        d.mkdir(parents=True, exist_ok=True)
        assets = [f"weapon,{w}" for w in weapons] + [f"soundbank,{b.removesuffix('.sabl').removesuffix('.sabs')}" for b in banks] \
            + [f"xanim,{mid}_idle", f"xmodel,{mid}_view", "image,*shared_specular"]
        referenced = ["techniqueset,mc_lit_sm_r0c0n0s0_zqq1fze7", "image,$identitynormalmap"]
        rawfiles = {f"scripts/zm/{mid}_seeded.gsc": base64.b64encode(b"SEEDED " + mid.encode()).decode()}
        assets.append(f"localize,{mid.upper()}")
        (d / "mod.ff").write_text(json.dumps({"zone": "mod", "rawfiles": rawfiles, "assets": assets, "referenced": referenced,
                                            "strings": {mid.upper(): f"The {mid}"}}))
        for b in banks:
            (d / b).write_bytes(b"BANK " + b.encode())
        code, row = invoke(["module", "declare", str(d / "mod.ff"), "--id", mid, "--base", "stock", "--map", "zm_transit", "--output", self.out()])
        self.assertEqual(code, 0, row)
        out = Path(row["result"]["output"])
        (d / "seed.json").write_bytes((out / "seed.json").read_bytes())
        if (out / "mod.str").is_file():
            (d / "mod.str").write_bytes((out / "mod.str").read_bytes())
        decl = json.loads((out / "module.json").read_text())
        decl.update(overrides)
        if roots is not None:
            manifest = json.loads((d / "seed.json").read_text()); manifest["roots"] = roots
            (d / "seed.json").write_text(json.dumps(manifest))
        (d / "module.json").write_text(json.dumps(decl, indent=2))
        return d, row["result"]


class SeedTests(SeedFixture):
    def test_declare_reads_the_package_and_drafts_a_declaration(self):
        d, result = self.seed_module("penetrator")
        self.assertEqual(result["provides"]["weapons"], ["halo_penetrator_zm"])
        self.assertEqual(result["soundbanks"], ["halo_penetrator.all.sabl"])
        self.assertEqual(result["referenced"], 2)
        manifest = json.loads((d / "seed.json").read_text())
        self.assertEqual(manifest["package"], "mod.ff")
        self.assertEqual(set(manifest["files"]), {"mod.ff", "halo_penetrator.all.sabl"})
        self.assertEqual(manifest["roots"][0], "weapon,halo_penetrator_zm", "weapons lead the roots")
        self.assertIn("rawfile,scripts/zm/penetrator_seeded.gsc", manifest["embedded"])
        self.assertEqual(manifest["strings"], "mod.str")
        self.assertEqual(manifest["provides"]["localize"], ["PENETRATOR"])
        self.assertIn("REFERENCE PENETRATOR", (d / "mod.str").read_text())
        self.assertNotIn("localize,PENETRATOR", manifest["roots"], "strings are merged into the pack's own file, never rooted")
        self.assertNotIn("image,*shared_specular", manifest["roots"], "images are never roots")
        decl = json.loads((d / "module.json").read_text())
        self.assertEqual(decl["seed"], "seed.json")
        self.assertEqual(decl["distribution"], "seed")
        self.assertEqual(decl["category"], "weapons")
        self.assertEqual(decl["bases"], ["stock"])
        # declare refuses anything not named mod.ff
        other = self.root / "other.ff"
        other.write_text("{}")
        code, row = invoke(["module", "declare", str(other), "--output", self.out()])
        self.assertEqual(row["error_code"], "input_invalid")

    def test_a_declaration_may_copy_its_manifest_provides_block_including_rawfiles(self):
        # docs/MODULES.md: a seed's manifest fills provides in and a declaration may narrow it by
        # copying the block. The manifest lists the rawfiles the package embeds under `rawfiles`, so
        # the copied block must be accepted as written (found declaring ten pack-sized hub seeds).
        d, _ = self.seed_module("penetrator")
        manifest = json.loads((d / "seed.json").read_text())
        self.assertEqual(manifest["provides"]["rawfiles"], ["scripts/zm/penetrator_seeded.gsc"])
        decl = json.loads((d / "module.json").read_text())
        decl["provides"] = manifest["provides"]
        (d / "module.json").write_text(json.dumps(decl))
        code, row = invoke(["module", "plan", str(self.composition(["penetrator"], zone_header=[">level.ipak_read,common_zm"])), "--output", self.out()])
        self.assertEqual(code, 0, row)
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        planned = plan["modules"][0]
        self.assertEqual(planned["provides"]["rawfiles"], ["scripts/zm/penetrator_seeded.gsc"])
        self.assertEqual(planned["provides"]["weapons"], ["halo_penetrator_zm"])
        # A seed declaration cannot claim a rawfile, weapon or model its manifest does not list, and an
        # empty manifest list is no licence: the manifest is the fact for the kinds it derives.
        for claim in ({"rawfiles": ["scripts/zm/not_in_package.gsc"]}, {"weapons": ["invented_zm"]},
                      {"rawfiles": ["scripts/zm/penetrator_seeded.gsc", "scripts/zm/extra.gsc"]}):
            decl["provides"] = claim
            (d / "module.json").write_text(json.dumps(decl))
            code, row = invoke(["module", "plan", str(self.composition(["penetrator"], zone_header=[">level.ipak_read,common_zm"])), "--output", self.out()])
            self.assertEqual(row["error_code"], "input_invalid", claim)
            self.assertIn("does not list", row["message"])
        # Kinds the listing cannot see stay the declaration's (a perk seed names its perk).
        decl["provides"] = {"perks": ["specialty_penetration"]}
        (d / "module.json").write_text(json.dumps(decl))
        code, row = invoke(["module", "plan", str(self.composition(["penetrator"], zone_header=[">level.ipak_read,common_zm"])), "--output", self.out()])
        self.assertEqual(code, 0, row)
        # Two seeds embedding the same rawfile are one file collision, never also a rawfiles name collision.
        decl["provides"] = manifest["provides"]
        (d / "module.json").write_text(json.dumps(decl))
        self.seed_module("pen_twin", weapons=("twin_zm",), banks=("twin.all.sabl",))
        twin = self.root / "modules" / "pen_twin"
        package = json.loads((twin / "mod.ff").read_text())
        package["rawfiles"]["scripts/zm/penetrator_seeded.gsc"] = package["rawfiles"].pop("scripts/zm/pen_twin_seeded.gsc")
        (twin / "mod.ff").write_text(json.dumps(package))
        code, row = invoke(["module", "declare", str(twin / "mod.ff"), "--id", "pen_twin", "--base", "stock", "--map", "zm_transit", "--output", self.out()])
        self.assertEqual(code, 0, row)
        (twin / "seed.json").write_bytes((Path(row["result"]["output"]) / "seed.json").read_bytes())
        code, row = invoke(["module", "plan", str(self.composition(["penetrator", "pen_twin"], name="stock_twins_test", zone_header=[">level.ipak_read,common_zm"])), "--output", self.out()])
        self.assertEqual(code, 0, row)
        shared = [u for u in row["result"]["undecided"] if "penetrator_seeded.gsc" in u["collision"]]
        self.assertEqual([(u["kind"], u["collision"]) for u in shared], [("file", "scripts/zm/penetrator_seeded.gsc")])
        self.assertFalse(any(u["collision"].startswith("rawfiles:") for u in row["result"]["undecided"]))
        # A whole pack declared as one seed embeds several hundred models; the per-kind limit has
        # room for that, and still has a ceiling.
        self.module("big", provides={"models": [f"model_{n}" for n in range(600)]})
        code, row = invoke(["module", "plan", str(self.composition(["big"], name="stock_big_test")), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.module("huge", provides={"models": [f"model_{n}" for n in range(4097)]})
        code, row = invoke(["module", "plan", str(self.composition(["huge"], name="stock_huge_test")), "--output", self.out()])
        self.assertEqual(row["error_code"], "input_invalid")

    def test_seed_module_composes_with_a_recipe_module_and_the_roots_are_verified(self):
        self.seed_module("penetrator")
        self.module("announcer")
        comp = self.composition(["penetrator", "announcer"], name="stock_pen_pack", zone_header=[">level.ipak_read,common_zm"])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual([(m["id"], m["payload"]) for m in row["result"]["modules"]], [("announcer", "recipe"), ("penetrator", "seed")])
        self.assertEqual(row["result"]["seeds"], 1)
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        self.assertEqual(plan["seeds"][0]["id"], "penetrator")
        self.assertIn("weapon,halo_penetrator_zm", plan["seeds"][0]["roots"])
        self.assertRegex(plan["modules"][1]["seed_sha256"], r"^[0-9a-f]{64}$")
        code, row = invoke(["module", "build", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertEqual(result["seed_roots_verified"], len(plan["seeds"][0]["roots"]))
        self.assertEqual(result["soundbanks"], ["halo_penetrator.all.sabl"])
        build = Path(result["output"])
        package = json.loads((build / "packages" / "mod.ff").read_text())
        self.assertIn("weapon,halo_penetrator_zm", package["assets"], "the linker copied the root out of the seed")
        self.assertIn("localize,PENETRATOR", package["assets"], "the seed's strings were merged into the pack's localize,mod")
        self.assertEqual(result["localized_strings"], 1)
        zone = (build / "project" / "zone_source" / "mod.zone").read_text().splitlines()
        self.assertEqual(zone[:4], ["> game,T6", "> name,mod", ">level.ipak_read,common_zm", "localize,mod"], zone[:5])
        self.assertIn("scripts/zm/announcer.gsc", package["rawfiles"])
        self.assertTrue((build / "packages" / "halo_penetrator.all.sabl").is_file(), "bank staged beside the package")
        receipt = json.loads((build / "receipt.json").read_text())
        self.assertTrue(any(a.endswith("mod.ff") and "-l" in step["argv"] for step in receipt["steps"] for a in step["argv"]), "seed loaded with -l")

    def test_seed_hash_drift_and_missing_package_are_refused(self):
        d, _ = self.seed_module("penetrator")
        (d / "mod.ff").write_text(json.dumps({"zone": "mod", "rawfiles": {}, "assets": ["weapon,halo_penetrator_zm"]}))
        code, row = invoke(["module", "plan", str(self.composition(["penetrator"])), "--output", self.out()])
        self.assertEqual(row["error_code"], "input_changed")
        (d / "mod.ff").unlink()
        code, row = invoke(["module", "plan", str(self.composition(["penetrator"])), "--output", self.out()])
        self.assertEqual(row["error_code"], "input_missing")
        # distribution private: the declaration is valid without the package, and plan says so honestly.
        decl = json.loads((d / "module.json").read_text()); decl["distribution"] = "private"
        (d / "module.json").write_text(json.dumps(decl))
        (d / "seed.json").unlink()
        code, row = invoke(["module", "plan", str(self.composition(["penetrator"])), "--output", self.out()])
        self.assertEqual(row["error_code"], "input_missing")
        self.assertIn("private", row["message"])

    def test_two_seeds_shipping_the_same_bank_or_weapon_are_decisions_or_refusals(self):
        self.seed_module("pen_a", banks=("shared.all.sabl",))
        self.seed_module("pen_b", banks=("shared.all.sabl",), weapons=("other_zm",))
        comp = self.composition(["pen_a", "pen_b"], name="stock_two_test")
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertTrue(any(u["collision"] == "asset:soundbank,shared.all" for u in row["result"]["undecided"]))


class StageTests(SeedFixture):
    def test_probe_stage_is_accepted_and_others_refused(self):
        self.module("alpha")
        code, row = invoke(["module", "plan", str(self.composition(["alpha"], name="stock_alpha_probe")), "--output", self.out()])
        self.assertEqual(code, 0, row)
        code, row = invoke(["module", "plan", str(self.composition(["alpha"], name="stock_alpha_release")), "--output", self.out()])
        self.assertEqual(code, 1, row)


class BaseOwnedTests(SeedFixture):
    def test_base_listing_resolves_names_the_base_carries_and_leaves_the_rest(self):
        # Two seeds each carry a private copy of *shared_specular (the fake seed writes it) and
        # both name their own weapon. A listing of the base zones that carries the image makes
        # that collision base-owned; the weapon and soundbank collisions stay decisions.
        self.seed_module("pen_a", banks=("shared.all.sabl",))
        self.seed_module("pen_b", banks=("shared.all.sabl",))
        listing = self.root / "packs" / "base" / "common_zm-list.txt"
        listing.parent.mkdir(parents=True, exist_ok=True)
        listing.write_text("Loaded zone \"common_zm\" (T6)\nimage, *shared_specular\ntechniqueset, ,mc_lit_sm_r0c0n0s0_zqq1fze7\nimage, ,*ref_only\n")
        comp = self.composition(["pen_a", "pen_b"], name="stock_owned_test", base_owned=["../base/common_zm-list.txt"])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        owned = [d for d in row["result"]["decisions"] if d["resolution"].startswith("base-owned")]
        self.assertEqual([d["collision"] for d in owned], ["asset:image,*shared_specular"])
        self.assertEqual(owned[0]["owner"], "pen_a")
        self.assertEqual(row["result"]["base_owned_names"], 1, "reference rows are not base-owned")
        undecided = {u["collision"] for u in row["result"]["undecided"]}
        self.assertIn("asset:soundbank,shared.all", undecided)
        self.assertIn("weapons:halo_penetrator_zm", undecided)
        # A provides registration is never base-owned, even when the base carries the name.
        listing.write_text("weapon, halo_penetrator_zm\nimage, *shared_specular\n")
        comp = self.composition(["pen_a", "pen_b"], name="stock_owned5_test", base_owned=["../base/common_zm-list.txt"])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertIn("weapons:halo_penetrator_zm", {u["collision"] for u in row["result"]["undecided"]})
        listing.write_text("Loaded zone \"common_zm\" (T6)\nimage, *shared_specular\ntechniqueset, ,mc_lit_sm_r0c0n0s0_zqq1fze7\nimage, ,*ref_only\n")
        self.assertNotIn("asset:image,*shared_specular", undecided)
        # A recorded decision for a base-owned name still wins, verbatim.
        comp = self.composition(["pen_a", "pen_b"], name="stock_owned2_test", base_owned=["../base/common_zm-list.txt"],
                                decisions=[{"collision": "asset:image,*shared_specular", "owner": "pen_b", "reason": "keep b"}])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual([d["owner"] for d in row["result"]["decisions"] if d["collision"] == "asset:image,*shared_specular"], ["pen_b"])
        built = self.composition(["pen_a"], name="stock_owned_build_test", base_owned=["../base/common_zm-list.txt"])
        code, row = invoke(["module", "build", str(built), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["base_owned_names"], 1, "build reports the count too")
        # Listings are relative files like loads; an absolute path or a missing file is refused.
        comp = self.composition(["pen_a", "pen_b"], name="stock_owned3_test", base_owned=[str(listing)])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 1); self.assertIn("relative", row["message"])
        comp = self.composition(["pen_a", "pen_b"], name="stock_owned4_test", base_owned=["../base/missing.txt"])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(row["error_code"], "input_missing")

    def test_forty_seeds_plan_within_the_load_cap(self):
        for i in range(40):
            self.seed_module(f"gun{i:02d}", weapons=(f"gun{i:02d}_zm",), banks=(f"gun{i:02d}.all.sabl",))
        code, row = invoke(["module", "plan", str(self.composition([f"gun{i:02d}" for i in range(40)], name="stock_forty_test")), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["seeds"], 40)

    def test_member_and_decision_caps(self):
        from plutonium_agent_toolkit.dev import compositions, builtin
        self.assertEqual(compositions.MAX_MODULES, 128)
        self.assertEqual(builtin.MAX_MEMBERS, 128, "built-in packs share the member cap")
        self.assertEqual(compositions.MAX_DECISIONS, 1024)
        self.module("alpha")
        comp = self.composition(["alpha"], name="stock_caps_test", decisions=[{"collision": f"scripts/zm/x{i}.gsc", "owner": "alpha"} for i in range(1025)])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 1); self.assertIn("1024", row["message"])


class NestingAndReferenceTests(SeedFixture):
    def test_a_composition_can_be_a_member_and_a_base(self):
        self.module("qol_a")
        self.module("qol_b")
        inner = self.composition(["qol_a", "qol_b"], name="stock_qol_pack")
        self.module("penetrator_script")
        d = self.root / "packs" / "stock_qol_plus_test"
        d.mkdir(parents=True)
        outer = {"schema": 1, "name": "stock_qol_plus_test", "base": "stock", "map": "zm_transit",
                 "modules": [{"path": "../stock_qol_pack", "role": "base"}, "../../modules/penetrator_script"]}
        (d / "composition.json").write_text(json.dumps(outer))
        code, row = invoke(["module", "plan", str(d / "composition.json"), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual([m["id"] for m in row["result"]["modules"]], ["qol_a", "qol_b", "penetrator_script"], "base members first")
        self.assertEqual([m["role"] for m in row["result"]["modules"]], ["base", "base", "module"])
        self.assertEqual(row["result"]["base_member"], "qol_a")
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        self.assertEqual(plan["modules"][0]["via"], "stock_qol_pack")
        code, row = invoke(["module", "build", str(d / "composition.json"), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["rawfiles_verified"], 3)
        # two bases refused; a nested pack for another map refused; a cycle refused
        outer["modules"] = [{"path": "../stock_qol_pack", "role": "base"}, {"path": "../../modules/penetrator_script", "role": "base"}]
        (d / "composition.json").write_text(json.dumps(outer))
        code, row = invoke(["module", "plan", str(d / "composition.json"), "--output", self.out()])
        self.assertEqual(code, 1); self.assertIn("at most one member with role base", row["message"])
        other_map = self.composition(["qol_a"], name="stock_other_pack", map_id="zm_buried")
        outer["modules"] = [{"path": "../stock_other_pack", "role": "base"}]
        (d / "composition.json").write_text(json.dumps(outer))
        code, row = invoke(["module", "plan", str(d / "composition.json"), "--output", self.out()])
        self.assertEqual(code, 1); self.assertIn("zm_buried", row["message"])
        loop = {"schema": 1, "name": "stock_loop_pack", "base": "stock", "map": "zm_transit", "modules": ["../stock_qol_plus_test"]}
        (self.root / "packs" / "stock_loop_pack").mkdir()
        (self.root / "packs" / "stock_loop_pack" / "composition.json").write_text(json.dumps(loop))
        outer["modules"] = ["../stock_loop_pack"]
        (d / "composition.json").write_text(json.dumps(outer))
        code, row = invoke(["module", "plan", str(d / "composition.json"), "--output", self.out()])
        self.assertEqual(code, 1); self.assertIn("cycle", row["message"])

    def test_a_reference_member_pins_a_commit_and_needs_a_fetched_path(self):
        self.module("announcer")
        comp = self.composition(["announcer"])
        data = json.loads(comp.read_text())
        commit = "a" * 40
        data["modules"] = [{"name": "someone/announcer", "commit": commit, "path": "../../modules/announcer"}]
        comp.write_text(json.dumps(data))
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        self.assertEqual(plan["modules"][0]["reference"], {"name": "someone/announcer", "commit": commit})
        for bad in ({"name": "someone/announcer", "path": "../../modules/announcer"},
                    {"name": "someone/announcer", "commit": commit},
                    {"name": "Bad Name", "commit": commit, "path": "../../modules/announcer"},
                    {"path": "../../modules/announcer", "commit": commit}):
            data["modules"] = [bad]
            comp.write_text(json.dumps(data))
            code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
            self.assertEqual(code, 1, bad)
            self.assertIn(row["error_code"], ("input_invalid", "input_missing"), bad)
