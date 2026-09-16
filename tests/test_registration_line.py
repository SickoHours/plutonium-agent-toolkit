"""The registration line: one console line per module, derived from the declaration.

Specified in docs/MODULES.md under "The registration line: one console line per module". The
declaration says who prints `<id> >> registered`; the plan derives `expected_lines` from that and
nothing else; the generated entry prints the line for an `entry` member; `test plan` checks each
promised line in the load phase and names the members that promise none. The `verify-declaration`
route the same section designs is not implemented here, so nothing below reads a module's source.
No line is observed in a game console by these tests: they check what the toolkit writes.
"""
import json
import unittest
from pathlib import Path

from plutonium_agent_toolkit.core.errors import Failure
from plutonium_agent_toolkit.dev.compositions import (REGISTRATION_KINDS, REGISTRATION_SUFFIX,
                                                      registration_line, validate_declaration_metadata)
from tests.test_compositions import CompositionFixture, declaration
from tests.test_dev_routes import invoke
from tests.test_testing_contracts import contract

ENTRY = {"replace": "scripts/zm/alpha::alpha_replace", "register": "scripts/zm/alpha::alpha_register"}


def meta(mid="alpha", **overrides):
    return validate_declaration_metadata(declaration(mid, **overrides))


class Shape(unittest.TestCase):
    """The line has one spelling, and it comes from one place."""

    def test_the_line_is_the_id_and_the_suffix(self):
        self.assertEqual(registration_line("alpha"), "alpha >> registered")
        self.assertEqual(registration_line("alpha"), "alpha" + REGISTRATION_SUFFIX)

    def test_the_vocabulary_is_the_three_words(self):
        self.assertEqual(REGISTRATION_KINDS, ("self", "entry", "none"))


class Declaration(unittest.TestCase):
    """`registration` is optional, takes three words, and `entry` needs something to print from."""

    def test_each_word_is_accepted(self):
        self.assertEqual(meta(registration="self")["registration"], "self")
        self.assertEqual(meta(registration="none")["registration"], "none")
        self.assertEqual(meta(registration="entry", entry=ENTRY)["registration"], "entry")

    def test_absent_is_none_and_says_nothing(self):
        self.assertIsNone(meta()["registration"])
        self.assertIsNone(meta(entry=ENTRY)["registration"])

    def test_an_unknown_word_is_refused_at_the_field(self):
        for value in ("both", "SELF", "", "yes", True, ["self"]):
            with self.subTest(value=value):
                with self.assertRaises(Failure) as cm:
                    meta(registration=value)
                self.assertEqual(cm.exception.details["field"], "/registration")
                self.assertIn("self, entry or none", str(cm.exception))

    def test_entry_without_an_entry_field_is_refused_at_the_field(self):
        with self.assertRaises(Failure) as cm:
            meta(registration="entry")
        self.assertEqual(cm.exception.details["field"], "/registration")
        self.assertIn("registration entry needs an entry field", str(cm.exception))
        self.assertIn("after calling entry.register", str(cm.exception))


class InspectEcho(CompositionFixture):
    """`module inspect` echoes `registration` only when the declaration names it."""

    def inspect(self, mid, **overrides):
        directory = self.module(mid, **overrides)
        code, row = invoke(["module", "inspect", str(directory / "module.json"), "--json"])
        self.assertEqual(code, 0, row)
        return row["result"]["metadata"]

    def test_a_named_registration_is_echoed(self):
        self.assertEqual(self.inspect("alpha", registration="self")["registration"], "self")
        self.assertEqual(self.inspect("beta", registration="none")["registration"], "none")

    def test_an_unnamed_registration_is_absent_from_the_metadata(self):
        self.assertNotIn("registration", self.inspect("alpha"))


