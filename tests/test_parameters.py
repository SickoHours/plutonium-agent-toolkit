"""Declared module parameters: the ``parameters`` field on module.json, the per-member
``parameters`` map on a composition, and the effective map the plan and the build record.

The format is specified in docs/MODULES.md; these tests are the executable half of that
section. Examples are neutral: a rotation cadence and a mystery-box flag.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plutonium_agent_toolkit import cli
from plutonium_agent_toolkit.dev import parameters
from tests.test_compositions import CompositionFixture
from tests.test_dev_routes import invoke as job_invoke

ROOT = Path(__file__).resolve().parents[1]

CADENCE = {"name": "cadence", "type": "string", "values": ["round", "timer"], "default": "round",
           "meaning": "round: reassign when a round ends. timer: wait between cycles."}
MIN_WAIT = {"name": "min_wait", "type": "int", "range": [5, 600], "default": 90,
            "meaning": "Timer cadence lower bound in seconds; ignored under the round cadence."}
BOX = {"name": "box", "type": "bool", "default": True,
       "meaning": "Whether the weapon registers in the mystery box pool."}


def invoke(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.entry(argv)
    return code, json.loads(out.getvalue())


class DeclaredParameters(unittest.TestCase):
    """``pat module inspect``: a declaration states its parameters, or is refused by the rule
    it broke, through the same path that refuses every other declaration error."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"PAT_HOME": str(self.root / "pat-home")})
        self.env.start()
        self.addCleanup(self.env.stop)

    def inspect(self, data):
        path = self.root / "module.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return invoke(["module", "inspect", str(path), "--json"])

    def declaration(self, **overrides):
        return {"schema": 1, "id": "rotation_example", "version": "1.0", "bases": ["b2"], "maps": ["zm_factory"],
                "recipe": "project.json", **overrides}

    def test_absent_adds_nothing_and_a_valid_field_is_echoed_normalized(self):
        code, row = self.inspect(self.declaration())
        self.assertEqual(code, 0, row)
        self.assertNotIn("parameters", row["result"]["metadata"])
        code, row = self.inspect(self.declaration(parameters=[CADENCE, MIN_WAIT, BOX]))
        self.assertEqual(code, 0, row)
        echoed = row["result"]["metadata"]["parameters"]
        self.assertEqual([p["name"] for p in echoed], ["cadence", "min_wait", "box"])
        self.assertEqual(echoed[0], {**CADENCE, "range": None})
        self.assertEqual(echoed[1], {**MIN_WAIT, "values": None})
        self.assertEqual(echoed[2], {**BOX, "values": None, "range": None})
        schema = json.loads((ROOT / "schemas/module-inspect-v1.schema.json").read_text())
        props = schema["$defs"]["moduleMetadata"]["properties"]["parameters"]
        self.assertEqual(props["items"]["properties"]["type"]["enum"], list(parameters.TYPES))
        self.assertEqual(props["maxItems"], parameters.MAX_PARAMETERS)

    def test_a_seed_payload_may_declare_them_too(self):
        code, row = self.inspect({"schema": 1, "id": "box_example", "version": "1.0", "bases": ["b2"], "maps": ["zm_factory"],
                                  "seed": "seed.json", "parameters": [BOX]})
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["metadata"]["parameters"][0]["default"], True)

    def test_defects_are_pointed_at(self):
        for value, field, phrase in (
            (CADENCE, "/parameters", "list of at most 32"),
            ([[CADENCE]], "/parameters/0", "is an object"),
            ([{**CADENCE, "unit": "seconds"}], "/parameters/0/unit", "unknown fields"),
            ([{k: v for k, v in CADENCE.items() if k != "meaning"}], "/parameters/0/meaning", "is missing"),
            ([{**CADENCE, "name": "Cadence"}], "/parameters/0/name", "lowercase letters"),
            ([{**CADENCE, "name": "c" * 33}], "/parameters/0/name", "lowercase letters"),
            ([CADENCE, {**CADENCE, "default": "timer"}], "/parameters/1/name", "twice"),
            ([{**CADENCE, "type": "float"}], "/parameters/0/type", "one of ['bool', 'int', 'string']"),
            ([{**MIN_WAIT, "values": [5, 10]}], "/parameters/0/range", "never both"),
            ([{**BOX, "values": [True, False]}], "/parameters/0/values", "a bool already has its two values"),
            ([{**CADENCE, "values": []}], "/parameters/0/values", "1 to 32 allowed values"),
            ([{**CADENCE, "values": ["round"] * 33}], "/parameters/0/values", "1 to 32 allowed values"),
            ([{**CADENCE, "values": ["round", 7]}], "/parameters/0/values/1", "is not a string"),
            ([{**CADENCE, "values": ["round", "round"]}], "/parameters/0/values", "repeats a value"),
            ([{**CADENCE, "values": None, "range": [1, 4]}], "/parameters/0/range", "belongs to an int parameter"),
            ([{**MIN_WAIT, "range": [5]}], "/parameters/0/range", "[min, max], two integers"),
            ([{**MIN_WAIT, "range": [5, True]}], "/parameters/0/range", "[min, max], two integers"),
            ([{**MIN_WAIT, "range": [600, 5]}], "/parameters/0/range", "min at most max"),
            ([{**CADENCE, "meaning": ""}], "/parameters/0/meaning", "at most 400 characters"),
            ([{**CADENCE, "meaning": "m" * 401}], "/parameters/0/meaning", "at most 400 characters"),
            ([{**MIN_WAIT, "default": 900}], "/parameters/0/default", "outside the declared range [5, 600]"),
            ([{**CADENCE, "default": "hourly"}], "/parameters/0/default", "not one of the declared values"),
            ([{**BOX, "default": 1}], "/parameters/0/default", "is not a bool"),
            ([{**MIN_WAIT, "default": True}], "/parameters/0/default", "is not an int"),
            ([{**CADENCE, "values": None, "default": "x" * 121}], "/parameters/0/default", "longer than 120 characters"),
        ):
            code, row = self.inspect(self.declaration(parameters=value))
            self.assertEqual(code, 1, row)
            self.assertEqual(row["error_code"], "input_invalid")
            diagnostic = row["details"]["inspection"]["diagnostics"][0]
            self.assertEqual(diagnostic["field"], field, value)
            self.assertIn(phrase, diagnostic["message"], value)

    def test_the_normalized_echo_re_validates(self):
        """The echo carries values and range with one of them null, so the rule that refuses two
        constraints is about two constraints, not two keys."""
        code, row = self.inspect(self.declaration(parameters=[CADENCE, MIN_WAIT, BOX]))
        self.assertEqual(code, 0, row)
        echoed = row["result"]["metadata"]["parameters"]
        code, again = self.inspect(self.declaration(parameters=echoed))
        self.assertEqual(code, 0, again)
        self.assertEqual(again["result"]["metadata"]["parameters"], echoed)

    def test_thirty_two_are_allowed_and_a_thirty_third_is_refused(self):
        rows = [{**BOX, "name": f"flag_{i}"} for i in range(parameters.MAX_PARAMETERS)]
        code, row = self.inspect(self.declaration(parameters=rows))
        self.assertEqual(code, 0, row)
        self.assertEqual(len(row["result"]["metadata"]["parameters"]), 32)
        code, row = self.inspect(self.declaration(parameters=rows + [{**BOX, "name": "flag_32"}]))
        self.assertEqual(code, 1, row)
        self.assertEqual(row["details"]["inspection"]["diagnostics"][0]["field"], "/parameters")


