"""What a module promises: file ownership, exclusive roles, services and dependency kinds.

The vocabulary and its validation only, as specified in docs/MODULES.md under "What a module
promises". The declaration reader accepts and checks the new fields, `module inspect` echoes them
when the declaration names them, and the service lookup prefers the typed mark over the older tag.
No refusal is added to the planner here: the plan tests below record that boundary.
"""
import json
import unittest
from pathlib import Path

from plutonium_agent_toolkit.core.errors import Failure
from plutonium_agent_toolkit.dev.compositions import (DEPENDENCY_KINDS, EXCLUSIVE_ROLES, MAX_WHY,
                                                      _service_for, shelf_services, validate_declaration_metadata)
from tests.test_compositions import CompositionFixture, declaration
from tests.test_dev_routes import invoke


def meta(mid="alpha", **overrides):
    return validate_declaration_metadata(declaration(mid, **overrides))


def refusal(case, **overrides):
    try:
        validate_declaration_metadata(declaration("alpha", **overrides))
    except Failure as exc:
        return exc
    raise AssertionError(f"{case}: expected a refusal")


class ReplacedFiles(unittest.TestCase):
    """`replaces.files` is a promise about a file the base or the map owns, not about a suffix."""

    def test_any_relative_zone_path_is_accepted(self):
        paths = ["animtrees/zm_example_basic.atr", "weapons/example_zm", "vision/example.vision",
                 "scripts/zm/zm_example.gsc"]
        self.assertEqual(meta(replaces={"functions": [], "files": paths})["replaces"]["files"], paths)

    def test_paths_are_lowercased_and_deduplicated(self):
        rows = ["Animtrees/Zm_Example.atr", "animtrees/zm_example.atr", "WEAPONS/Example_ZM"]
        self.assertEqual(meta(replaces={"functions": [], "files": rows})["replaces"]["files"],
                         ["animtrees/zm_example.atr", "weapons/example_zm"])

    def test_a_rooted_or_escaping_path_is_still_refused_at_its_pointer(self):
        for path in ("/rooted/zm_example.atr", "../outside/zm_example.atr", "D:/drive/zm_example.atr",
                     "back\\slash.atr"):
            with self.subTest(path=path):
                exc = refusal(path, replaces={"functions": [], "files": ["animtrees/ok.atr", path]})
                self.assertEqual(exc.details["field"], "/replaces/files/1")


class Exclusive(unittest.TestCase):
    """A role a pack has room for exactly one owner of."""

    def test_a_valid_list_is_normalized_and_absence_is_empty(self):
        self.assertEqual(meta(exclusive=["hud", "perk-art"])["exclusive"], ["hud", "perk-art"])
        self.assertEqual(meta(exclusive=list(EXCLUSIVE_ROLES))["exclusive"], list(EXCLUSIVE_ROLES))
        self.assertEqual(meta()["exclusive"], [])
        self.assertEqual(meta(exclusive=[])["exclusive"], [])

    def test_an_unknown_word_is_refused_at_its_index_and_the_message_names_the_roles(self):
        exc = refusal("unknown role", exclusive=["hud", "core-rules"])
        self.assertEqual(exc.details["field"], "/exclusive/1")
        for role in EXCLUSIVE_ROLES:
            self.assertIn(role, exc.message)
        self.assertEqual(refusal("not a string", exclusive=["hud", 7]).details["field"], "/exclusive/1")

    def test_a_duplicate_role_or_a_non_list_is_refused_on_the_field(self):
        self.assertEqual(refusal("duplicate", exclusive=["hud", "hud"]).details["field"], "/exclusive")
        self.assertEqual(refusal("not a list", exclusive="hud").details["field"], "/exclusive")


class Service(unittest.TestCase):
    """A module that exists to own shared things, so others depend on it and ship no copy."""

    def test_a_service_that_provides_something_shareable_is_accepted(self):
        for kind in ("rawfiles", "scripts", "soundbanks", "aliases"):
            with self.subTest(kind=kind):
                self.assertIs(meta(service=True, provides={kind: ["shared_thing"]})["service"], True)

    def test_a_service_that_only_owns_a_role_is_accepted(self):
        self.assertIs(meta(service=True, exclusive=["perk-art"])["service"], True)

    def test_a_service_with_nothing_shareable_is_refused(self):
        for provides in (None, {"perks": ["some_perk"]}, {"rawfiles": []}):
            with self.subTest(provides=provides):
                row = {} if provides is None else {"provides": provides}
                exc = refusal("nothing shareable", service=True, **row)
                self.assertEqual(exc.details["field"], "/service")
                self.assertIn("shareable", exc.message)

    def test_a_service_that_registers_its_own_weapon_is_refused(self):
        exc = refusal("weapon", service=True, provides={"rawfiles": ["shared.csv"], "weapons": ["example_zm"]})
        self.assertEqual(exc.details["field"], "/service")
        self.assertIn("no weapon of its own", exc.message)

    def test_service_must_be_a_json_boolean_and_absence_is_false(self):
        for value in ("true", 1, [], {}):
            with self.subTest(value=value):
                self.assertEqual(refusal("not a boolean", service=value).details["field"], "/service")
        self.assertIs(meta()["service"], False)
        self.assertIs(meta(service=False)["service"], False)
        self.assertIs(meta(service=False, provides={"weapons": ["example_zm"]})["service"], False)


