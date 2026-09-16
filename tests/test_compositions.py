"""``module plan|build``: composition of declared modules against the fake backends.

The formats are specified in docs/MODULES.md; these tests are the executable half of that page.
"""
import json
from pathlib import Path

from plutonium_agent_toolkit.dev.compositions import staged_scripts
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

    def module_with_assets(self, mid, rows, script=None):
        d = self.module(mid)
        recipe = json.loads((d / "project.json").read_text())
        for row in rows:
            (d / row["source"]).parent.mkdir(parents=True, exist_ok=True)
            (d / row["source"]).write_bytes(b"BYTES " + row["source"].encode())
        recipe["assets"] = rows
        if script is not None:
            (d / "scripts" / f"{mid}.gsc").write_text(script)
        (d / "project.json").write_text(json.dumps(recipe, indent=2))
        return d


class StagedScripts(CompositionFixture):
    """What the pack's own bytes are. A pack-level check reads the rows the build stages and no
    others: the loser of a file collision never reaches the package, and the generated entry does."""

    def rows(self, compiled, decided=(), modules=()):
        return staged_scripts(compiled, list(decided), list(modules))

    def test_a_decided_collision_keeps_only_the_owners_copy(self):
        alpha = (Path("/m/alpha/scripts/half.csc"), Path("scripts/zm/half.csc"), "client")
        beta = (Path("/m/beta/scripts/half.csc"), Path("scripts/zm/half.csc"), "client")
        modules = [{"id": "alpha", "directory": "/m/alpha"}, {"id": "beta", "directory": "/m/beta"}]
        decided = [{"kind": "file", "collision": "scripts/zm/half.csc", "owner": "beta"}]
        self.assertEqual(self.rows([alpha, beta], decided, modules), [(*beta, "beta")])
        decided = [{"kind": "file", "collision": "scripts/zm/half.csc", "owner": "alpha"}]
        self.assertEqual(self.rows([alpha, beta], decided, modules), [(*alpha, "alpha")])

    def test_without_a_decision_the_first_row_wins_once(self):
        alpha = (Path("/m/alpha/scripts/x.gsc"), Path("scripts/zm/x.gsc"), "server")
        beta = (Path("/m/beta/scripts/x.gsc"), Path("scripts/zm/X.GSC"), "server")
        modules = [{"id": "alpha", "directory": "/m/alpha"}, {"id": "beta", "directory": "/m/beta"}]
        self.assertEqual(self.rows([alpha, beta], (), modules), [(*alpha, "alpha")],
                         "one target is staged once, case-insensitively")

    def test_the_generated_entry_is_a_staged_row_owned_by_no_member(self):
        """Its source is the job directory, not a module's: it is the pack's own script and it is
        staged like any other compiled row, so a check reads it with no module to name."""
        member = (Path("/m/alpha/scripts/alpha.gsc"), Path("scripts/zm/alpha.gsc"), "server")
        entry = (Path("/job/generated-entry/zz_stock_pack_test_entry.gsc"),
                 Path("scripts/zm/zz_stock_pack_test_entry.gsc"), "server")
        modules = [{"id": "alpha", "directory": "/m/alpha"}]
        self.assertEqual(self.rows([member, entry], (), modules), [(*member, "alpha"), (*entry, None)])

    def test_a_pack_with_a_generated_entry_still_reads_its_clientfields(self):
        """End to end: the generated entry is compiled, staged and read with the members."""
        m = self.module("alpha", entry={"replace": "scripts/zm/alpha::alpha_replace",
                                        "register": "scripts/zm/alpha::alpha_register"}, registration="entry")
        (m / "scripts/alpha.gsc").write_text(
            'alpha_replace() {}\nalpha_register()\n{\n    registerclientfield("toplayer", "halo_cr35_meter", 1, 2, "int");\n}\n')
        code, result = invoke(["module", "plan", str(self.composition(["alpha"])), "--output", self.out()])
        self.assertFalse(result["ok"], result)
        self.assertIn("clientfield-symmetry:halo_cr35_meter", result["details"]["failed"])
        entry_target = "scripts/zm/zz_stock_pack_test_entry.gsc"
        self.assertIn("externals:" + entry_target, [s["id"] for s in result["details"]["checks"]],
                      "the generated entry is one of the compiled scripts the checks read")
        plan = json.loads((Path(result["receipt"]).parent / "plan.json").read_text())
        self.assertIn(entry_target, [s["target"] for s in plan["scripts"]],
                      "and it is a script row in the plan like any member's")
        row = next(c for c in result["details"]["checks"] if c["id"] == "clientfield-symmetry:halo_cr35_meter")
        self.assertIn("module alpha", row["detail"])


class CompositionTests(CompositionFixture):
    def test_lineage_is_metadata_only_and_preserves_multiple_source_maps(self):
        from plutonium_agent_toolkit.dev.compositions import validate_declaration_metadata
        one = {"game": "t5", "map": "zm_factory", "source": "Example source", "note": "Same-map call path; not T6 verification."}
        rows = [one, dict(one, map="zm_prototype")]
        self.assertEqual(validate_declaration_metadata(declaration("alpha", lineage=rows))["lineage"], rows)
        self.assertEqual(validate_declaration_metadata(declaration("alpha", lineage=one))["lineage"], [one])
        for value in ([], dict(one, game="t6"), dict(one, map="other"), dict(one, source=""), dict(one, note="x"*401)):
            with self.assertRaises(Exception):
                validate_declaration_metadata(declaration("alpha", lineage=value))


    def test_unqualified_target_is_opt_in_and_retained_in_build_receipt(self):
        self.module("alpha", maps=["zm_transit"])
        comp = self.composition(["alpha"], name="b2_example_pack", base="b2", map_id="zm_factory")
        code, denied = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 1, denied)
        expected = [{"id": "alpha", "declared_bases": ["stock"], "declared_maps": ["zm_transit"], "base": "b2", "map": "zm_factory"}]
        for action in ("plan", "build"):
            code, result = invoke(["module", action, str(comp), "--allow-unqualified", "--output", self.out()])
            self.assertEqual(code, 0, result)
            self.assertEqual(result["result"]["unqualified"], expected)
            receipt = json.loads(Path(result["result"]["receipt"]).read_text())
            self.assertEqual(receipt["result"]["unqualified"], expected)


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