class PlanExpectedLines(CompositionFixture):
    """The plan derives one row per member from the declaration, in plan order."""

    def pack(self):
        self.module("alpha", registration="self")
        self.module("beta", registration="none", dependencies=["alpha"])
        self.module("gamma", dependencies=["beta"])
        return self.composition(["gamma", "beta", "alpha"])

    def test_plan_json_carries_a_row_per_member_in_plan_order(self):
        comp = self.pack()
        out = self.out()
        code, row = invoke(["module", "plan", str(comp), "--output", out, "--json"])
        self.assertEqual(code, 0, row)
        plan = json.loads((Path(out) / "plan.json").read_text())
        self.assertEqual(plan["order"], ["alpha", "beta", "gamma"])
        self.assertEqual(plan["expected_lines"], [
            {"id": "alpha", "registration": "self", "line": "alpha >> registered"},
            {"id": "beta", "registration": "none", "line": None},
            {"id": "gamma", "registration": None, "line": None}])
        self.assertEqual([r["id"] for r in plan["expected_lines"]], plan["order"])
        self.assertEqual([r["registration"] for r in plan["modules"]], ["self", "none", None])

    def test_the_plan_summary_carries_the_same_rows(self):
        comp = self.pack()
        out = self.out()
        code, row = invoke(["module", "plan", str(comp), "--output", out, "--json"])
        self.assertEqual(code, 0, row)
        plan = json.loads((Path(out) / "plan.json").read_text())
        self.assertEqual(row["result"]["expected_lines"], plan["expected_lines"])

    def test_an_entry_member_gets_the_line_the_build_will_print(self):
        m = self.module("alpha", registration="entry", entry=ENTRY)
        (m / "scripts/alpha.gsc").write_text("alpha_replace() {}\nalpha_register() {}")
        out = self.out()
        code, row = invoke(["module", "plan", str(self.composition(["alpha"])), "--output", out, "--json"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["expected_lines"],
                         [{"id": "alpha", "registration": "entry", "line": "alpha >> registered"}])


class GeneratedEntryLine(CompositionFixture):
    """`module build` prints an `entry` member's line, right after the call that registers it."""

    def entry_member(self, mid, **overrides):
        m = self.module(mid, entry={"replace": f"scripts/zm/{mid}::{mid}_replace",
                                    "register": f"scripts/zm/{mid}::{mid}_register"}, **overrides)
        (m / f"scripts/{mid}.gsc").write_text(f"{mid}_replace() {{}}\n{mid}_register() {{}}")
        return m

    def entry_lines(self, comp):
        out = self.out()
        code, row = invoke(["module", "build", str(comp), "--output", out, "--json"])
        self.assertEqual(code, 0, row)
        source = Path(out) / "generated-entry/zz_stock_pack_test_entry.gsc"
        self.assertTrue(source.is_file())
        return source.read_text().splitlines()

    def test_the_println_follows_the_register_call(self):
        self.entry_member("alpha", registration="entry")
        lines = self.entry_lines(self.composition(["alpha"]))
        index = lines.index("    scripts\\zm\\alpha::alpha_register();")
        self.assertEqual(lines[index + 1], '    println("alpha >> registered");')
        # main() calls the replacement and prints nothing: the line means the registration ran.
        self.assertEqual(lines.count('    println("alpha >> registered");'), 1)
        self.assertNotIn('    println("alpha >> registered");',
                         lines[:lines.index("    scripts\\zm\\alpha::alpha_replace();") + 2])

    def test_a_member_without_registration_prints_nothing(self):
        self.entry_member("alpha")
        self.assertNotIn("println", "\n".join(self.entry_lines(self.composition(["alpha"]))))

    def test_self_and_none_are_the_modules_own_business(self):
        for value in ("self", "none"):
            with self.subTest(registration=value):
                self.entry_member("alpha", registration=value)
                self.assertNotIn("println", "\n".join(self.entry_lines(self.composition(["alpha"]))))

    def test_two_entry_members_print_in_dependency_order(self):
        self.entry_member("alpha", registration="entry")
        self.entry_member("beta", registration="entry", dependencies=["alpha"])
        text = "\n".join(self.entry_lines(self.composition(["beta", "alpha"])))
        self.assertLess(text.index("::alpha_register();"), text.index("::beta_register();"))
        self.assertLess(text.index('println("alpha >> registered");'),
                        text.index('println("beta >> registered");'))
        self.assertLess(text.index('println("alpha >> registered");'), text.index("::beta_register();"))


class TestPlanLoadPhase(CompositionFixture):
    """The load phase checks each promised line, and says which members promise none."""

    def member(self, mid, **overrides):
        m = self.module(mid, maps=["zm_transit"], tests="test-contract.json", **overrides)
        (m / "test-contract.json").write_text(json.dumps(contract(module=mid, maps={"zm_transit": {"preconditions": []}})))
        return m

    def stitched(self, comp):
        out = self.out()
        code, row = invoke(["test", "plan", "--composition", str(comp), "--output", out, "--json"])
        self.assertEqual(code, 0, row)
        return json.loads((Path(out) / "test-plan.json").read_text())

    def test_a_promised_line_becomes_a_load_step_and_a_silent_member_is_named(self):
        self.member("alpha", registration="self")
        self.member("beta", registration="none", dependencies=["alpha"])
        plan = self.stitched(self.composition(["beta", "alpha"]))
        load = plan["phases"][0]
        self.assertEqual(load["name"], "load")
        self.assertEqual([s["id"] for s in load["steps"]], ["load-clean", "registration/alpha"])
        step = load["steps"][1]
        self.assertEqual(step["actor"], "agent")
        self.assertEqual(step["verifier"], "agent")
        self.assertNotIn("action", step)
        self.assertEqual(step["check"], {"source": "log", "present": "^alpha >> registered"})
        # The error-absence check is unchanged and still first.
        self.assertEqual(load["steps"][0]["check"], {"source": "log", "absent": "script error|Unresolved external|out of space"})
        self.assertIn("beta prints no registration line", plan["not_covered"])
        self.assertNotIn("alpha prints no registration line", plan["not_covered"])

    def test_the_other_phases_keep_their_positions(self):
        self.member("alpha", registration="self")
        self.member("beta", registration="none", dependencies=["alpha"])
        plan = self.stitched(self.composition(["beta", "alpha"]))
        self.assertEqual([p["name"] for p in plan["phases"]], ["load", "members", "interactions", "soak"])
        self.assertEqual([s["id"] for s in plan["phases"][1]["steps"]], ["alpha/s1", "beta/s1"])

    def test_an_unnamed_registration_is_covered_by_nothing_and_says_so(self):
        self.member("alpha")
        plan = self.stitched(self.composition(["alpha"]))
        self.assertEqual([s["id"] for s in plan["phases"][0]["steps"]], ["load-clean"])
        self.assertIn("alpha prints no registration line", plan["not_covered"])

    def test_the_present_regex_matches_the_line_the_plan_expects(self):
        import re

        self.member("alpha", registration="self")
        plan = self.stitched(self.composition(["alpha"]))
        pattern = plan["phases"][0]["steps"][1]["check"]["present"]
        self.assertRegex(registration_line("alpha"), pattern)
        self.assertRegex(registration_line("alpha") + " v2", pattern)
        self.assertIsNone(re.search(pattern, "prefix " + registration_line("alpha")))
        self.assertIsNone(re.search(pattern, "alpha_hud >> registered"))


if __name__ == "__main__":
    unittest.main()