class DependencyKinds(unittest.TestCase):
    """An entry is a module id, or an object saying what the edge is for."""

    def test_strings_and_objects_normalize_to_ids_in_order_with_a_kind_for_every_entry(self):
        row = meta(dependencies=["beta", {"id": "gamma", "kind": "call"},
                                 {"id": "delta", "kind": "runtime", "why": "reads level.pacing from that module's init"},
                                 {"id": "epsilon"}])
        self.assertEqual(row["dependencies"], ["beta", "gamma", "delta", "epsilon"])
        self.assertEqual(row["dependency_kinds"], {
            "beta": {"kind": None, "why": None},
            "gamma": {"kind": "call", "why": None},
            "delta": {"kind": "runtime", "why": "reads level.pacing from that module's init"},
            "epsilon": {"kind": None, "why": None}})
        self.assertEqual(meta()["dependency_kinds"], {})

    def test_every_declared_kind_is_accepted(self):
        for kind in DEPENDENCY_KINDS:
            with self.subTest(kind=kind):
                entry = {"id": "beta", "kind": kind}
                if kind == "runtime":
                    entry["why"] = "the engine's order of init is the whole relationship"
                self.assertEqual(meta(dependencies=[entry])["dependency_kinds"]["beta"]["kind"], kind)

    def test_an_unknown_kind_is_refused_at_its_pointer(self):
        exc = refusal("unknown kind", dependencies=["beta", {"id": "gamma", "kind": "imports"}])
        self.assertEqual(exc.details["field"], "/dependencies/1/kind")
        for kind in DEPENDENCY_KINDS:
            self.assertIn(kind, exc.message)

    def test_a_runtime_dependency_must_say_why(self):
        exc = refusal("runtime without why", dependencies=[{"id": "beta", "kind": "runtime"}])
        self.assertEqual(exc.details["field"], "/dependencies/0/why")
        self.assertIn("beta", exc.message)
        self.assertIn("nothing in the files can verify it", exc.message)

    def test_why_is_bounded(self):
        self.assertEqual(meta(dependencies=[{"id": "beta", "why": "x" * MAX_WHY}])["dependency_kinds"]["beta"]["why"],
                         "x" * MAX_WHY)
        exc = refusal("why too long", dependencies=[{"id": "beta", "why": "x" * (MAX_WHY + 1)}])
        self.assertEqual(exc.details["field"], "/dependencies/0/why")

    def test_a_duplicate_id_across_a_string_and_an_object_is_refused(self):
        exc = refusal("duplicate", dependencies=["beta", {"id": "beta", "kind": "call"}])
        self.assertEqual(exc.details["field"], "/dependencies")
        self.assertIn("duplicate", exc.message)

    def test_an_unknown_object_key_is_refused_with_its_pointer(self):
        exc = refusal("unknown key", dependencies=[{"id": "beta", "reason": "because"}])
        self.assertEqual(exc.details["field"], "/dependencies/0/reason")

    def test_a_missing_id_and_a_self_dependency_in_object_form_are_refused(self):
        self.assertEqual(refusal("no id", dependencies=[{"kind": "call"}]).details["field"], "/dependencies/0/id")
        exc = refusal("self", dependencies=[{"id": "alpha", "kind": "call"}])
        self.assertEqual(exc.details["field"], "/dependencies/0/id")
        self.assertIn("cannot list itself", exc.message)
        self.assertEqual(refusal("bad id", dependencies=[{"id": "BAD"}]).details["field"], "/dependencies/0/id")


