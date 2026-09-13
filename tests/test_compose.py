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

    def test_recipe_names_the_members_title_and_refuses_a_mixed_or_wrong_game(self):
        (self.root / "modules" / "mp_only").mkdir(parents=True)
        (self.root / "modules" / "mp_only" / "module.json").write_text(json.dumps({
            "schema": 1, "id": "mp_only", "version": "0.1.0", "game": "iw5", "title": "mp_only", "category": "scripts",
            "recipe": "project.json", "bases": ["stock"], "maps": ["*"], "dependencies": [], "conflicts": [],
            "resource_contract": {"threads": 1, "entities": 0, "hud": 0, "network_fields": 0}}))
        code, row = invoke(self.inputs() + ["--module", "alpha", "--output", self.out()])
        self.assertEqual(code, 0, row)
        recipe = json.loads(Path(row["result"]["composition"]).read_text())
        self.assertEqual(recipe["game"], "t6", "derived from the only title the members declare")
        code, row = invoke(self.inputs() + ["--module", "alpha", "--module", "mp_only", "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("more than one title", row["message"])
        code, row = invoke(self.inputs() + ["--game", "iw5", "--module", "alpha", "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertIn("--game iw5", row["message"])

    def test_malformed_foundation_link_loads_refuse(self):
        args = self.inputs()
        foundation = Path(args[args.index("--foundation") + 1])
        for broken in ({"link_loads": "zm_factory"}, {"link_loads": {"zm_factory": [7]}}, {"link_loads": {"zm_factory": "x"}}):
            foundation.write_text(json.dumps(broken))
            code, row = invoke(args + ["--module", "alpha", "--output", self.out()])
            self.assertEqual(code, 1, row)
            self.assertEqual(row["error_code"], "input_invalid", row)

    def test_foundation_zone_header_must_be_strings(self):
        args = self.inputs()
        foundation = Path(args[args.index("--foundation") + 1])
        foundation.write_text(json.dumps({"link_loads": {"zm_factory": []}, "mod_zone_header": [">game,T6", 7]}))
        code, row = invoke(args + ["--module", "alpha", "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("mod_zone_header", row["message"])

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

    def test_discovery_does_not_spend_the_selected_input_budget(self):
        args = self.inputs()
        declaration = json.loads((self.root/'modules/alpha/module.json').read_text())
        for i in range(4093):
            directory = self.root/'modules'/f'unused_{i}'
            directory.mkdir()
            (directory/'module.json').write_text(json.dumps(dict(declaration, id=f'unused_{i}')))
        code, row = invoke(args + ['--module','alpha','--output',self.out()])
        self.assertEqual(code, 0, row)
        receipt = json.loads(Path(row['result']['receipt']).read_text())
        self.assertLess(len(receipt['inputs']), 10)
        self.assertIn(str(self.root/'foundation.json'), receipt['inputs'])

    def test_publish_refuses_a_deleted_member_load_or_owned_listing(self):
        import hashlib
        import shutil
        from types import SimpleNamespace
        from plutonium_agent_toolkit.dev import compose
        from plutonium_agent_toolkit.core.jobs import Job
        from plutonium_agent_toolkit.core.errors import Failure
        args = self.inputs()
        for kind in ('member', 'load', 'owned'):
            with self.subTest(kind=kind):
                source_root = self.root/f'publish-{kind}'
                source_root.mkdir()
                member = source_root/'member'
                member.mkdir()
                (member/'module.json').write_text((self.root/'modules/alpha/module.json').read_text())
                load = source_root/'base.ff'
                load.write_bytes(b'fixture')
                owned = source_root/'owned.txt'
                owned.write_text('image,example')
                recipe = source_root/'composition.json'
                recipe.write_text(json.dumps({'schema':1,'name':'stock_sample_pack','base':'stock','map':'zm_transit','modules':['member'],'loads':['base.ff'],'base_owned':['owned.txt']}))
                package = source_root/'mod.ff'
                package.write_bytes(b'package')
                receipt = source_root/'build.json'
                receipt.write_text(json.dumps({'command':'module build','status':'succeeded','ok':True,'inputs':{str(recipe):hashlib.sha256(recipe.read_bytes()).hexdigest()},'outputs':{'mod.ff':hashlib.sha256(package.read_bytes()).hexdigest()},'result':{'mod_ff':'mod.ff'}}))
                if kind == 'member': shutil.rmtree(member)
                elif kind == 'load': load.unlink()
                else: owned.unlink()
                destination = source_root/'saved/stock_sample_pack'
                job = Job(Path(self.out()), 'module compose', [])
                with self.assertRaises(Failure) as raised:
                    compose.publish(SimpleNamespace(composition=str(recipe),from_build=str(receipt),publish_to=str(destination)), job)
                self.assertEqual(raised.exception.code, 'input_missing')
                self.assertFalse(destination.exists())
