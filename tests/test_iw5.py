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

    def test_script_form_magic_and_instances(self):
        self.assertEqual(titles.script_form("t6"), "compiled")
        self.assertEqual(titles.script_form("iw5"), "source")
        self.assertEqual(titles.title_of_magic(b"IWffu100\x01"), "iw5")
        self.assertEqual(titles.title_of_magic(b"TAff\x00\x00"), "t6")
        self.assertIsNone(titles.title_of_magic(b"FASTFILE"))
        self.assertEqual(titles.instances("iw5"), ("server",))
        self.assertEqual(titles.modes("iw5"), ("mp",))
        self.assertEqual(titles.script_target("iw5", "x"), "scripts/x.gsc")


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

    def test_gsc_check_writes_nothing_and_refuses_a_client_instance_on_iw5(self):
        src = self.root / "hello.gsc"
        src.write_text('main() { self iprintln("hi"); }\n')
        code, row = invoke(["gsc", "check", str(src), "--game", "iw5", "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["files"], [])
        self.assertEqual(row["result"]["checked"], "hello.gsc")
        self.assertFalse(list((Path(row["result"]["output"]) / "compiled").rglob("*")) if (Path(row["result"]["output"]) / "compiled").exists() else [])
        csc = self.root / "hud.csc"
        csc.write_text("main() {}\n")
        code, row = invoke(["gsc", "check", str(csc), "--game", "iw5", "--output", self.out()])
        self.assertEqual(row["error_code"], "input_invalid")
        bad = self.root / "bad.gsc"
        bad.write_text("main() { FAIL_COMPILE }\n")
        code, row = invoke(["gsc", "check", str(bad), "--game", "iw5", "--output", self.out()])
        self.assertEqual(row["error_code"], "backend_failed")

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
        self.assertEqual(recipe["scripts"][0]["target"], "scripts/iw5_demo.gsc")

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
        # The rawfile is the source text: Plutonium IW5 compiles it, gsc-tool only checked it.
        self.assertEqual(row["result"]["script_form"], "source")
        packed = (build / "readback" / "scripts" / "iw5_demo.gsc").read_text()
        self.assertIn("main()", packed)
        self.assertNotIn("COMPILED:", packed)
        self.assertEqual((build / "script-000" / "receipt.json").exists(), True)
        self.assertIn("gsc check", (build / "script-000" / "receipt.json").read_text())

    def test_iw5_refuses_sp_mode_and_client_scripts(self):
        d = self.root / "sp"
        (d / "scripts").mkdir(parents=True)
        (d / "scripts" / "a.gsc").write_text("main() {}\n")
        (d / "scripts" / "b.csc").write_text("main() {}\n")
        for recipe in ({"schema": 1, "game": "iw5", "mode": "sp", "name": "a",
                        "scripts": [{"source": "scripts/a.gsc", "target": "scripts/a.gsc"}], "assets": [], "loads": []},
                       {"schema": 1, "game": "iw5", "mode": "mp", "name": "b",
                        "scripts": [{"source": "scripts/b.csc", "target": "scripts/b.csc"}], "assets": [], "loads": []}):
            (d / "project.json").write_text(json.dumps(recipe))
            code, row = invoke(["project", "plan", str(d / "project.json"), "--output", self.out()])
            self.assertEqual(row["error_code"], "input_invalid", row)

    def test_t6_build_still_packs_the_compiled_script(self):
        code, row = invoke(["project", "init", "--name", "t6_c", "--output", self.out()])
        project = Path(row["result"]["output"])
        code, row = invoke(["project", "build", str(project / "project.json"), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["script_form"], "compiled")
        packed = (Path(row["result"]["output"]) / "readback" / "scripts" / "zm" / "t6_c.gsc").read_bytes()
        self.assertTrue(packed.startswith(b"COMPILED:"))

    def test_declare_writes_the_iw5_game_into_the_draft(self):
        code, row = invoke(["project", "init", "--name", "iw5_seed", "--game", "iw5", "--output", self.out()])
        project = Path(row["result"]["output"])
        code, row = invoke(["project", "build", str(project / "project.json"), "--output", self.out()])
        self.assertEqual(code, 0, row)
        mod_ff = Path(row["result"]["output"]) / row["result"]["mod_ff"]
        code, row = invoke(["module", "declare", str(mod_ff), "--game", "iw5", "--base", "stock",
                            "--map", "mp_dome", "--id", "iw5_seed", "--output", self.out()])
        self.assertEqual(code, 0, row)
        # The fake linker writes JSON packages without a magic, so --game is required there; a
        # real IWffu100 package is sniffed (covered by test_install below).
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
            "scripts": [{"source": f"scripts/{mid}.gsc", "target": f"scripts/{mid}.gsc", "instance": "server"}],
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


class Iw5InstallTests(unittest.TestCase):
    def setUp(self):
        import os
        import tempfile
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        os.environ["PAT_HOME"] = str(self.root / "home")
        self.addCleanup(lambda: os.environ.pop("PAT_HOME", None))
        self.t6 = self.root / "storage" / "t6"
        self.iw5 = self.root / "storage" / "iw5"
        (self.t6 / "mods").mkdir(parents=True)
        self.iw5.mkdir(parents=True)
        invoke(["configure", "--plutonium-storage-t6", str(self.t6), "--plutonium-storage-iw5", str(self.iw5)])

    def _package(self, magic: bytes) -> Path:
        p = self.root / "build" / magic.decode()[:4] / "packages" / "mod.ff"
        p.parent.mkdir(parents=True)
        p.write_bytes(magic + b"\x01\x00\x00\x00payload")
        return p

    def test_the_magic_routes_the_package_to_its_storage(self):
        code, row = invoke(["game", "install-mod", str(self._package(b"IWffu100")), "hello_iw5"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["game"], "iw5")
        self.assertTrue((self.iw5 / "mods" / "hello_iw5" / "mod.ff").is_file())
        self.assertFalse((self.t6 / "mods" / "hello_iw5").exists())
        self.assertIn("fs_game mods/hello_iw5", row["result"]["next"][0])
        code, row = invoke(["game", "install-mod", str(self._package(b"TAff")), "hello_zm"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["game"], "t6")
        self.assertTrue((self.t6 / "mods" / "hello_zm" / "mod.ff").is_file())

    def test_an_unknown_magic_is_refused_when_both_storages_exist(self):
        code, row = invoke(["game", "install-mod", str(self._package(b"NOPE")), "x"])
        self.assertEqual(row["error_code"], "input_invalid")

    def test_declare_sniffs_the_title_and_refuses_a_contradiction(self):
        pkg = self._package(b"IWffu100")
        code, row = invoke(["module", "declare", str(pkg), "--game", "t6", "--output", str(self.root / "out-declare")])
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertIn("iw5", row["message"])


if __name__ == "__main__":
    unittest.main()
