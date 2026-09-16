"""Where a person finds a module, and whether its port works yet: `system` and `port_status`.

Specified in docs/MODULES.md under "Where a person finds it, and whether it works yet". `system`
is a shelf word the planner never reads; `port_status` is the author's verdict on the port, and a
member whose verdict is not `finished` is refused unless the composition's member object names
that status under `accept`. Nothing here reads a module's source or loads anything: the checker
cannot see either field in bytes, which is the point of both.
"""
import json
import unittest
from pathlib import Path

from plutonium_agent_toolkit.core.errors import Failure
from plutonium_agent_toolkit.dev.compositions import (PORT_STATUSES, REFUSAL_KINDS, SYSTEMS,
                                                      validate_declaration_metadata)
from tests.test_compositions import CompositionFixture, declaration
from tests.test_dev_routes import invoke

UNFINISHED = tuple(status for status in PORT_STATUSES if status != "finished")


def meta(mid="alpha", **overrides):
    return validate_declaration_metadata(declaration(mid, **overrides))


def refusal(case, **overrides):
    try:
        validate_declaration_metadata(declaration("alpha", **overrides))
    except Failure as exc:
        return exc
    raise AssertionError(f"{case}: expected a refusal")


class Vocabulary(unittest.TestCase):
    """Two closed lists, and the words they hold."""

    def test_the_systems_are_the_twelve_shelves(self):
        self.assertEqual(SYSTEMS, ("pack-a-punch", "perks", "hud", "weapons", "powerups", "box",
                                   "core-rules", "gums", "bosses", "equipment", "audio", "map"))

    def test_the_port_statuses_are_the_three_verdicts(self):
        self.assertEqual(PORT_STATUSES, ("finished", "loads-but-wrong", "not-ported"))

    def test_port_status_is_a_refusal_kind(self):
        self.assertIn("port_status", REFUSAL_KINDS)


class System(unittest.TestCase):
    """`system` is optional, takes one word from the list, and says nothing when absent."""

    def test_every_system_word_is_accepted(self):
        for word in SYSTEMS:
            with self.subTest(system=word):
                self.assertEqual(meta(system=word)["system"], word)

    def test_absent_is_none(self):
        self.assertIsNone(meta()["system"])

    def test_an_unknown_word_is_refused_at_the_field(self):
        for value in ("gobblegums", "Perks", "", "scripts", True, ["perks"]):
            with self.subTest(value=value):
                exc = refusal(f"system {value!r}", system=value)
                self.assertEqual(exc.details["field"], "/system")
                self.assertIn("system is one of", exc.message)
                self.assertIn("pack-a-punch", exc.message)


class PortStatus(unittest.TestCase):
    """`port_status` is optional, takes three words, and absent means the port is finished."""

    def test_every_status_is_accepted(self):
        for status in PORT_STATUSES:
            with self.subTest(port_status=status):
                self.assertEqual(meta(port_status=status)["port_status"], status)

    def test_absent_is_finished(self):
        self.assertEqual(meta()["port_status"], "finished",
                         "the fact every declaration written before this field already states")

    def test_an_unknown_word_is_refused_at_the_field(self):
        for value in ("broken", "Finished", "", "wip", False, ["finished"]):
            with self.subTest(value=value):
                exc = refusal(f"port_status {value!r}", port_status=value)
                self.assertEqual(exc.details["field"], "/port_status")
                self.assertIn("port_status is one of", exc.message)


class InspectEcho(CompositionFixture):
    """`module inspect` echoes both fields only when the declaration names them."""

    def inspect(self, mid, **overrides):
        directory = self.module(mid, **overrides)
        code, row = invoke(["module", "inspect", str(directory / "module.json"), "--json"])
        self.assertEqual(code, 0, row)
        return row["result"]["metadata"]

    def test_named_fields_are_echoed(self):
        metadata = self.inspect("alpha", system="perks", port_status="loads-but-wrong")
        self.assertEqual(metadata["system"], "perks")
        self.assertEqual(metadata["port_status"], "loads-but-wrong")

    def test_unnamed_fields_are_absent_from_the_metadata(self):
        metadata = self.inspect("alpha")
        for key in ("system", "port_status"):
            self.assertNotIn(key, metadata)

    def test_a_named_finished_is_echoed_and_the_default_is_not(self):
        self.assertEqual(self.inspect("alpha", port_status="finished")["port_status"], "finished")
        self.assertNotIn("port_status", self.inspect("beta", system="hud"))