class EffectiveMap(unittest.TestCase):
    """The pure resolution: defaults filled, settings over them, one problem per broken rule."""

    def test_unset_takes_the_default_and_a_set_value_wins(self):
        values, problems = parameters.effective([CADENCE, MIN_WAIT, BOX], {"cadence": "timer"})
        self.assertEqual(values, {"cadence": "timer", "min_wait": 90, "box": True})
        self.assertEqual(problems, [])

    def test_a_module_that_declares_none_and_sets_none_has_an_empty_map(self):
        self.assertEqual(parameters.effective(None, None), ({}, []))

    def test_every_broken_rule_is_reported_and_configures_nothing(self):
        values, problems = parameters.effective(
            [CADENCE, MIN_WAIT, BOX], {"cadence": "hourly", "min_wait": 900, "box": "yes", "nope": 1})
        self.assertEqual(values, {"cadence": "round", "min_wait": 90, "box": True})
        by_name = dict(problems)
        self.assertIn("is not one of the declared values", by_name["cadence"])
        self.assertIn("outside the declared range [5, 600]", by_name["min_wait"])
        self.assertIn("is not a bool", by_name["box"])
        self.assertIn("is not declared by the module", by_name["nope"])
        self.assertIn("['box', 'cadence', 'min_wait']", by_name["nope"])
        self.assertEqual(parameters.effective(None, {"box": True})[1][0][1],
                         "is not declared by the module (it declares no parameters)")