class InspectEcho(CompositionFixture):
    """`module inspect` echoes the new fields only when the declaration names them."""

    def inspect(self, mid, **overrides):
        directory = self.module(mid, **overrides)
        code, row = invoke(["module", "inspect", str(directory / "module.json"), "--json"])
        self.assertEqual(code, 0, row)
        return row["result"]["metadata"]

    def test_a_declaration_naming_the_three_fields_echoes_them(self):
        metadata = self.inspect("alpha", exclusive=["hud"], service=True,
                                provides={"rawfiles": ["shared/table.csv"]},
                                dependencies=[{"id": "beta", "kind": "service", "why": "the shared table is beta's"}])
        self.assertEqual(metadata["exclusive"], ["hud"])
        self.assertIs(metadata["service"], True)
        self.assertEqual(metadata["dependencies"], ["beta"])
        self.assertEqual(metadata["dependency_kinds"],
                         {"beta": {"kind": "service", "why": "the shared table is beta's"}})

    def test_a_declaration_without_them_carries_none_of_the_keys(self):
        metadata = self.inspect("alpha")
        for key in ("exclusive", "service", "dependency_kinds"):
            self.assertNotIn(key, metadata)

    def test_dependency_kinds_is_echoed_only_when_an_object_entry_exists(self):
        plain = self.inspect("alpha", dependencies=["beta", "gamma"])
        self.assertEqual(plain["dependencies"], ["beta", "gamma"])
        self.assertNotIn("dependency_kinds", plain)
        mixed = self.inspect("delta", dependencies=["beta", {"id": "gamma"}])
        self.assertEqual(mixed["dependency_kinds"],
                         {"beta": {"kind": None, "why": None}, "gamma": {"kind": None, "why": None}})

    def test_service_false_is_echoed_when_the_declaration_says_so(self):
        self.assertIs(self.inspect("alpha", service=False)["service"], False)


class PlanCarriesThePromises(CompositionFixture):
    """The planner reads the same declarations and records the new fields. No refusal is added
    here: two owners of one role still plan, which is the boundary the next change moves."""

    def plan(self, comp):
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        return code, row

    def test_an_object_dependency_orders_the_plan_exactly_as_a_string_would(self):
        for entry in ("alpha", {"id": "alpha", "kind": "call"}):
            with self.subTest(entry=entry):
                self.module("alpha")
                self.module("beta", dependencies=[entry])
                code, row = self.plan(self.composition(["beta", "alpha"], name="stock_order_test"))
                self.assertEqual(code, 0, row)
                self.assertEqual([m["id"] for m in row["result"]["modules"]], ["alpha", "beta"])

    def test_plan_json_records_the_new_fields(self):
        self.module("alpha", service=True, exclusive=["hud"],
                    dependencies=[{"id": "beta", "kind": "name"}])
        self.module("beta")
        code, row = self.plan(self.composition(["alpha", "beta"]))
        self.assertEqual(code, 0, row)
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        rows = {m["id"]: m for m in plan["modules"]}
        self.assertEqual(rows["alpha"]["exclusive"], ["hud"])
        self.assertIs(rows["alpha"]["service"], True)
        self.assertEqual(rows["alpha"]["dependency_kinds"], {"beta": {"kind": "name", "why": None}})
        self.assertEqual(rows["beta"]["exclusive"], [])
        self.assertIs(rows["beta"]["service"], False)
        self.assertEqual(rows["beta"]["dependency_kinds"], {})

    def test_a_service_owning_a_role_plans_alone(self):
        self.module("alpha", service=True, exclusive=["hud"])
        code, row = self.plan(self.composition(["alpha"]))
        self.assertEqual(code, 0, row)
        self.assertTrue(row["ok"], row)

    def test_two_owners_of_one_role_still_plan_in_this_release(self):
        self.module("alpha", exclusive=["hud"])
        self.module("beta", exclusive=["hud"])
        code, row = self.plan(self.composition(["alpha", "beta"], name="stock_two_hud_test"))
        self.assertEqual(code, 0, row)
        self.assertTrue(row["ok"], "the exclusive refusal is the planner's half, not this one's")


class ServiceLookup(CompositionFixture):
    """The typed mark wins over the legacy tag when both own the same thing."""

    def test_the_declared_service_is_chosen_over_a_shared_service_tag(self):
        shared = "shared/zm_example_table.csv"
        self.module("alpha_tagged", tags=["shared-service"], provides={"rawfiles": [shared]})
        self.module("zeta_service", service=True, provides={"rawfiles": [shared]})
        rows = shelf_services(str(self.root))
        self.assertEqual({r["id"] for r in rows}, {"alpha_tagged", "zeta_service"})
        self.assertEqual(_service_for(rows, "rawfiles", shared)["id"], "zeta_service",
                         "the typed field wins; the tag is read for one more release")
        self.assertIsNone(_service_for(rows, "rawfiles", "nobody/owns_this.csv"))

    def test_the_tag_still_wins_when_no_candidate_declares_the_field(self):
        shared = "shared/zm_other_table.csv"
        self.module("alpha_plain", provides={"rawfiles": [shared]})
        self.module("zeta_tagged", tags=["shared-service"], provides={"rawfiles": [shared]})
        rows = shelf_services(str(self.root))
        self.assertEqual(_service_for(rows, "rawfiles", shared)["id"], "zeta_tagged")


if __name__ == "__main__":
    unittest.main()