class PlanRows(CompositionFixture):
    """Every plan row carries both facts, defaults included."""

    def test_plan_json_records_the_system_and_the_port_status(self):
        self.module("alpha", system="perks")
        self.module("beta", system="weapons", port_status="loads-but-wrong")
        comp = self.composition(["alpha", {"path": "../../modules/beta", "accept": ["loads-but-wrong"]}])
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        rows = {m["id"]: m for m in plan["modules"]}
        self.assertEqual(rows["alpha"]["system"], "perks")
        self.assertEqual(rows["alpha"]["port_status"], "finished")
        self.assertEqual(rows["beta"]["system"], "weapons")
        self.assertEqual(rows["beta"]["port_status"], "loads-but-wrong")

    def test_a_row_for_a_declaration_naming_neither_carries_the_defaults(self):
        self.module("alpha")
        code, row = invoke(["module", "plan", str(self.composition(["alpha"])), "--output", self.out()])
        self.assertEqual(code, 0, row)
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        self.assertIsNone(plan["modules"][0]["system"])
        self.assertEqual(plan["modules"][0]["port_status"], "finished")


class CompositionEcho(CompositionFixture):
    """`module inspect` of a composition carries each member's `accept`, empty when it names none."""

    def test_a_members_accept_is_echoed_and_defaults_to_empty(self):
        self.module("alpha", port_status="loads-but-wrong")
        self.module("beta")
        comp = self.composition([{"path": "../../modules/alpha", "accept": ["loads-but-wrong"]}, "beta"])
        code, row = invoke(["module", "inspect", str(comp), "--json"])
        self.assertEqual(code, 0, row)
        self.assertEqual([m["accept"] for m in row["result"]["metadata"]["members"]], [["loads-but-wrong"], []])


