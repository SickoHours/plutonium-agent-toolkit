"""IW5 (MW3) support: the title seam threads a game through the gsc, project and composition
routes without forking them. These run against the same fake backends as the T6 tests and assert
the IW5-specific stamps: gsc records ``game=iw5``, the recipe and zone use mp/``> game,IW5``, and a
title cannot be mixed inside one composition. Real IW5 OpenAssetTools/gsc-tool qualification is a
separate step on a Windows or Linux host with the real programs (see the IW5 rows in docs/SUPPORT.md).
"""
import json
import unittest
from pathlib import Path

from plutonium_agent_toolkit.core.errors import Failure
from plutonium_agent_toolkit.dev import titles
from tests.test_dev_routes import DevRouteFixture, invoke


class TitlesUnitTests(unittest.TestCase):
    def test_known_titles_and_tokens(self):
        self.assertEqual(titles.DEFAULT_TITLE, "t6")
        self.assertIn("iw5", titles.names())
        self.assertEqual(titles.gsc_game("iw5"), "iw5")
        self.assertEqual(titles.gsc_game("t6"), "t6")
        self.assertEqual(titles.zone("iw5")["game_token"], "IW5")
        self.assertEqual(titles.zone("t6")["game_token"], "T6")
        self.assertEqual(titles.zone("t6")["name"], titles.zone("iw5")["name"], "both bind to mod.ff")

    def test_unknown_title_is_a_failure(self):
        with self.assertRaises(Failure):
            titles.get("iw4")


