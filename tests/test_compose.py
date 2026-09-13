import json
from pathlib import Path
from tests.test_compositions import CompositionFixture
from tests.test_dev_routes import invoke


class ComposeTests(CompositionFixture):
    def inputs(self):
        self.module("alpha", maps=["zm_transit"])
        self.module("alpha_registration", dependencies=["alpha"])
        self.module("beta")
        foundation = self.root / "foundation.json"
        foundation.write_text(json.dumps({"link_loads": {"zm_factory": []}, "mod_zone_header": [">game,T6", ">level.ipak_read,zm_transit"]}))
        return ["module", "compose", "--name", "b2_sample_pack", "--base", "b2", "--map", "zm_factory", "--foundation", str(foundation), "--member-root", str(self.root / "modules")]

    def test_compose_resolves_ids_registration_and_map_loads(self):
        code, row = invoke(self.inputs() + ["--module", "alpha", "--module", "beta", "--output", self.out()])
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertEqual({m["id"] for m in result["modules"]}, {"alpha", "alpha_registration", "beta"})
        self.assertEqual(len(result["unqualified"]), 3)
        recipe = json.loads(Path(result["composition"]).read_text())
        self.assertIn(">level.ipak_read,zm_factory", recipe["zone_header"])
        self.assertEqual(recipe["loads"], [])
        self.assertTrue((Path(result["output"]) / result["plan_receipt"]).is_file())

    def test_missing_module_and_unstaged_map_refuse(self):
        args = self.inputs()
        code, row = invoke(args + ["--module", "missing", "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_missing")
        self.assertIn("missing", row["message"])
        args[args.index("--map") + 1] = "zm_moon"
        code, row = invoke(args + ["--module", "alpha", "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertIn("zm_moon", row["message"])

    def test_publish_requires_exact_successful_build_and_does_not_replace(self):
        code, row = invoke(self.inputs() + ["--module", "alpha", "--output", self.out()])
        self.assertEqual(code, 0, row)
        composition = row["result"]["composition"]
        plan_receipt = str(Path(row["result"]["output"]) / row["result"]["plan_receipt"])
        target = self.root / "templates" / "b2_sample_pack"
        args = ["module", "compose", "--composition", composition, "--publish-to", str(target), "--from-build"]
        code, row = invoke(args + [plan_receipt, "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertFalse(target.exists())
        code, row = invoke(["module", "build", composition, "--allow-unqualified", "--output", self.out()])
        self.assertEqual(code, 0, row)
        receipt = row["result"]["receipt"]
        code, row = invoke(args + [receipt, "--output", self.out()])
        self.assertEqual(code, 0, row)
        saved = target / "composition.json"
        before = saved.read_bytes()
        code, row = invoke(["module", "plan", str(saved), "--allow-unqualified", "--output", self.out()])
        self.assertEqual(code, 0, row)
        code, row = invoke(args + [receipt, "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertEqual(saved.read_bytes(), before)