class PortStatusRefusal(CompositionFixture):
    """An unfinished port is composed knowingly or not at all."""

    def plan(self, comp):
        return invoke(["module", "plan", str(comp), "--output", self.out()])

    def test_an_unfinished_member_is_refused_with_its_status_and_pointer(self):
        for status in UNFINISHED:
            with self.subTest(port_status=status):
                self.module("alpha", port_status=status)
                code, row = self.plan(self.composition(["alpha"]))
                self.assertEqual(code, 1, row)
                refusals = [r for r in row["details"]["refusals"] if r["kind"] == "port_status"]
                self.assertEqual(len(refusals), 1, row["details"]["refusals"])
                self.assertEqual(refusals[0]["modules"], ["alpha"])
                self.assertEqual(refusals[0]["status"], status)
                self.assertEqual(refusals[0]["field"], "/modules/0")
                self.assertIn(f"alpha is {status} and this composition does not accept it", refusals[0]["message"])
                self.assertIn(f'"accept": ["{status}"]', refusals[0]["hint"])

    def test_it_is_collected_beside_another_refusal_in_one_run(self):
        self.module("alpha", port_status="loads-but-wrong")
        self.module("beta", dependencies=["gamma"])
        code, row = self.plan(self.composition(["alpha", "beta"], name="stock_both_test"))
        self.assertEqual(code, 1, row)
        kinds = {r["kind"] for r in row["details"]["refusals"]}
        self.assertEqual(kinds, {"port_status", "missing_dependency"}, row["details"]["refusals"])

    def test_the_named_status_plans(self):
        for status in UNFINISHED:
            with self.subTest(port_status=status):
                self.module("alpha", port_status=status)
                comp = self.composition([{"path": "../../modules/alpha", "accept": [status]}])
                code, row = self.plan(comp)
                self.assertEqual(code, 0, row)
                self.assertTrue(row["ok"], row)

    def test_another_status_than_the_members_own_does_not_accept_it(self):
        self.module("alpha", port_status="not-ported")
        comp = self.composition([{"path": "../../modules/alpha", "accept": ["loads-but-wrong"]}])
        code, row = self.plan(comp)
        self.assertEqual(code, 1, row)
        refusal_row = next(r for r in row["details"]["refusals"] if r["kind"] == "port_status")
        self.assertEqual(refusal_row["status"], "not-ported")

    def test_a_dependency_brought_along_is_refused_the_same_way(self):
        self.module("alpha", dependencies=["beta"])
        self.module("beta", port_status="not-ported")
        code, row = self.plan(self.composition(["alpha", "beta"], name="stock_dependency_test"))
        self.assertEqual(code, 1, row)
        refusals = [r for r in row["details"]["refusals"] if r["kind"] == "port_status"]
        self.assertEqual([r["modules"] for r in refusals], [["beta"]])
        self.assertEqual(refusals[0]["field"], "/modules/1")

    def test_accept_on_a_finished_member_is_harmless(self):
        self.module("alpha")
        comp = self.composition([{"path": "../../modules/alpha", "accept": ["loads-but-wrong"]}])
        code, row = self.plan(comp)
        self.assertEqual(code, 0, row)
        self.assertTrue(row["ok"], row)

    def test_accept_finished_is_refused_at_the_member_field(self):
        self.module("alpha")
        for value in (["finished"], [], "loads-but-wrong", ["loads-but-wrong", "loads-but-wrong"],
                      ["loads-but-wrong", "not-ported", "finished"], ["unknown"]):
            with self.subTest(accept=value):
                comp = self.composition([{"path": "../../modules/alpha", "accept": value}])
                code, row = self.plan(comp)
                self.assertEqual(code, 1, row)
                self.assertEqual(row["error_code"], "input_invalid", row)
                self.assertEqual(row["details"]["field"], "/modules/0/accept")

    def test_both_unfinished_statuses_can_be_accepted_at_once(self):
        self.module("alpha", port_status="not-ported")
        comp = self.composition([{"path": "../../modules/alpha", "accept": list(UNFINISHED)}])
        code, row = self.plan(comp)
        self.assertEqual(code, 0, row)


class NestedAccept(CompositionFixture):
    """A nested pack carries the `accept` its own composition.json wrote, and only that one."""

    def nested(self, inner_members, outer_member):
        inner = self.composition(inner_members, name="stock_inner_pack")
        outer = self.root / "packs" / "stock_outer_test"
        outer.mkdir(parents=True, exist_ok=True)
        path = outer / "composition.json"
        path.write_text(json.dumps({"schema": 1, "name": "stock_outer_test", "base": "stock", "map": "zm_transit",
                                    "modules": [outer_member]}, indent=2))
        self.assertTrue(inner.is_file())
        return path

    def test_a_nested_member_accepts_its_own_unfinished_module(self):
        self.module("delta", port_status="loads-but-wrong")
        comp = self.nested([{"path": "../../modules/delta", "accept": ["loads-but-wrong"]}], "../stock_inner_pack")
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 0, row)
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        self.assertEqual(plan["modules"][0]["port_status"], "loads-but-wrong")

    def test_an_outer_accept_does_not_reach_into_the_nested_pack(self):
        self.module("epsilon", port_status="not-ported")
        comp = self.nested(["epsilon"], {"path": "../stock_inner_pack", "accept": ["not-ported"]})
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 1, row)
        refusal_row = next(r for r in row["details"]["refusals"] if r["kind"] == "port_status")
        self.assertEqual(refusal_row["modules"], ["epsilon"])
        self.assertEqual(refusal_row["status"], "not-ported")
        self.assertEqual(refusal_row["field"], "/modules/0",
                         "the pointer is into the composition.json that listed the member")