class Iw5DevTests(DevRouteFixture):
    def _mod_zone(self, build: Path) -> list[str]:
        zones = list(build.rglob("*.zone"))
        self.assertEqual(len(zones), 1, zones)
        return zones[0].read_text(encoding="utf-8").splitlines()

    def test_gsc_compile_records_iw5(self):
        src = self.root / "hello.gsc"
        src.write_text('main() { self iprintln("hi"); }\n')
        code, row = invoke(["gsc", "compile", str(src), "--game", "iw5", "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["game"], "iw5")

    def test_gsc_compile_defaults_to_t6(self):
        src = self.root / "hello.gsc"
        src.write_text('main() { self iprintln("hi"); }\n')
        code, row = invoke(["gsc", "compile", str(src), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["game"], "t6")

    def test_project_init_plan_build_iw5(self):
        code, row = invoke(["project", "init", "--name", "iw5_demo", "--game", "iw5", "--output", self.out()])
        self.assertEqual(code, 0, row)
        project = Path(row["result"]["output"])
        recipe = json.loads((project / "project.json").read_text())
        self.assertEqual(recipe["game"], "iw5")
        self.assertEqual(recipe["mode"], "mp")
        self.assertEqual(recipe["scripts"][0]["target"], "scripts/mp/iw5_demo.gsc")

        code, row = invoke(["project", "plan", str(project / "project.json"), "--output", self.out()])
        self.assertEqual(code, 0, row)
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        self.assertEqual(plan["game"], "iw5")
        self.assertEqual(plan["mode"], "mp")

        code, row = invoke(["project", "build", str(project / "project.json"), "--output", self.out()])
        self.assertEqual(code, 0, row)
        build = Path(row["result"]["output"])
        self.assertEqual(row["result"]["game"], "iw5")
        self.assertEqual(row["result"]["mod_ff"], "packages/mod.ff")
        header = self._mod_zone(build)
        self.assertEqual(header[0], "> game,IW5")
        self.assertEqual(header[1], "> name,mod")

    def test_declare_writes_the_iw5_game_into_the_draft(self):
        code, row = invoke(["project", "init", "--name", "iw5_seed", "--game", "iw5", "--output", self.out()])
        project = Path(row["result"]["output"])
        code, row = invoke(["project", "build", str(project / "project.json"), "--output", self.out()])
        self.assertEqual(code, 0, row)
        mod_ff = Path(row["result"]["output"]) / row["result"]["mod_ff"]
        code, row = invoke(["module", "declare", str(mod_ff), "--game", "iw5", "--base", "stock",
                            "--map", "mp_dome", "--id", "iw5_seed", "--output", self.out()])
        self.assertEqual(code, 0, row)
        draft = json.loads((Path(row["result"]["output"]) / "module.json").read_text())
        self.assertEqual(draft["game"], "iw5")
        self.assertEqual(draft["distribution"], "seed")

    def test_t6_build_is_unchanged(self):
        code, row = invoke(["project", "init", "--name", "t6_demo", "--output", self.out()])
        project = Path(row["result"]["output"])
        recipe = json.loads((project / "project.json").read_text())
        self.assertEqual((recipe["game"], recipe["mode"]), ("t6", "zm"))
        code, row = invoke(["project", "build", str(project / "project.json"), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(self._mod_zone(Path(row["result"]["output"]))[0], "> game,T6")


class Iw5CompositionTests(DevRouteFixture):
    def _iw5_module(self, mid):
        d = self.root / "modules" / mid
        (d / "scripts").mkdir(parents=True, exist_ok=True)
        (d / "scripts" / f"{mid}.gsc").write_text(f"main()\n{{\n    level thread {mid}();\n}}\n\n{mid}()\n{{\n    wait 1;\n}}\n")
        (d / "project.json").write_text(json.dumps({
            "schema": 1, "game": "iw5", "mode": "mp", "name": mid,
            "scripts": [{"source": f"scripts/{mid}.gsc", "target": f"scripts/mp/{mid}.gsc", "instance": "server"}],
            "assets": [], "loads": []}))
        (d / "module.json").write_text(json.dumps({
            "schema": 1, "id": mid, "version": "0.1.0", "game": "iw5", "title": mid,
            "category": "scripts", "recipe": "project.json", "bases": ["stock"], "maps": ["*"],
            "resource_contract": {"threads": 1, "entities": 0, "hud": 0, "network_fields": 0}}))
        return d

    def _composition(self, name, game, modules):
        d = self.root / "packs" / name
        d.mkdir(parents=True, exist_ok=True)
        row = {"schema": 1, "name": name, "game": game, "base": "stock", "map": "mp_dome",
               "modules": [(Path("../../modules") / m).as_posix() for m in modules], "loads": []}
        (d / "composition.json").write_text(json.dumps(row))
        return d / "composition.json"

    def test_iw5_composition_builds_with_the_iw5_header(self):
        self._iw5_module("alpha")
        self._iw5_module("beta")
        comp = self._composition("stock_pack_test", "iw5", ["alpha", "beta"])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        self.assertEqual((plan["game"], plan["mode"]), ("iw5", "mp"))

        code, row = invoke(["module", "build", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        zones = list(Path(row["result"]["output"]).rglob("*.zone"))
        self.assertEqual(zones[0].read_text().splitlines()[0], "> game,IW5")

    def test_a_kind_from_another_title_is_refused(self):
        # `wonder` is a T6 weapons kind; IW5's weapons kinds are primary/secondary/launcher/melee/
        # special, so an IW5 module declaring weapons/wonder is refused.
        d = self._iw5_module("wonder_mod")
        decl = json.loads((d / "module.json").read_text())
        decl["category"], decl["kind"] = "weapons", "wonder"
        (d / "module.json").write_text(json.dumps(decl))
        comp = self._composition("stock_pack_test", "iw5", ["wonder_mod"])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")

    def test_mixing_titles_in_one_composition_is_refused(self):
        self._iw5_module("alpha")
        beta = self.root / "modules" / "beta"
        (beta / "scripts").mkdir(parents=True, exist_ok=True)
        (beta / "scripts" / "beta.gsc").write_text("main()\n{\n    wait 1;\n}\n")
        (beta / "project.json").write_text(json.dumps({
            "schema": 1, "game": "t6", "mode": "zm", "name": "beta",
            "scripts": [{"source": "scripts/beta.gsc", "target": "scripts/zm/beta.gsc", "instance": "server"}],
            "assets": [], "loads": []}))
        (beta / "module.json").write_text(json.dumps({
            "schema": 1, "id": "beta", "version": "0.1.0", "game": "t6", "title": "beta",
            "category": "scripts", "recipe": "project.json", "bases": ["stock"], "maps": ["*"],
            "resource_contract": {"threads": 1, "entities": 0, "hud": 0, "network_fields": 0}}))
        comp = self._composition("stock_pack_test", "iw5", ["alpha", "beta"])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("beta", json.dumps(row))


if __name__ == "__main__":
    unittest.main()