class CompositionParameters(CompositionFixture):
    """A member sets them; the plan carries the effective map and refuses what is not declared."""

    def plan(self, comp, *extra):
        return job_invoke(["module", "plan", str(comp), "--output", self.out(), *extra])

    def rotation(self, mid="rotation", **overrides):
        return self.module(mid, parameters=[CADENCE, MIN_WAIT, BOX], **overrides)

    def test_a_set_value_reaches_the_plan_row_and_the_unset_ones_take_their_defaults(self):
        self.rotation()
        self.module("plain")
        comp = self.composition([{"path": "../../modules/rotation", "parameters": {"cadence": "timer", "min_wait": 30}},
                                 "plain"])
        code, row = self.plan(comp)
        self.assertEqual(code, 0, row)
        by_id = {m["id"]: m for m in row["result"]["modules"]}
        self.assertEqual(by_id["rotation"]["parameters"], {"cadence": "timer", "min_wait": 30, "box": True})
        self.assertEqual(by_id["plain"]["parameters"], {}, "a module that declares none carries an empty map")
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        rows = {r["id"]: r for r in plan["modules"]}
        self.assertEqual(rows["rotation"]["parameters"], {"cadence": "timer", "min_wait": 30, "box": True})
        self.assertEqual(rows["plain"]["parameters"], {})

    def test_a_member_that_sets_nothing_takes_every_default(self):
        self.rotation()
        code, row = self.plan(self.composition(["rotation"]))
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["modules"][0]["parameters"], {"cadence": "round", "min_wait": 90, "box": True})

    def test_an_undeclared_name_is_a_parameters_refusal(self):
        self.rotation()
        comp = self.composition([{"path": "../../modules/rotation", "parameters": {"pace": True}}])
        code, row = self.plan(comp)
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")
        refusal = row["details"]["refusals"][0]
        self.assertEqual(refusal["kind"], "parameters")
        self.assertEqual(refusal["modules"], ["rotation"])
        self.assertEqual(refusal["parameter"], "pace")
        self.assertEqual(refusal["field"], "/modules/0/parameters/pace")
        self.assertIn("rotation: parameter 'pace' is not declared by the module", refusal["message"])
        self.assertFalse((Path(row["receipt"]).parent / "plan.json").exists(), "refused before a plan was written")

    def test_a_value_outside_its_declared_constraint_is_a_parameters_refusal(self):
        self.rotation()
        for setting, phrase in (({"cadence": "hourly"}, "is not one of the declared values ['round', 'timer']"),
                                ({"min_wait": 900}, "is outside the declared range [5, 600]"),
                                ({"box": 1}, "is not a bool")):
            comp = self.composition([{"path": "../../modules/rotation", "parameters": setting}],
                                    name=f"stock_{list(setting)[0]}_test")
            code, row = self.plan(comp)
            self.assertEqual(code, 1, row)
            refusal = row["details"]["refusals"][0]
            self.assertEqual(refusal["kind"], "parameters")
            self.assertIn(phrase, refusal["message"])

    def test_every_broken_setting_is_refused_in_one_run(self):
        self.rotation()
        comp = self.composition([{"path": "../../modules/rotation", "parameters": {"cadence": "hourly", "nope": 1}}])
        code, row = self.plan(comp)
        self.assertEqual(code, 1, row)
        self.assertEqual([r["parameter"] for r in row["details"]["refusals"]], ["cadence", "nope"])

    def test_the_map_is_lexically_checked_in_the_composition_itself(self):
        self.rotation()
        for setting, phrase in ((["cadence"], "maps at most 32 declared parameter names"),
                                ({"Cadence": "timer"}, "a parameters name is lowercase"),
                                ({"cadence": [1]}, "is a bool, an int or a string"),
                                ({"cadence": "x" * 121}, "is a bool, an int or a string"),
                                ({f"p{i}": 1 for i in range(33)}, "maps at most 32 declared parameter names")):
            comp = self.composition([{"path": "../../modules/rotation", "parameters": setting}])
            code, row = self.plan(comp)
            self.assertEqual(code, 1, row)
            self.assertEqual(row["error_code"], "input_invalid")
            self.assertIn(phrase, row["message"])

    def test_a_nested_composition_takes_no_parameters(self):
        self.rotation()
        inner = self.composition(["rotation"], name="stock_inner_test")
        outer = self.composition([{"path": "../stock_inner_test", "parameters": {"cadence": "timer"}}],
                                 name="stock_outer_test")
        code, row = self.plan(outer)
        self.assertEqual(code, 1, row)
        self.assertIn("A nested composition takes no parameters", row["message"])
        self.assertEqual(row["details"]["field"], "/modules/0/parameters")
        self.assertTrue(inner.is_file())

    def test_a_nested_member_s_refusal_points_into_its_own_composition(self):
        # The outer pack lists another module first, so the inner member's flattened index is not
        # its index in the file that set the value; the pointer names that file and its own index.
        self.rotation()
        self.module("plain")
        inner = self.composition([{"path": "../../modules/rotation", "parameters": {"pace": 1}}], name="stock_inner_test")
        outer = self.composition(["plain", {"path": "../stock_inner_test"}], name="stock_outer_test")
        code, row = self.plan(outer)
        self.assertEqual(code, 1, row)
        refusal = next(r for r in row["details"]["refusals"] if r["kind"] == "parameters")
        self.assertEqual(refusal["field"], "/modules/0/parameters/pace")
        self.assertEqual(refusal["composition"], "stock_inner_test")
        self.assertTrue(inner.is_file())

    def test_module_inspect_echoes_what_a_member_sets(self):
        self.rotation()
        comp = self.composition([{"path": "../../modules/rotation", "parameters": {"cadence": "timer"}}, "../../modules/rotation"])
        code, row = invoke(["module", "inspect", str(comp), "--json"])
        self.assertEqual(code, 0, row)
        members = row["result"]["metadata"]["members"]
        self.assertEqual(members[0]["parameters"], {"cadence": "timer"})
        self.assertEqual(members[1]["parameters"], {}, "a member that sets none")
        schema = json.loads((ROOT / "schemas/module-inspect-v1.schema.json").read_text())
        member = schema["$defs"]["compositionMetadata"]["properties"]["members"]["items"]
        self.assertIn("parameters", member["required"])
        self.assertEqual(set(members[0]), set(member["required"]))

    def test_the_build_receipt_records_the_configuration_and_the_package_is_unchanged(self):
        self.rotation()
        packages = []
        for setting in ({"cadence": "round"}, {"cadence": "timer", "min_wait": 30}):
            comp = self.composition([{"path": "../../modules/rotation", "parameters": setting}], name="stock_rotation_test")
            code, row = job_invoke(["module", "build", str(comp), "--output", self.out()])
            self.assertEqual(code, 0, row)
            build = Path(row["result"]["output"])
            self.assertEqual(row["result"]["modules"][0]["parameters"], {"cadence": "round", "min_wait": 90, "box": True} | setting)
            receipt = json.loads((build / "receipt.json").read_text())
            self.assertEqual(receipt["result"]["modules"][0]["parameters"], row["result"]["modules"][0]["parameters"],
                             "the receipt on disk says which configuration the build is")
            packages.append((build / row["result"]["mod_ff"]).read_bytes())
        self.assertEqual(packages[0], packages[1],
                         "no consumer reads a parameter yet: the configuration is recorded, the package bytes are not touched")


if __name__ == "__main__":
    unittest.main()