class PerTargetRecipeDeclarationTests(CompositionFixture):
    """`recipes` is the adapter payload's per-target cut map; the declaration checks that need no
    filesystem, and the two payloads that cannot carry one."""

    def test_keys_are_a_foundation_and_a_map_and_values_stay_inside_the_module(self):
        from plutonium_agent_toolkit.dev.compositions import validate_declaration_metadata
        good = {"dlc5-beta2/zm_factory": "recipe-b2.json", "bo2-stock/zm_transit": "cuts/recipe.json"}
        self.assertEqual(validate_declaration_metadata(declaration("alpha", recipes=good))["recipes"], good)
        self.assertEqual(validate_declaration_metadata(declaration("alpha"))["recipes"], {})
        # A base token is not refused lexically (`b2` is a possible foundation id); a key that
        # disagrees with its own recipe's foundation is refused when the payload is resolved.
        for bad in ({"dlc5-beta2": "r.json"}, {"dlc5-beta2/factory": "r.json"},
                    {"DLC5/zm_factory": "r.json"}, {"dlc5-beta2/zm_factory": "../r.json"},
                    {"dlc5-beta2/zm_factory": "/r.json"}, {"dlc5-beta2/zm_factory": "cuts\\r.json"},
                    {"dlc5-beta2/zm_factory": 1}, ["dlc5-beta2/zm_factory"]):
            with self.subTest(recipes=bad), self.assertRaises(Exception):
                validate_declaration_metadata(declaration("alpha", recipes=bad))

    def test_a_seed_payload_cannot_name_per_target_recipes(self):
        from plutonium_agent_toolkit.dev.compositions import validate_declaration_metadata
        row = declaration("alpha", recipes={"dlc5-beta2/zm_factory": "recipe-b2.json"})
        row.pop("recipe"); row["seed"] = "seed.json"
        with self.assertRaises(Exception) as caught:
            validate_declaration_metadata(row)
        self.assertIn("a seed is one package", caught.exception.message)

    def test_a_project_recipe_module_is_refused_a_recipes_entry(self):
        directory = self.module("alpha", recipes={"dlc5-beta2/zm_factory": "recipe-b2.json"})
        (directory / "recipe-b2.json").write_text(json.dumps(
            {"schema": 1, "module": "alpha", "foundation": "dlc5-beta2", "map": "zm_factory"}))
        comp = self.composition(["alpha"], name="b2_pack_test", base="b2", map_id="zm_factory")
        for action in ("plan", "build"):
            code, row = invoke(["module", action, str(comp), "--allow-unqualified", "--output", self.out()])
            self.assertEqual(code, 1, row)
            self.assertEqual(row["error_code"], "input_invalid", row)
            self.assertIn("project.json is a project recipe the toolkit compiles itself", row["message"])
            self.assertEqual(row["details"]["field"], "/recipes")

    def test_inspect_reports_the_targets_and_never_the_paths(self):
        directory = self.module("alpha", recipes={"dlc5-beta2/zm_factory": "recipe-b2.json"})
        code, row = invoke(["module", "inspect", str(directory / "module.json")])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["metadata"]["recipes"], ["dlc5-beta2/zm_factory"])
        code, row = invoke(["module", "inspect", str(self.module("beta") / "module.json")])
        self.assertEqual(code, 0, row)
        self.assertNotIn("recipes", row["result"]["metadata"], "a declaration without the field reports none")


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
        self.module("gun_a", provides={"weapons": ["halo_ray_zm"]})
        self.module("gun_b", provides={"weapons": ["halo_ray_zm"]})
        code, row = invoke(["module", "plan", str(self.composition(["gun_a", "gun_b"])), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["undecided"][0]["collision"], "weapons:halo_ray_zm")
        self.assertEqual(row["result"]["undecided"][0]["kind"], "name")
        comp = self.composition(["gun_a", "gun_b"], decisions=[{"collision": "weapons:halo_ray_zm", "owner": "gun_a", "reason": "a is the tested one"}])
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
        # A provides registration is never base-owned: a WeaponDef the base already carries is
        # the native-WeaponDef rule (an imported definition overriding the map's own crashes
        # precache), refused as a service row for each member that registers it.
        listing.write_text("weapon, halo_penetrator_zm\nimage, *shared_specular\n")
        comp = self.composition(["pen_a", "pen_b"], name="stock_owned5_test", base_owned=["../base/common_zm-list.txt"])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertEqual([(r["kind"], r["what"], r["modules"]) for r in row["details"]["refusals"]],
                         [("service", "native WeaponDef", ["pen_a"]), ("service", "native WeaponDef", ["pen_b"])])
        self.assertNotIn("weapons:halo_penetrator_zm", {u["collision"] for u in row["details"]["undecided"]})
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
            self.seed_module(f"gun{i:02d}", weapons=(f"gun{i:02d}_zm",), banks=())
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


class PoolAndDeliveryTests(CompositionFixture):
    """The 2026-09-14 pack failures, reproduced offline: rawfile pool, image-bank slots, withheld authoring inputs, map scripts."""
    def module_with_assets(self, mid, rows, script=None):
        d = self.module(mid)
        recipe = json.loads((d / "project.json").read_text())
        for row in rows:
            (d / row["source"]).parent.mkdir(parents=True, exist_ok=True)
            (d / row["source"]).write_bytes(b"BYTES " + row["source"].encode())
        recipe["assets"] = rows
        if script is not None:
            (d / "scripts" / f"{mid}.gsc").write_text(script)
        (d / "project.json").write_text(json.dumps(recipe, indent=2))
        return d

    def test_plan_reports_footprint_and_refuses_a_rawfile_pool_overflow_naming_the_contributor(self):
        rows = [{"source": f"model_export/m{i}.glb", "target": f"model_export/m{i}.glb", "type": "rawfile"} for i in range(600)]
        self.module_with_assets("wavegun", rows)
        self.module("hud")
        comp = self.composition(["wavegun", "hud"], name="stock_pool_test")
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("pool:rawfile-assets", row["message"])
        self.assertIn("wavegun (601)", row["message"])
        pool = next(c for c in row["details"]["checks"] if c["id"] == "pool:rawfile-assets")
        self.assertEqual(pool["outcome"], "failed")
        self.assertEqual(pool["base"], 531, "TranZit's own rawfiles from shipped occupancy")
        self.assertEqual(pool["contribution"], 602)
        self.assertEqual(pool["contributors"][0], {"id": "wavegun", "count": 601})

    def test_a_member_guarded_on_another_map_refuses_naming_the_script(self):
        # The script compiles, links and loads; its main() just returns, so the pack ships a
        # member that does nothing. Only reading the guard finds that before the game does.
        guarded = 'main()\n{\n    if ( getdvar( "mapname" ) != "zm_nuked" )\n        return;\n    level thread bus();\n}\n\nbus()\n{\n    wait 1;\n}\n'
        self.module_with_assets("bus", [], script=guarded)
        comp = self.composition(["bus"], name="stock_guard_test")
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertIn("map-guard:scripts/zm/bus.gsc", row["message"])
        check = next(c for c in row["details"]["checks"] if c["id"] == "map-guard:scripts/zm/bus.gsc")
        self.assertEqual(check["outcome"], "failed")
        self.assertEqual(check["detail"], "returns unless mapname is zm_nuked; this composition targets zm_transit, so the script does nothing on it")

    def test_a_member_guarded_on_the_target_map_passes_and_an_unguarded_one_is_not_counted(self):
        self.module_with_assets("bus", [], script='main()\n{\n    if ( getdvar( "mapname" ) != "zm_transit" )\n        return;\n    level thread bus();\n}\n\nbus()\n{\n    wait 1;\n}\n')
        self.module("hud")
        code, row = invoke(["module", "plan", str(self.composition(["bus", "hud"], name="stock_guard_test")), "--output", self.out()])
        self.assertEqual(code, 0, row)
        by_id = {c["id"]: c for c in row["result"]["checks"]}
        self.assertEqual(by_id["map-guard:scripts/zm/bus.gsc"]["outcome"], "passed")
        self.assertEqual(by_id["map-guard:scripts/zm/hud.gsc"]["outcome"], "not_counted")

    def test_deliver_false_withholds_authoring_inputs_from_the_zone_and_the_pool(self):
        rows = [{"source": f"model_export/m{i}.glb", "target": f"model_export/m{i}.glb", "type": "rawfile", "deliver": False} for i in range(600)]
        rows.append({"source": "accuracy/x.accu", "target": "accuracy/x.accu", "type": "rawfile"})
        self.module_with_assets("wavegun", rows)
        comp = self.composition(["wavegun"], name="stock_deliver_test")
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["withheld"], 600)
        self.assertEqual(row["result"]["footprint"]["wavegun"], {"rawfiles": 2, "soundbanks": [], "scripts": 1})
        pool = next(c for c in row["result"]["checks"] if c["id"] == "pool:rawfile-assets")
        self.assertEqual(pool["outcome"], "passed");self.assertEqual(pool["count"], 533)
        receipt = json.loads((Path(row["result"]["output"]) / "receipt.json").read_text())
        self.assertTrue(any(k.replace("\\", "/").endswith("model_export/m0.glb") for k in receipt["inputs"]), "withheld files are still hashed inputs")
        code, row = invoke(["module", "build", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        package = json.loads((Path(row["result"]["output"]) / "packages" / "mod.ff").read_text())
        self.assertEqual(sorted(package["rawfiles"]), ["accuracy/x.accu", "scripts/zm/wavegun.gsc"])
        self.assertEqual(row["result"]["rawfiles_verified"], 2)

    def test_identical_bytes_pick_a_delivered_owner_over_a_withheld_one(self):
        """A withheld row stages the file but emits no zone entry: when a delivered member has the
        same bytes at the same target, the dedupe must name the delivered one or the rawfile is lost."""
        row = {"source": "accuracy/x.accu", "target": "accuracy/x.accu", "type": "rawfile"}
        self.module_with_assets("withholder", [dict(row, deliver=False)])
        self.module_with_assets("deliverer", [dict(row)])
        comp = self.composition(["withholder", "deliverer"], name="stock_withheld_owner_test")
        code, result = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, result)
        decided = next(d for d in result["result"]["decisions"] if d["collision"] == "accuracy/x.accu")
        self.assertEqual(decided["resolution"], "identical bytes; one copy is packed")
        self.assertEqual(decided["modules"], ["withholder", "deliverer"], "the withheld member is listed first")
        self.assertEqual(decided["owner"], "deliverer", "a delivered owner keeps the zone entry")
        code, result = invoke(["module", "build", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, result)
        package = json.loads((Path(result["result"]["output"]) / "packages" / "mod.ff").read_text())
        self.assertIn("accuracy/x.accu", package["rawfiles"], "the delivered copy is still in the zone")

    def _clientfield_module(self, mid, server, client=None):
        """A module whose server script registers a clientfield, optionally with the client half."""
        d = self.module(mid)
        (d / "scripts" / f"{mid}.gsc").write_text(server)
        if client is not None:
            (d / "scripts" / f"{mid}.csc").write_text(client)
            recipe = json.loads((d / "project.json").read_text())
            recipe["scripts"].append({"source": f"scripts/{mid}.csc", "target": f"scripts/zm/{mid}.csc", "instance": "client"})
            (d / "project.json").write_text(json.dumps(recipe, indent=2))
        return d

    REGISTER = ('main()\n{\n}\n\ninit()\n{\n'
                '    registerclientfield("toplayer", "halo_cr35_meter", 1, 2, "int");\n}\n')

    def test_a_server_clientfield_with_no_client_half_refuses_the_plan(self):
        """Two packs shipped this shape on 2026-09-16; the engine refused the map at load."""
        self._clientfield_module("meter", self.REGISTER)
        code, result = invoke(["module", "plan", str(self.composition(["meter"])), "--output", self.out()])
        self.assertFalse(result["ok"])
        self.assertIn("Offline checks failed", result["message"])
        self.assertIn("clientfield-symmetry:halo_cr35_meter", result["details"]["failed"])
        row = next(c for c in result["details"]["checks"] if c["id"] == "clientfield-symmetry:halo_cr35_meter")
        self.assertEqual(row["outcome"], "failed")
        self.assertIn("halo_cr35_meter", row["detail"]);self.assertIn("scripts/zm/meter.gsc", row["detail"])
        self.assertIn("module meter", row["detail"])
        self.assertIn("ship the other half as a loose scripts/zm script", row["detail"])

    def test_both_halves_in_the_pack_pass_the_symmetry_check(self):
        self._clientfield_module("meter", self.REGISTER, self.REGISTER)
        code, result = invoke(["module", "plan", str(self.composition(["meter"])), "--output", self.out()])
        self.assertEqual(code, 0, result)
        rows = [c for c in result["result"]["checks"] if c["id"].startswith("clientfield-symmetry")]
        self.assertEqual([(c["id"], c["outcome"]) for c in rows], [("clientfield-symmetry:halo_cr35_meter", "passed")])

    def test_a_pack_that_registers_no_clientfield_carries_one_not_counted_row(self):
        self.module("alpha")
        code, result = invoke(["module", "plan", str(self.composition(["alpha"])), "--output", self.out()])
        self.assertEqual(code, 0, result)
        rows = [c for c in result["result"]["checks"] if c["id"].startswith("clientfield-symmetry")]
        self.assertEqual([(c["id"], c["outcome"]) for c in rows], [("clientfield-symmetry", "not_counted")])

    def _csc_member(self, mid, body, target="scripts/zm/half.csc"):
        """A module staging a `.csc` at a shared target, so two of them collide on one file."""
        d = self.module(mid)
        (d / "scripts" / f"{mid}.csc").write_text(body)
        recipe = json.loads((d / "project.json").read_text())
        recipe["scripts"].append({"source": f"scripts/{mid}.csc", "target": target, "instance": "client"})
        (d / "project.json").write_text(json.dumps(recipe, indent=2))
        return d

    SILENT_CSC = "main()\n{\n}\n\ninit()\n{\n    level.nothing = 1;\n}\n"

    def _collision_pack(self, owner, name):
        self._clientfield_module("meter", self.REGISTER)
        self._csc_member("winner", self.SILENT_CSC)
        self._csc_member("loser", self.REGISTER)
        comp = self.composition(["meter", "winner", "loser"], name=name,
                                decisions=[{"collision": "scripts/zm/half.csc", "owner": owner, "reason": "the tested copy"}])
        return invoke(["module", "plan", str(comp), "--output", self.out()])

    def test_a_discarded_collision_loser_cannot_answer_for_the_client_half(self):
        """Only `winner`'s silent copy is staged, so the client half is not in the package."""
        code, result = self._collision_pack("winner", "stock_cf_loser_test")
        self.assertFalse(result["ok"], result)
        self.assertIn("clientfield-symmetry:halo_cr35_meter", result["details"]["failed"])
        row = next(c for c in result["details"]["checks"] if c["id"] == "clientfield-symmetry:halo_cr35_meter")
        self.assertEqual(row["outcome"], "failed")
        self.assertIn("by no .csc in this pack", row["detail"])
        self.assertNotIn("loser", row["detail"], "the discarded copy is not evidence of anything")

    def test_the_collision_winner_is_the_copy_that_answers(self):
        code, result = self._collision_pack("loser", "stock_cf_winner_test")
        self.assertEqual(code, 0, result)
        rows = [c for c in result["result"]["checks"] if c["id"].startswith("clientfield-symmetry")]
        self.assertEqual([(c["id"], c["outcome"]) for c in rows], [("clientfield-symmetry:halo_cr35_meter", "passed")])
        self.assertIn("module loser", rows[0]["detail"], "the staging owner names the row, not the last claimant")

    def test_an_iw5_pack_has_no_two_vm_clientfield_property_to_judge(self):
        d = self.module("iw5_thing", game="iw5")
        (d / "scripts" / "iw5_thing.gsc").write_text(self.REGISTER)
        recipe = json.loads((d / "project.json").read_text()); recipe["game"] = "iw5"; recipe["mode"] = "mp"
        (d / "project.json").write_text(json.dumps(recipe))
        comp = self.composition(["iw5_thing"], name="stock_iw5field_test", base="stock", map_id="mp_alpha", game="iw5")
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        checks = (row.get("result") or row.get("details") or {}).get("checks") or []
        rows = [c for c in checks if c["id"].startswith("clientfield-symmetry")]
        self.assertEqual([(c["id"], c["outcome"]) for c in rows], [("clientfield-symmetry", "not_counted")], row)
        self.assertIn("clientfield registrations are a T6 two-VM property", rows[0]["detail"])
        self.assertNotIn("clientfield-symmetry", (row.get("details") or {}).get("failed") or [])

    def _client_module(self, mid, box_list, provides_weapons):
        d = self.module(mid, provides={"weapons": provides_weapons})
        (d / "scripts" / f"{mid}.csc").write_text(
            'init()\n{\n    foreach (weapon in strtok("' + box_list + '", " "))\n        addzombieboxweapon(weapon, getweaponmodel(weapon), 0);\n}\n')
        recipe = json.loads((d / "project.json").read_text())
        recipe["scripts"].append({"source": f"scripts/{mid}.csc", "target": f"scripts/zm/{mid}.csc", "instance": "client"})
        (d / "project.json").write_text(json.dumps(recipe, indent=2))
        return d

    def test_a_client_box_registration_for_a_weapon_nobody_provides_is_refused(self):
        """wavegun_client.csc registered the VR-11's humangun_zm; the engine faulted at the first box use."""
        self._client_module("wave", "humangun_zm humangun_upgraded_zm", ["microwavegundw_zm"])
        code, result = invoke(["module", "plan", str(self.composition(["wave"])), "--allow-unqualified", "--output", self.out()])
        self.assertFalse(result["ok"])
        self.assertIn("Offline checks failed", result["message"])
        self.assertIn("box-registration:scripts/zm/wave.csc", result["details"]["failed"])
        self.assertIn("humangun_zm", result["message"])
        self.assertIn("box-weapon-not-found", result["message"])

    def _server_module(self, mid, body):
        d = self.module(mid)
        (d / "scripts" / f"{mid}.gsc").write_text(body)
        return d

    def test_a_bare_stock_call_no_include_covers_refuses_the_plan(self):
        """blast_furnace shipped with a bare `register_zombie_damage_callback` and no #include; the
        plan accepted it with 0 failed rows and the load died at `Unresolved external`."""
        self._server_module("furnace", "main()\n{\n    register_zombie_damage_callback(::ammo_damage);\n}\nammo_damage()\n{\n}\n")
        code, result = invoke(["module", "plan", str(self.composition(["furnace"])), "--allow-unqualified", "--output", self.out()])
        self.assertFalse(result["ok"])
        self.assertIn("Offline checks failed", result["message"])
        self.assertIn("externals:scripts/zm/furnace.gsc", result["details"]["failed"])
        self.assertIn("maps/mp/zombies/_zm_spawner", result["message"])
        row = next(c for c in result["details"]["checks"] if c["id"] == "externals:scripts/zm/furnace.gsc")
        self.assertEqual(row["outcome"], "failed")

    def test_an_argument_count_no_included_owner_takes_refuses_the_plan(self):
        """qol_max_ammo's shape: the include is present, the arity is not."""
        self._server_module("maxammo", "#include maps\\mp\\_utility;\nmain()\n{\n    players = get_players( self.team );\n}\n")
        code, result = invoke(["module", "plan", str(self.composition(["maxammo"])), "--allow-unqualified", "--output", self.out()])
        self.assertFalse(result["ok"])
        self.assertIn("externals:scripts/zm/maxammo.gsc", result["details"]["failed"])
        self.assertIn("get_players called with 1 argument", result["message"])

    def test_an_unknown_bare_name_carries_its_own_row_and_does_not_refuse(self):
        """The unknown listing is not_counted, so it never refuses, but it is its own row."""
        self._server_module("probe", "main()\n{\n    totally_unknown_thing();\n}\n")
        code, result = invoke(["module", "plan", str(self.composition(["probe"])), "--allow-unqualified", "--output", self.out()])
        self.assertEqual(code, 0, result)
        rows = {c["id"]: c for c in result["result"]["checks"]}
        self.assertEqual(rows["externals:scripts/zm/probe.gsc"]["outcome"], "passed")
        unknown = rows["externals-unknown:scripts/zm/probe.gsc"]
        self.assertEqual(unknown["outcome"], "not_counted")
        self.assertIn("totally_unknown_thing", unknown["detail"])

    def test_a_client_box_registration_for_a_provided_weapon_passes(self):
        self._client_module("wave", "microwavegundw_zm", ["microwavegundw_zm", "microwavegundw_upgraded_zm"])
        code, result = invoke(["module", "plan", str(self.composition(["wave"])), "--allow-unqualified", "--output", self.out()])
        rows = [c for c in result["result"]["checks"] if c["id"].startswith("box-registration:")]
        self.assertEqual([c["outcome"] for c in rows], ["passed"])

    def test_a_client_box_registration_may_name_a_weapon_another_member_provides(self):
        self._client_module("wave", "thundergun_zm", [])
        self.module("thunder", provides={"weapons": ["thundergun_zm"]})
        code, result = invoke(["module", "plan", str(self.composition(["wave", "thunder"])), "--allow-unqualified", "--output", self.out()])
        rows = [c for c in result["result"]["checks"] if c["id"].startswith("box-registration:")]
        self.assertEqual([c["outcome"] for c in rows], ["passed"])

    def _client_root_module(self, mid, body):
        d = self.module(mid)
        (d / "scripts" / f"{mid}.csc").write_text(body)
        recipe = json.loads((d / "project.json").read_text())
        recipe["scripts"].append({"source": f"scripts/{mid}.csc", "target": f"scripts/zm/{mid}.csc", "instance": "client"})
        (d / "project.json").write_text(json.dumps(recipe, indent=2))
        return d

    def test_a_client_script_that_works_in_main_is_refused_with_the_row(self):
        """lc25: qol_wallguns_in_box.csc registered from main(), the early client pass, and the
        client-script pass died with zero `CSC Executed` lines."""
        self._client_root_module("wallguns", "main()\n{\n    wallguns_register();\n}\n\nwallguns_register()\n{\n}\n")
        code, result = invoke(["module", "plan", str(self.composition(["wallguns"])), "--allow-unqualified", "--output", self.out()])
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.assertIn("Offline checks failed", result["message"])
        self.assertIn("csc-main-body:scripts/zm/wallguns.csc", result["details"]["failed"])
        row = next(c for c in result["details"]["checks"] if c["id"] == "csc-main-body:scripts/zm/wallguns.csc")
        self.assertEqual(row["outcome"], "failed")
        self.assertIn("init()", row["detail"])

    def test_a_client_script_with_an_empty_main_plans(self):
        self._client_root_module("tesla", "main()\n{\n}\n\ninit()\n{\n    level.tesla = 1;\n}\n")
        code, result = invoke(["module", "plan", str(self.composition(["tesla"])), "--allow-unqualified", "--output", self.out()])
        self.assertEqual(code, 0, result)
        rows = {c["id"]: c["outcome"] for c in result["result"]["checks"] if c["id"].startswith("csc-main-body:")}
        self.assertEqual(rows["csc-main-body:scripts/zm/tesla.csc"], "passed")
        self.assertEqual(rows["csc-main-body:scripts/zm/tesla.gsc"], "not_counted", "the module's server half is not judged")

    def test_a_server_main_may_do_work_and_is_not_counted(self):
        """Every module() fixture's server half threads from main(); that is the shape the server VM
        supports, and the row must say so rather than refuse it."""
        self.module("probe")
        code, result = invoke(["module", "plan", str(self.composition(["probe"])), "--allow-unqualified", "--output", self.out()])
        self.assertEqual(code, 0, result)
        row = next(c for c in result["result"]["checks"] if c["id"] == "csc-main-body:scripts/zm/probe.gsc")
        self.assertEqual(row["outcome"], "not_counted")

    def test_deliver_false_is_rawfile_only_and_boolean(self):
        d = self.module_with_assets("alpha", [{"source": "x.json", "target": "xmodel/x.json", "type": "xmodel", "name": "x", "deliver": False}])
        code, row = invoke(["module", "plan", str(self.composition(["alpha"])), "--output", self.out()])
        self.assertEqual(code, 1);self.assertIn("rawfile rows only", row["message"])
        recipe = json.loads((d / "project.json").read_text());recipe["assets"] = [{"source": "x.json", "target": "x.json", "type": "rawfile", "deliver": "no"}]
        (d / "project.json").write_text(json.dumps(recipe))
        code, row = invoke(["module", "plan", str(self.composition(["alpha"])), "--output", self.out()])
        self.assertEqual(code, 1);self.assertIn("true or false", row["message"])

    def test_image_bank_reads_in_the_zone_header_are_counted_against_slots(self):
        self.module("alpha")
        header = [f">level.ipak_read,{n}" for n in ("base", "zm_factory", "zm_temple", "dlc0", "dlc2", "dlc3")]
        comp = self.composition(["alpha"], name="stock_ipak_test", zone_header=header)
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertIn("pool:image-bank-slots", row["message"])
        pool = next(c for c in row["details"]["checks"] if c["id"] == "pool:image-bank-slots")
        self.assertEqual(pool["count"], 17);self.assertEqual([c["id"] for c in pool["contributors"]], ["zm_factory", "zm_temple", "dlc0", "dlc2", "dlc3"])
        comp = self.composition(["alpha"], name="stock_ipak_test", zone_header=header[:4])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)

    def test_b2_compositions_count_against_der_riese_occupancy(self):
        self.module("alpha", bases=["b2"], maps=["zm_factory"])
        code, row = invoke(["module", "plan", str(self.composition(["alpha"], name="b2_alpha_test", base="b2", map_id="zm_factory")), "--output", self.out()])
        self.assertEqual(code, 0, row)
        pool = next(c for c in row["result"]["checks"] if c["id"] == "pool:rawfile-assets")
        self.assertEqual(pool["outcome"], "passed");self.assertEqual(pool["base"], 481)

    def test_a_script_including_a_stock_script_the_target_map_lacks_is_refused(self):
        src = "#include maps\\mp\\zombies\\_zm_perk_divetonuke;\nmain()\n{\n    maps\\mp\\zombies\\_zm_perk_divetonuke::enable_divetonuke_perk_for_level();\n}\n"
        self.module_with_assets("phd", [], script=src)
        (self.root / "modules" / "phd" / "module.json").write_text(json.dumps(declaration("phd", bases=["b2"], maps=["zm_factory"])))
        code, row = invoke(["module", "plan", str(self.composition(["phd"], name="b2_phd_test", base="b2", map_id="zm_factory")), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertIn("map-scripts:scripts/zm/phd.gsc", row["message"]);self.assertIn("_zm_perk_divetonuke", row["message"])
        code, row = invoke(["module", "plan", str(self.composition(["phd"], name="b2_phd_test", base="b2", map_id="zm_cosmodrome")), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertIn("declared for maps", row["message"], "Ascension carries the script, but the module is not declared for that map")

    def test_an_image_a_member_ships_passes_and_the_plan_says_the_rest_is_undecided(self):
        """A pack's images are the one pool the plan cannot read alone: the client's banks are not here."""
        row = {"source": "assets/images/halo_tex.iwi", "target": "images/halo_tex.iwi", "type": "image", "name": "halo_tex"}
        self.module_with_assets("skull", [row])
        code, result = invoke(["module", "plan", str(self.composition(["skull"], name="stock_image_test")), "--output", self.out()])
        self.assertEqual(code, 0, result)
        rows = {c["id"]: c for c in result["result"]["checks"] if c["id"].startswith("image-sources")}
        self.assertEqual(rows["image-sources:halo_tex"]["outcome"], "not_counted")
        self.assertIn("storage/t6/images", rows["image-sources:halo_tex"]["detail"])
        self.assertEqual(rows["image-sources"]["outcome"], "not_counted")
        report = self.root / "shipped-check.json"
        report.write_text(json.dumps({"pack": "stock_image_test", "images": [{"name": "halo_tex", "pixels": "present"}]}))
        code, result = invoke(["module", "plan", str(self.composition(["skull"], name="stock_image_test")), "--output", self.out(),
                               "--image-report", str(report)])
        self.assertEqual(code, 0, result)
        receipt = json.loads((Path(result["result"]["output"]) / "receipt.json").read_text())
        self.assertIn(str(report.resolve()), receipt["inputs"], "the readback the plan was decided against is a hashed input")

    def test_a_generated_image_name_is_shipped_and_a_path_separator_is_still_refused(self):
        """T6 names a derived texture `~$black-rgb&~-rt5_weapon_mesh~5d8c5c3e`; a module that ships it must name it exactly."""
        name = "~$black-rgb&~-rt5_weapon_mesh~5d8c5c3e"
        self.module_with_assets("thundergun", [{"source": f"assets/images/{name}.iwi", "target": f"images/{name}.iwi",
                                                "type": "image", "name": name}])
        code, result = invoke(["module", "plan", str(self.composition(["thundergun"], name="stock_generated_image_test")), "--output", self.out()])
        self.assertEqual(code, 0, result)
        self.assertEqual(next(c for c in result["result"]["checks"] if c["id"] == f"image-sources:{name}")["outcome"], "not_counted")
        from plutonium_agent_toolkit.dev.projects import _zone_target
        for bad in ("images/../escape.iwi", "/images/x.iwi", "images/a:b.iwi"):
            with self.assertRaises(Exception):
                _zone_target(bad)

    def test_a_pack_s_images_travel_beside_the_package(self):
        """The fastfile carries an image's header, never its pixels. packages/images/ is the artifact
        that carries them; the engine reads a bank or storage/t6/images, never the mod folder."""
        row = {"source": "assets/images/halo_tex.iwi", "target": "images/halo_tex.iwi", "type": "image", "name": "halo_tex"}
        self.module_with_assets("skull", [row])
        code, result = invoke(["module", "build", str(self.composition(["skull"], name="stock_image_delivery_test")), "--output", self.out()])
        self.assertEqual(code, 0, result)
        self.assertEqual(result["result"]["images_beside_package"], ["halo_tex.iwi"])
        packages = Path(result["result"]["output"]) / "packages"
        self.assertEqual((packages / "images" / "halo_tex.iwi").read_bytes(), b"BYTES assets/images/halo_tex.iwi")

    def test_a_readback_naming_an_image_with_no_pixels_refuses_the_pack(self):
        self.module("thundergun")
        report = self.root / "image-check.json"
        report.write_text(json.dumps({"pack": "stock_image_gap_test", "images_dumped": 252,
                                      "rows": [{"image": "t5_weapon_thundergun_n", "located": "the module's prepared images/"}]}))
        comp = self.composition(["thundergun"], name="stock_image_gap_test")
        code, row = invoke(["module", "plan", str(comp), "--output", self.out(), "--image-report", str(report)])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("image-sources:t5_weapon_thundergun_n", row["message"])
        self.assertIn("renders without them", row["message"])
        self.assertIn("located: the module's prepared images/", row["message"])
        failed = next(c for c in row["details"]["checks"] if c["id"] == "image-sources:t5_weapon_thundergun_n")
        self.assertEqual(failed["outcome"], "failed")
        self.assertIn("No member declares", failed["detail"])

    def test_the_same_pack_without_the_readback_is_undecided_rather_than_accepted(self):
        self.module("thundergun")
        comp = self.composition(["thundergun"], name="stock_image_unmeasured_test")
        code, result = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, result)
        summary = next(c for c in result["result"]["checks"] if c["id"] == "image-sources")
        self.assertEqual(summary["outcome"], "not_counted")
        self.assertIn("readback beside the banks", summary["detail"])


class DonorShadowingTests(CompositionFixture):
    """A donor zone loaded beside the base must never answer a name the base already carries.

    A T6 fastfile carries an image's header and never its pixels, so a donor's copy of a stock name
    puts a foreign header in front of the base's pixels and the shared camo textures render wrong on
    every weapon, the pack's and the map's alike. The composer excludes every base-owned image and
    material name from the zone; these tests are the executable half of that section in
    docs/MODULES.md.
    """

    def zone(self, name, assets=(), pulls=()):
        """A loadable fastfile for the fakes. ``pulls`` are the names this zone drags in on its own,
        which is how a material closure reaches a base-owned image without anyone rooting it."""
        d = self.root / "packs" / "zones"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{name}.ff"
        path.write_text(json.dumps({"zone": name, "rawfiles": {}, "assets": list(assets), "pulls": list(pulls)}))
        return path

    def listings(self, **zones):
        d = self.root / "packs" / "listings"
        d.mkdir(parents=True, exist_ok=True)
        for zone_name, rows in zones.items():
            (d / f"{zone_name}-list.txt").write_text("".join(f"{row}\n" for row in rows))
        return d

    def pack(self, name, **extra):
        self.module("skull")
        return self.composition(["skull"], name=name, loads=["../zones/common_zm.ff", "../zones/moon.ff"], **extra)

    def setUp(self):
        super().setUp()
        self.zone("common_zm")
        # The donor carries the base's camo image and a material of its own; only the first shadows.
        self.zone("moon", pulls=["image,camo_gold_nml", "material,mtl_moon_only"])
        self.listings(common_zm=["image, camo_gold_nml", "material, mtl_stock", "image, ,ref_only"])

    def test_a_base_owned_name_is_excluded_and_the_donor_copy_never_reaches_the_package(self):
        comp = self.pack("stock_shadow_test", base_owned=["../listings/common_zm-list.txt"])
        code, row = invoke(["module", "build", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        # A reference row (type, ,name) is not a base copy, so it is never excluded.
        self.assertEqual(row["result"]["base_owned_excluded"], {"image": 1, "material": 1})
        self.assertEqual(row["result"]["donor_shadowing"]["outcome"], "passed")
        self.assertEqual(row["result"]["donor_shadowing"]["count"], 0)
        package = json.loads((Path(row["result"]["output"]) / row["result"]["mod_ff"]).read_text())
        self.assertNotIn("image,camo_gold_nml", package["assets"])
        self.assertIn("image,camo_gold_nml", package["referenced"])
        self.assertIn("material,mtl_moon_only", package["assets"], "a donor name the base does not carry is still the pack's to root")
        zone_text = (Path(row["result"]["output"]) / "project" / "zone_source" / "mod.zone").read_text()
        self.assertIn("ignore,mod_base_owned", zone_text)
        rows = (Path(row["result"]["output"]) / "project" / "zone_source" / "assetlist" / "mod_base_owned.csv").read_text().splitlines()
        self.assertEqual(sorted(rows), ["image,camo_gold_nml", "material,mtl_stock"])

    def test_without_a_base_listing_the_plan_refuses_and_names_how_many_zones_are_loaded(self):
        code, row = invoke(["module", "plan", str(self.pack("stock_shadow2_test")), "--output", self.out()])
        self.assertEqual(code, 1, row)
        check = next(c for c in row["details"]["checks"] if c["id"] == "donor-shadowing")
        self.assertEqual(check["outcome"], "failed")
        self.assertEqual(check["count"], 2, "with no listing at all, no load can be shown to be part of the base")
        self.assertEqual(sorted(check["names"]), ["common_zm", "moon"])
        self.assertIn("no base listing", check["detail"])

    def test_base_listings_are_derived_from_the_loads_so_a_cart_hand_lists_nothing(self):
        comp = self.pack("stock_shadow3_test")
        code, row = invoke(["module", "plan", str(comp), "--output", self.out(),
                            "--base-listings", str(self.root / "packs" / "listings")])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["base_owned_names"], 2, "the reference row is not a base copy")
        check = next(c for c in row["result"]["checks"] if c["id"] == "donor-shadowing")
        self.assertEqual(check["outcome"], "passed")
        doc = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        self.assertEqual(doc["base_loads"], ["common_zm"], "the load with a listing is the base's; the one without it is the donor")
        self.assertEqual([Path(p).name for p in doc["base_listings"]], ["common_zm-list.txt"])
        self.assertEqual(doc["base_owned_assets"], {"image": 1, "material": 1})
        code, row = invoke(["module", "plan", str(comp), "--output", self.out(), "--base-listings", str(self.root / "nope")])
        self.assertEqual(row["error_code"], "input_missing")

    def test_a_foundation_descriptor_can_name_the_listings_directory(self):
        from plutonium_agent_toolkit.dev import targets
        (self.root / "foundations").mkdir(parents=True, exist_ok=True)
        (self.root / "foundations" / "stock-fnd.json").write_text(json.dumps(
            {"schema": 1, "id": "stock-fnd", "profile_prefix": "stock", "maps": {"zm_transit": {}},
             "base_listings": "packs/listings"}))
        self.assertEqual(targets.base_listing_dirs(self.root, "stock-fnd"), [self.root / "packs" / "listings"])
        self.assertEqual(targets.base_listing_dirs(self.root, "absent-fnd"), [])

    def test_a_foundation_link_load_is_the_base_even_with_no_listing_staged_here(self):
        """A build against the foundation's own zones and nothing else has no donor, so it needs no
        listing: `module qualify` links exactly that way."""
        (self.root / "foundations").mkdir(parents=True, exist_ok=True)
        (self.root / "foundations" / "stock-fnd.json").write_text(json.dumps(
            {"schema": 1, "id": "stock-fnd", "profile_prefix": "stock",
             "maps": {"zm_transit": {"link_loads": ["common_zm"]}}}))
        self.module("skull")
        comp = self.composition(["skull"], name="stock_shadow4_test", loads=["../zones/common_zm.ff"])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out(), "--workspace", str(self.root)])
        self.assertEqual(code, 0, row)
        check = next(c for c in row["result"]["checks"] if c["id"] == "donor-shadowing")
        self.assertEqual(check["outcome"], "passed")
        self.assertIn("no donor zone", check["detail"])
        # Add the donor back and the same composition is refused again: only the declared zone is base.
        comp = self.composition(["skull"], name="stock_shadow5_test", loads=["../zones/common_zm.ff", "../zones/moon.ff"])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out(), "--workspace", str(self.root)])
        self.assertEqual(code, 1, row)
        check = next(c for c in row["details"]["checks"] if c["id"] == "donor-shadowing")
        self.assertEqual((check["outcome"], check["count"], check["names"]), ("failed", 1, ["moon"]))


class LooseOverrideTests(CompositionFixture):
    """Plutonium's global `storage/t6/images` is the other half of the shadowing failure, and it is
    not in any fastfile: a loose file there wins over every image bank, for every mod folder on the
    machine and for the bare game with none selected. A loose copy of a base-owned name therefore
    repaints that name on the bare foundation too, which is why a rendering diagnosis starts with a
    control load and why this refuses at plan time. The executable half of that section in
    docs/MODULES.md.
    """

    def setUp(self):
        super().setUp()
        self.module("skull")
        d = self.root / "packs" / "zones"
        d.mkdir(parents=True, exist_ok=True)
        (d / "common_zm.ff").write_text(json.dumps({"zone": "common_zm", "rawfiles": {}, "assets": [], "pulls": []}))
        listings = self.root / "packs" / "listings"
        listings.mkdir(parents=True, exist_ok=True)
        (listings / "common_zm-list.txt").write_text("image, camo_zombies_nml\nmaterial, mtl_stock\n")

    def storage(self, *loose):
        """A configured Plutonium T6 storage folder, with `images/` present only when asked."""
        storage = self.root / "storage" / "t6"
        storage.mkdir(parents=True, exist_ok=True)
        if loose:
            (storage / "images").mkdir(exist_ok=True)
            for name in loose:
                (storage / "images" / name).write_bytes(b"IWi\x0d" + b"\0" * 32)
        code, row = invoke(["configure", "--plutonium-storage-t6", str(storage)])
        self.assertEqual(code, 0, row)
        return storage

    def pack(self, name):
        return self.composition(["skull"], name=name, loads=["../zones/common_zm.ff"],
                                base_owned=["../listings/common_zm-list.txt"])

    def test_a_loose_file_carrying_a_base_owned_name_refuses_the_plan(self):
        self.storage("camo_zombies_nml.iwi", "t5_weapon_thundergun_n.iwi")
        code, row = invoke(["module", "plan", str(self.pack("stock_loose_test")), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertIn("loose-overrides:camo_zombies_nml", row["message"])
        check = next(c for c in row["details"]["checks"] if c["id"] == "loose-overrides")
        self.assertEqual(check["outcome"], "failed")
        self.assertEqual((check["count"], check["names"]), (1, ["camo_zombies_nml"]))
        self.assertTrue(check["counted"])
        named = next(c for c in row["details"]["checks"] if c["id"] == "loose-overrides:camo_zombies_nml")
        self.assertEqual(named["outcome"], "failed")
        self.assertIn("camo_zombies_nml.iwi", named["detail"])

    def test_a_configured_loose_path_with_nothing_the_base_owns_passes(self):
        self.storage("t5_weapon_thundergun_n.iwi")
        code, row = invoke(["module", "plan", str(self.pack("stock_loose2_test")), "--output", self.out()])
        self.assertEqual(code, 0, row)
        check = next(c for c in row["result"]["checks"] if c["id"] == "loose-overrides")
        self.assertEqual(check["outcome"], "passed")
        self.assertEqual((check["count"], check["loose_images"], check["counted"]), (0, 1, True))

    def test_a_configured_storage_without_an_images_folder_is_not_counted(self):
        self.storage()
        code, row = invoke(["module", "plan", str(self.pack("stock_loose3_test")), "--output", self.out()])
        self.assertEqual(code, 0, row)
        check = next(c for c in row["result"]["checks"] if c["id"] == "loose-overrides")
        self.assertEqual(check["outcome"], "not_counted")
        self.assertFalse(check["counted"], "an absent loose path is uncounted, not clean")

    def test_no_configured_storage_is_not_counted_and_not_a_pass(self):
        code, row = invoke(["module", "plan", str(self.pack("stock_loose4_test")), "--output", self.out()])
        self.assertEqual(code, 0, row)
        check = next(c for c in row["result"]["checks"] if c["id"] == "loose-overrides")
        self.assertEqual(check["outcome"], "not_counted")
        self.assertFalse(check["counted"])
        self.assertIn("pat configure --plutonium-storage-t6", check["hint"])

    def test_an_iw5_pack_is_never_judged_against_t6_s_loose_folder(self):
        self.storage("camo_zombies_nml.iwi")
        d = self.module("iw5_thing", game="iw5")
        recipe = json.loads((d / "project.json").read_text()); recipe["game"] = "iw5"; recipe["mode"] = "mp"
        (d / "project.json").write_text(json.dumps(recipe))
        comp = self.composition(["iw5_thing"], name="iw5_loose_test", base="stock", map_id="mp_alpha", game="iw5")
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        checks = (row.get("result") or row.get("details") or {}).get("checks") or []
        self.assertFalse([c for c in checks if c["id"].startswith("loose-overrides")], row)

    def test_a_composition_with_no_base_listing_compares_nothing(self):
        self.storage("camo_zombies_nml.iwi")
        comp = self.composition(["skull"], name="stock_loose5_test", loads=["../zones/common_zm.ff"])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        # No listing is already a donor-shadowing refusal; loose-overrides has nothing to compare.
        self.assertEqual(code, 1, row)
        check = next(c for c in row["details"]["checks"] if c["id"] == "loose-overrides")
        self.assertEqual(check["outcome"], "not_counted")
        self.assertIn("No base listing", check["detail"])


class RecipeLoadTests(CompositionFixture):
    """A member's own `loads` are the pack's loads.

    A module whose assets resolve against a donor zone says so in its recipe, once, where the
    assets are. Every composition that includes that module links against that zone: the composer
    does not repeat the row, and a pack that already loads it does not link it twice. The zone is
    a payload nobody ships, so one that is not on this machine refuses per member, by name.
    """

    def zone(self, name, directory="zones", pulls=()):
        d = self.root / "packs" / directory
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{name}.ff"
        path.write_text(json.dumps({"zone": name, "rawfiles": {}, "assets": [], "pulls": list(pulls)}))
        return path

    def listings(self, **zones):
        d = self.root / "packs" / "listings"
        d.mkdir(parents=True, exist_ok=True)
        for zone_name, rows in zones.items():
            (d / f"{zone_name}-list.txt").write_text("".join(f"{row}\n" for row in rows))
        return d

    def donor_module(self, mid, zone="zm_moon_patch", **overrides):
        """A module whose recipe names the zone its assets resolve against, beside the recipe."""
        d = self.module(mid, **overrides)
        path = d / "donor" / f"{zone}.ff"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"zone": zone, "rawfiles": {}, "assets": [], "pulls": []}))
        recipe = json.loads((d / "project.json").read_text())
        recipe["loads"] = [f"donor/{zone}.ff"]
        (d / "project.json").write_text(json.dumps(recipe, indent=2))
        return d, path

    def plan(self, comp, *extra, expect=0):
        code, row = invoke(["module", "plan", str(comp), "--output", self.out(), *extra])
        self.assertEqual(code, expect, row)
        result = row.get("result") or row.get("details") or {}
        if expect != 0:
            return row, result
        return row, json.loads((Path(result["output"]) / "plan.json").read_text())

    def loaded_argv(self, receipt):
        """Every path the link step was told to load with `-l`, in the order it was told."""
        rows = json.loads(Path(receipt).read_text())
        for step in rows["steps"]:
            argv = step["argv"]
            if "-l" in argv:
                return [argv[i + 1] for i, a in enumerate(argv) if a == "-l"]
        return []

    def test_a_members_recipe_load_is_planned_reported_and_linked_for_the_pack(self):
        self.zone("common_zm")
        self.listings(common_zm=["image, camo_gold_nml", "material, mtl_stock"])
        d, donor = self.donor_module("alpha")
        comp = self.composition(["alpha"], loads=["../zones/common_zm.ff"])
        row, plan = self.plan(comp, "--base-listings", str(self.root / "packs" / "listings"))
        self.assertEqual(plan["loads"], [str(self.root / "packs" / "zones" / "common_zm.ff"), str(donor)],
                         "the composition's own loads first, then the member's")
        self.assertEqual(plan["modules"][0]["recipe_loads"], [str(donor)])
        # Hashed like every other input: the receipt re-reads it and a change after the plan fails.
        receipt = json.loads((Path(row["result"]["output"]) / "receipt.json").read_text())
        self.assertIn(str(donor), receipt["inputs"])
        code, built = invoke(["module", "build", str(comp), "--output", self.out(),
                              "--base-listings", str(self.root / "packs" / "listings")])
        self.assertEqual(code, 0, built)
        self.assertEqual(self.loaded_argv(Path(built["result"]["output"]) / "receipt.json"),
                         [str(self.root / "packs" / "zones" / "common_zm.ff"), str(donor)],
                         "the linker was given the member's zone as well as the pack's")

    def test_the_same_zone_named_twice_is_linked_once(self):
        """The pack that already loads a donor zone gains a member whose recipe names the same
        file: one `-l`, in the position the composition's own row gave it."""
        self.zone("common_zm")
        self.listings(common_zm=["image, camo_gold_nml"])
        d, donor = self.donor_module("alpha")
        self.module("beta")
        shared = Path("../..") / donor.relative_to(self.root)
        comp = self.composition(["alpha", "beta"], loads=["../zones/common_zm.ff", shared.as_posix()])
        row, plan = self.plan(comp, "--base-listings", str(self.root / "packs" / "listings"))
        self.assertEqual(plan["loads"], [str(self.root / "packs" / "zones" / "common_zm.ff"), str(donor)])
        self.assertEqual(plan["modules"][0]["recipe_loads"], [str(donor)])
        self.assertEqual(plan["modules"][1]["recipe_loads"], [], "beta names none")
        code, built = invoke(["module", "build", str(comp), "--output", self.out(),
                              "--base-listings", str(self.root / "packs" / "listings")])
        self.assertEqual(code, 0, built)
        self.assertEqual(self.loaded_argv(Path(built["result"]["output"]) / "receipt.json").count(str(donor)), 1)

    def test_two_members_naming_the_same_zone_link_it_once(self):
        """The other shape of the same fact: a nested pack names the donor its own way and the
        member's recipe names it beside the assets. Two members, one `-l`."""
        self.zone("common_zm")
        self.listings(common_zm=["image, camo_gold_nml"])
        d, donor = self.donor_module("alpha")
        self.module("beta")
        self.composition(["beta"], name="stock_inner_pack",
                         loads=[(Path("../..") / donor.relative_to(self.root)).as_posix()])
        comp = self.composition([{"path": "../stock_inner_pack"}, "alpha"],
                                name="stock_outer_test", loads=["../zones/common_zm.ff"])
        row, plan = self.plan(comp, "--base-listings", str(self.root / "packs" / "listings"))
        self.assertEqual(plan["loads"], [str(self.root / "packs" / "zones" / "common_zm.ff"), str(donor)])
        self.assertEqual(sorted(m["id"] for m in plan["modules"]), ["alpha", "beta"])
        code, built = invoke(["module", "build", str(comp), "--output", self.out(),
                              "--base-listings", str(self.root / "packs" / "listings")])
        self.assertEqual(code, 0, built)
        self.assertEqual(self.loaded_argv(Path(built["result"]["output"]) / "receipt.json").count(str(donor)), 1)

    def test_a_recipe_load_this_machine_does_not_hold_refuses_by_member_and_path(self):
        d, donor = self.donor_module("alpha")
        self.module("beta")
        donor.unlink()
        comp = self.composition(["alpha", "beta"])
        row, details = self.plan(comp, expect=1)
        self.assertEqual(row["error_code"], "input_missing")
        refusal = details["refusals"][0]
        self.assertEqual((refusal["kind"], refusal["modules"]), ("private_payload", ["alpha"]))
        self.assertIn(str(donor), refusal["message"])
        self.assertEqual(refusal["missing"], [str(donor)])
        code, built = invoke(["module", "build", str(comp), "--output", self.out()])
        self.assertEqual(code, 1, built)
        self.assertEqual(built["details"]["refusals"][0]["kind"], "private_payload")

    def test_donor_loads_names_the_zones_outside_the_base_and_omits_the_base_s_own(self):
        """`donor_loads` is the complement of `base_loads`, over every load whoever named it: the
        composition's `common_zm` has a listing and is the base's; the member's has none."""
        self.zone("common_zm")
        self.listings(common_zm=["image, camo_gold_nml"])
        d, donor = self.donor_module("alpha")
        comp = self.composition(["alpha"], loads=["../zones/common_zm.ff"])
        row, plan = self.plan(comp, "--base-listings", str(self.root / "packs" / "listings"))
        self.assertEqual(plan["base_loads"], ["common_zm"])
        self.assertEqual(plan["donor_loads"], ["zm_moon_patch"])
        self.assertEqual(row["result"]["donor_loads"], ["zm_moon_patch"], "and the plan summary says it too")

    def test_donor_shadowing_judges_a_members_recipe_load_like_any_other_donor(self):
        """The check classifies by listing presence, so a zone a member named is a donor to it:
        with no listing the pack refuses, and the refusal names the member's zone."""
        self.zone("common_zm")
        d, donor = self.donor_module("alpha")
        comp = self.composition(["alpha"], loads=["../zones/common_zm.ff"])
        row, details = self.plan(comp, expect=1)
        check = next(c for c in details["checks"] if c["id"] == "donor-shadowing")
        self.assertEqual((check["outcome"], check["count"], check["names"]), ("failed", 2, ["common_zm", "zm_moon_patch"]))
        # With the base's listing staged, the member's zone is the only donor left.
        self.listings(common_zm=["image, camo_gold_nml"])
        row, plan = self.plan(comp, "--base-listings", str(self.root / "packs" / "listings"))
        check = next(c for c in row["result"]["checks"] if c["id"] == "donor-shadowing")
        self.assertEqual(check["outcome"], "passed")
        self.assertEqual(plan["donor_loads"], ["zm_moon_patch"])
