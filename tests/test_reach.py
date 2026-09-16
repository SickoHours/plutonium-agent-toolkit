"""Whether a player can reach a feature, and whether they can see they have it: `reach` and `hud`.

Specified in docs/MODULES.md under "Whether a player can reach it: `reach` and `hud`". `reach` is
one word from a closed list saying how a player gets to the feature; `hud` says whether the player
can see they have it. Reachability is a fact about a composition on a map, so `module plan` derives
it per member and warns, never refuses. `module verify-declaration` reads the byte footprint per
word and proposes only what a byte alone decides.

Fixtures are synthetic modules built the way tests/test_compositions.py builds them, with the
location table shapes tests/test_targets.py already carries. Nothing here loads a game.
"""
import json
import unittest
from pathlib import Path

from plutonium_agent_toolkit.core.errors import Failure
from plutonium_agent_toolkit.dev import targets
from plutonium_agent_toolkit.dev.compositions import (HUD, PICKUP_SYSTEMS, REACH, reach_rows,
                                                      validate_declaration_metadata)
from tests.test_compositions import CompositionFixture, declaration
from tests.test_dev_routes import invoke
from tests.test_targets import table

# A weapon that registers itself into the map's availability tables and does nothing else: one
# footprint, which is what makes it proposable.
WALL_SOURCE = 'main()\n{\n    include_zombie_weapon("halo_rifle_zm", &"HALO_RIFLE");\n}\n'
# The two halves of a grant on spawn, both defined here so the module calls nothing it does not own.
SPAWN_SOURCE = ('main()\n{\n    level thread on_player_spawned();\n}\n\n'
                'on_player_spawned()\n{\n    self give_perk("halo_speed");\n}\n\n'
                'give_perk(name)\n{\n    wait 1;\n}\n')

MACHINE_NEED = {"needs": "perk-machine", "occupant": "specialty_armorvest", "fallback": "refuse"}


def meta(mid="alpha", **overrides):
    return validate_declaration_metadata(declaration(mid, **overrides))


def refusal(case, **overrides):
    try:
        validate_declaration_metadata(declaration("alpha", **overrides))
    except Failure as exc:
        return exc
    raise AssertionError(f"{case}: expected a refusal")


class Vocabulary(unittest.TestCase):
    """Three closed lists, and the words they hold."""

    def test_the_reach_words_are_the_six_routes_a_player_takes(self):
        self.assertEqual(REACH, ("wall-or-box", "machine", "granted", "drop", "passive", "menu"))

    def test_hud_is_the_icon_and_its_absence(self):
        self.assertEqual(HUD, ("icon", "none"))

    def test_the_pickup_systems_are_the_four_shelves_a_player_carries_from(self):
        self.assertEqual(PICKUP_SYSTEMS, ("perks", "gums", "powerups", "equipment"))


class Declaration(unittest.TestCase):
    """Both fields are optional, take one word each, and two reach words need a second field."""

    def test_every_reach_word_is_accepted(self):
        for word in REACH:
            with self.subTest(reach=word):
                extra = {"placements": [MACHINE_NEED]} if word == "machine" else {}
                self.assertEqual(meta(reach=word, **extra)["reach"], word)

    def test_every_hud_word_is_accepted(self):
        for word in HUD:
            with self.subTest(hud=word):
                self.assertEqual(meta(hud=word)["hud"], word)

    def test_absent_is_none_for_both(self):
        self.assertIsNone(meta()["reach"])
        self.assertIsNone(meta()["hud"])

    def test_an_unknown_reach_word_is_refused_at_the_field(self):
        for value in ("box", "Machine", "", "wall", True, ["drop"]):
            with self.subTest(value=value):
                exc = refusal(f"reach {value!r}", reach=value)
                self.assertEqual(exc.details["field"], "/reach")
                self.assertIn("reach is one of", exc.message)
                self.assertIn("wall-or-box", exc.message)

    def test_an_unknown_hud_word_is_refused_at_the_field(self):
        for value in ("shader", "Icon", "", True, ["icon"]):
            with self.subTest(value=value):
                exc = refusal(f"hud {value!r}", hud=value)
                self.assertEqual(exc.details["field"], "/hud")
                self.assertIn("hud is one of", exc.message)

    def test_a_passive_rule_that_prints_no_registration_line_is_refused(self):
        exc = refusal("passive with registration none", reach="passive", registration="none")
        self.assertEqual(exc.details["field"], "/reach")
        self.assertIn("a passive rule needs its registration line; nothing else shows it ran", exc.message)

    def test_a_passive_rule_that_says_who_prints_the_line_is_accepted(self):
        self.assertEqual(meta(reach="passive", registration="self")["reach"], "passive")
        self.assertEqual(meta(reach="passive")["reach"], "passive",
                         "a declaration that does not say is not a declaration that says none")

    def test_a_machine_with_no_placements_row_is_refused(self):
        exc = refusal("machine with no placements", reach="machine")
        self.assertEqual(exc.details["field"], "/reach")
        self.assertIn("a machine needs a placements row naming the site kind", exc.message)

    def test_a_machine_that_names_its_site_kind_is_accepted(self):
        self.assertEqual(meta(reach="machine", placements=[MACHINE_NEED])["reach"], "machine")


class InspectEcho(CompositionFixture):
    """`module inspect` echoes both fields only when the declaration names them."""

    def inspect(self, mid, **overrides):
        directory = self.module(mid, **overrides)
        code, row = invoke(["module", "inspect", str(directory / "module.json"), "--json"])
        self.assertEqual(code, 0, row)
        return row["result"]["metadata"]

    def test_named_fields_are_echoed(self):
        metadata = self.inspect("alpha", reach="drop", hud="icon")
        self.assertEqual((metadata["reach"], metadata["hud"]), ("drop", "icon"))

    def test_unnamed_fields_are_absent_from_the_metadata(self):
        metadata = self.inspect("alpha", system="perks")
        for key in ("reach", "hud"):
            self.assertNotIn(key, metadata)


class PlanFixture(CompositionFixture):
    def plan(self, comp, *extra, expect=0):
        out = self.out()
        code, row = invoke(["module", "plan", str(comp), "--output", out, "--json", *extra])
        self.assertEqual(code, expect, row)
        self.assertTrue(row["ok"], row)
        return row["result"], json.loads((Path(out) / "plan.json").read_text())

    def reach_warnings(self, plan):
        return [w["message"] for w in plan["warnings"] if ": reachable " in w["message"]]

    def hud_warnings(self, plan):
        return [w["message"] for w in plan["warnings"] if ": hud " in w["message"]]

    def row(self, plan, mid):
        return next(r for r in plan["modules"] if r["id"] == mid)


class PlanRows(PlanFixture):
    """Every plan row carries the two declared words and the two derived ones."""

    def test_plan_json_records_reach_and_hud_as_declared(self):
        self.module("alpha", reach="drop", hud="icon")
        self.module("beta")
        _summary, plan = self.plan(self.composition(["alpha", "beta"]))
        self.assertEqual((self.row(plan, "alpha")["reach"], self.row(plan, "alpha")["hud"]), ("drop", "icon"))
        self.assertIsNone(self.row(plan, "beta")["reach"])
        self.assertIsNone(self.row(plan, "beta")["hud"])

    def test_the_summary_row_carries_the_derived_pair_too(self):
        self.module("alpha", reach="drop")
        summary, plan = self.plan(self.composition(["alpha"]))
        self.assertEqual(summary["modules"][0]["reachable"], True)
        self.assertEqual(summary["modules"][0]["reason"], self.row(plan, "alpha")["reason"])


class Reachability(PlanFixture):
    """`reachable` is derived per member for this composition on this map, and never refuses."""

    def test_a_wall_or_box_member_is_reachable_with_no_warning(self):
        self.module("alpha", reach="wall-or-box")
        _summary, plan = self.plan(self.composition(["alpha"]))
        self.assertIs(self.row(plan, "alpha")["reachable"], True)
        self.assertIn("wall-or-box", self.row(plan, "alpha")["reason"])
        self.assertEqual(self.reach_warnings(plan), [])

    def test_drop_and_passive_are_the_declarations_own_promise(self):
        self.module("alpha", reach="drop")
        self.module("beta", reach="passive", registration="self")
        _summary, plan = self.plan(self.composition(["alpha", "beta"]))
        self.assertEqual([self.row(plan, m)["reachable"] for m in ("alpha", "beta")], [True, True])
        self.assertEqual(self.reach_warnings(plan), [])

    def test_a_menu_member_is_not_reachable_and_says_why(self):
        self.module("alpha", reach="menu", menu_route="Developer menu > Halo > Spawn")
        _summary, plan = self.plan(self.composition(["alpha"]))
        self.assertIs(self.row(plan, "alpha")["reachable"], False)
        self.assertEqual(self.row(plan, "alpha")["reason"], "developer menu only")
        self.assertEqual(self.reach_warnings(plan),
                         ["alpha: reachable false on zm_transit: developer menu only"])

    def test_a_member_that_does_not_say_is_unknown_and_warned(self):
        self.module("alpha")
        _summary, plan = self.plan(self.composition(["alpha"]))
        self.assertIsNone(self.row(plan, "alpha")["reachable"])
        self.assertEqual(self.reach_warnings(plan),
                         ["alpha: reachable unknown on zm_transit: the declaration does not say"])

    def test_a_grant_is_reachable_when_its_grantor_is_in_the_composition(self):
        self.module("grantor", provides={"perks": ["halo_speed"]})
        self.module("grantee", reach="granted", provides={"perks": ["halo_speed"]}, dependencies=["grantor"])
        _summary, plan = self.plan(self.composition(["grantee", "grantor"]))
        self.assertIs(self.row(plan, "grantee")["reachable"], True)
        self.assertEqual(self.row(plan, "grantee")["reason"],
                         "grantor is in the composition and provides halo_speed")
        self.assertEqual([m for m in self.reach_warnings(plan) if m.startswith("grantee:")], [],
                         "the grantor declares no reach of its own and is warned for that, not the grantee")

    def test_a_grant_with_nothing_to_grant_it_is_not_reachable(self):
        """No dependency at all: there is no candidate grantor for the reason to name."""
        self.module("grantee", reach="granted", provides={"perks": ["halo_speed"]})
        _summary, plan = self.plan(self.composition(["grantee"]))
        self.assertIs(self.row(plan, "grantee")["reachable"], False)
        self.assertEqual(self.row(plan, "grantee")["reason"],
                         "no member grants it and it does not grant itself on spawn")
        self.assertEqual(self.reach_warnings(plan),
                         ["grantee: reachable false on zm_transit: "
                          "no member grants it and it does not grant itself on spawn"])

    def test_a_dependency_that_is_here_and_hands_nothing_over_is_the_one_named(self):
        self.module("bystander")
        self.module("grantee", reach="granted", provides={"perks": ["halo_speed", "halo_jump"]},
                    dependencies=["bystander"])
        _summary, plan = self.plan(self.composition(["grantee", "bystander"]))
        self.assertIs(self.row(plan, "grantee")["reachable"], False)
        self.assertEqual(self.row(plan, "grantee")["reason"],
                         "bystander is in the composition but provides none of halo_jump, halo_speed")

    def test_a_dependency_that_is_not_here_is_named_instead(self):
        """Read through `reach_rows` directly: the planner refuses a missing dependency before a
        plan reaches this derivation, so the branch exists for every other caller of it."""
        grantee = {"id": "grantee", "reach": "granted", "dependencies": ["absent_grantor"],
                   "provides": {"perks": ["halo_speed"]}}
        self.assertEqual(reach_rows([grantee], [], {}),
                         {"grantee": (False, "absent_grantor is not in the composition")})

    def test_a_module_that_names_nothing_to_be_granted_has_no_candidate_to_name(self):
        grantor = {"id": "grantor", "reach": None, "dependencies": [], "provides": {"perks": ["halo_speed"]}}
        grantee = {"id": "grantee", "reach": "granted", "dependencies": ["grantor"], "provides": {}}
        self.assertEqual(reach_rows([grantee, grantor], [], {})["grantee"],
                         (False, "no member grants it and it does not grant itself on spawn"))

    def test_a_grant_the_module_performs_at_spawn_is_reachable_alone(self):
        directory = self.module("grantee", reach="granted", provides={"perks": ["halo_speed"]})
        (directory / "scripts" / "grantee.gsc").write_text(SPAWN_SOURCE)
        _summary, plan = self.plan(self.composition(["grantee"]))
        self.assertIs(self.row(plan, "grantee")["reachable"], True)
        self.assertEqual(self.row(plan, "grantee")["reason"], "the module gives it on player spawn")
        self.assertEqual(self.reach_warnings(plan), [])

    def test_a_commented_out_grant_at_spawn_is_not_a_grant(self):
        directory = self.module("grantee", reach="granted", provides={"perks": ["halo_speed"]})
        (directory / "scripts" / "grantee.gsc").write_text(
            "main()\n{\n    // on_player_spawned() self give_perk(\"halo_speed\");\n    wait 1;\n}\n")
        _summary, plan = self.plan(self.composition(["grantee"]))
        self.assertIs(self.row(plan, "grantee")["reachable"], False)


class MachineReachability(PlanFixture):
    """A machine is reachable when the composition's target has the site it needs."""

    def setUp(self):
        super().setUp()
        self.ws = self.root / "workspace"
        (self.ws / "foundations").mkdir(parents=True)
        (self.ws / "foundations" / "dlc5-beta2.json").write_text(json.dumps(
            {"schema": 1, "id": "dlc5-beta2", "profile_prefix": "b2", "maps": {"zm_factory": {}}}))
        path = self.ws / targets.table_relpath("dlc5-beta2/zm_factory/zclassic", "stock")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(table()), encoding="utf-8")

    def machine_pack(self, **overrides):
        self.module("jugg", bases=["b2"], maps=["zm_factory"], reach="machine",
                    placements=[MACHINE_NEED], **overrides)
        return self.composition(["jugg"], name="b2_machine_test", base="b2", map_id="zm_factory")

    def test_a_satisfied_placements_need_makes_the_machine_reachable(self):
        comp = self.machine_pack()
        _summary, plan = self.plan(comp, "--workspace", str(self.ws),
                                   "--target", "dlc5-beta2/zm_factory/zclassic")
        self.assertIs(self.row(plan, "jugg")["reachable"], True)
        self.assertIn("the site table has a row", self.row(plan, "jugg")["reason"])
        self.assertEqual(self.reach_warnings(plan), [])

    def test_without_a_target_the_site_table_was_not_read(self):
        _summary, plan = self.plan(self.machine_pack())
        self.assertIsNone(self.row(plan, "jugg")["reachable"])
        self.assertEqual(self.row(plan, "jugg")["reason"], "no --target, so the site table was not read")
        self.assertEqual(self.reach_warnings(plan),
                         ["jugg: reachable unknown on zm_factory: no --target, so the site table was not read"])


class HudWarning(PlanFixture):
    """A pickup a player cannot see is one they will report as broken."""

    def test_a_pickup_system_member_with_no_hud_is_warned(self):
        self.module("alpha", system="perks")
        _summary, plan = self.plan(self.composition(["alpha"]))
        self.assertEqual(self.hud_warnings(plan),
                         ["alpha: hud absent; a perks a player cannot see is one they will report as broken"])

    def test_hud_none_is_warned_with_the_word_it_declared(self):
        self.module("alpha", system="gums", hud="none")
        _summary, plan = self.plan(self.composition(["alpha"]))
        self.assertEqual(self.hud_warnings(plan),
                         ["alpha: hud none; a gums a player cannot see is one they will report as broken"])

    def test_hud_icon_is_not_warned(self):
        self.module("alpha", system="perks", hud="icon")
        _summary, plan = self.plan(self.composition(["alpha"]))
        self.assertEqual(self.hud_warnings(plan), [])

    def test_a_rule_with_no_pickup_is_not_asked_for_an_icon(self):
        self.module("alpha", system="perks", reach="passive", registration="self")
        _summary, plan = self.plan(self.composition(["alpha"]))
        self.assertEqual(self.hud_warnings(plan), [])

    def test_a_system_a_player_does_not_carry_is_not_asked_either(self):
        self.module("alpha", system="map")
        _summary, plan = self.plan(self.composition(["alpha"]))
        self.assertEqual(self.hud_warnings(plan), [])


class VerifyFixture(CompositionFixture):
    def verify(self, directory, *extra):
        code, row = invoke(["module", "verify-declaration", str(directory), "--json", *extra])
        self.assertEqual(code, 0, row)
        return row["result"]

    def one(self, result, field):
        found = [r for r in result["rows"] if r["field"] == field]
        self.assertEqual(len(found), 1, found)
        return found[0]

    def source_module(self, mid, script, **overrides):
        directory = self.module(mid, **overrides)
        (directory / "scripts" / f"{mid}.gsc").write_text(script)
        return directory


class VerifyReach(VerifyFixture):
    """The byte footprint per word: a signature is a footprint, never proof the path runs."""

    def test_a_declared_word_with_its_footprint_is_partial(self):
        directory = self.source_module("alpha", WALL_SOURCE, reach="wall-or-box")
        row = self.one(self.verify(directory), "/reach")
        self.assertEqual((row["declared"], row["observed"], row["outcome"]),
                         (["wall-or-box"], ["wall-or-box"], "partial"))
        self.assertEqual(row["note"], "the footprint is present; that the path runs is the load's proof")

    def test_a_declared_word_with_no_footprint_is_declared_not_observed(self):
        directory = self.source_module("alpha", 'main()\n{\n    wait 1;\n}\n', reach="drop")
        row = self.one(self.verify(directory), "/reach")
        self.assertEqual((row["declared"], row["observed"], row["outcome"]), (["drop"], [], "declared_not_observed"))

    def test_every_footprint_found_is_listed_when_nothing_is_declared(self):
        directory = self.source_module(
            "alpha", 'main()\n{\n    include_zombie_weapon("halo_rifle_zm");\n    setdvar("halo_rifle_ammo", 1);\n}\n')
        row = self.one(self.verify(directory), "/reach")
        self.assertEqual((row["declared"], row["observed"], row["outcome"]),
                         ([], ["passive", "wall-or-box"], "observed_not_declared"),
                         "a weapon is wall-or-box and passive at once")

    def test_nothing_declared_and_nothing_found_is_not_counted(self):
        row = self.one(self.verify(self.module("alpha")), "/reach")
        self.assertEqual((row["declared"], row["observed"], row["outcome"]), ([], [], "not_counted"))
        self.assertEqual(row["note"], "no reach footprint in this module's bytes")

    def test_a_machine_footprint_needs_the_placements_row_beside_it(self):
        script = 'main()\n{\n    level thread zombie_vending_init();\n}\n\nzombie_vending_init()\n{\n    wait 1;\n}\n'
        directory = self.source_module("alpha", script)
        self.assertEqual(self.one(self.verify(directory), "/reach")["observed"], [],
                         "a vending call with nothing placed reaches nobody")
        self.redeclare(directory, "alpha", placements=[MACHINE_NEED])
        self.assertEqual(self.one(self.verify(directory), "/reach")["observed"], ["machine"])

    def test_a_grant_on_spawn_and_a_powerup_registration_are_their_own_words(self):
        granted = self.source_module("alpha", SPAWN_SOURCE)
        self.assertEqual(self.one(self.verify(granted), "/reach")["observed"], ["granted"])
        drop = self.source_module("beta", 'main()\n{\n    add_zombie_powerup("halo_bonus");\n}\n')
        self.assertEqual(self.one(self.verify(drop), "/reach")["observed"], ["drop"])

    def test_a_developer_menu_route_counts_only_when_nothing_else_does(self):
        directory = self.source_module("alpha", 'main()\n{\n    wait 1;\n}\n',
                                       menu_route="Developer menu > Halo > Spawn")
        self.assertEqual(self.one(self.verify(directory), "/reach")["observed"], ["menu"])
        self.redeclare(directory, "alpha", menu_route="Developer menu > Halo > Spawn")
        (directory / "scripts" / "alpha.gsc").write_text(WALL_SOURCE)
        self.assertEqual(self.one(self.verify(directory), "/reach")["observed"], ["wall-or-box"])

    def redeclare(self, directory, mid, **overrides):
        (directory / "module.json").write_text(json.dumps(declaration(mid, **overrides), indent=2))
        return directory


class VerifyHud(VerifyFixture):
    """An icon is a byte: an image or material asset row, a shader precache or a stock icon name."""

    ICON_ASSET = {"source": "assets/halo_icon.iwi", "target": "images/halo_icon", "type": "image", "name": "halo_icon"}

    def icon_module(self, mid, **overrides):
        directory = self.module_with_assets(mid, [self.ICON_ASSET])
        (directory / "module.json").write_text(json.dumps(declaration(mid, **overrides), indent=2))
        return directory

    def test_a_declared_icon_with_its_byte_agrees(self):
        row = self.one(self.verify(self.icon_module("alpha", hud="icon")), "/hud")
        self.assertEqual((row["declared"], row["observed"], row["outcome"]), (["icon"], ["icon"], "agrees"))

    def test_a_declared_icon_with_no_byte_is_declared_not_observed(self):
        row = self.one(self.verify(self.module("alpha", hud="icon")), "/hud")
        self.assertEqual((row["declared"], row["observed"], row["outcome"]), (["icon"], [], "declared_not_observed"))

    def test_hud_none_beside_an_icon_byte_is_observed_not_declared(self):
        row = self.one(self.verify(self.icon_module("alpha", hud="none")), "/hud")
        self.assertEqual((row["declared"], row["observed"], row["outcome"]), (["none"], ["icon"], "observed_not_declared"))
        self.assertEqual(row["note"], "the module draws an icon and says it draws nothing")

    def test_hud_none_with_no_byte_agrees(self):
        row = self.one(self.verify(self.module("alpha", hud="none")), "/hud")
        self.assertEqual((row["declared"], row["observed"], row["outcome"]), (["none"], [], "agrees"))

    def test_an_undeclared_icon_byte_is_observed_not_declared(self):
        row = self.one(self.verify(self.icon_module("alpha")), "/hud")
        self.assertEqual((row["declared"], row["observed"], row["outcome"]), ([], ["icon"], "observed_not_declared"))

    def test_a_shader_precache_in_source_is_the_same_byte(self):
        directory = self.source_module("alpha", 'main()\n{\n    precacheShader("specialty_armorvest_zombies");\n}\n')
        self.assertEqual(self.one(self.verify(directory), "/hud")["observed"], ["icon"])

    def test_a_space_before_the_paren_is_still_a_precache(self):
        directory = self.source_module("alpha", 'main()\n{\n    PrecacheShader ("halo_icon");\n}\n')
        self.assertEqual(self.one(self.verify(directory), "/hud")["observed"], ["icon"])

    def test_a_rule_with_no_pickup_gets_no_hud_row_at_all(self):
        """`reach: passive` draws nothing by design: there is nothing for a player to carry, so
        there is nothing for them to see they have, and the route asks for no icon."""
        directory = self.module_with_assets("alpha", [self.ICON_ASSET])
        (directory / "module.json").write_text(json.dumps(
            declaration("alpha", reach="passive", registration="self", system="perks"), indent=2))
        result = self.verify(directory, "--propose")
        self.assertEqual([r for r in result["rows"] if r["field"] == "/hud"], [])
        self.assertNotIn("hud", result["proposal"], "and nothing is proposed for a field with no row")

    def test_a_pickup_system_with_no_byte_is_told_what_to_declare(self):
        row = self.one(self.verify(self.module("alpha", system="perks")), "/hud")
        self.assertEqual((row["declared"], row["observed"], row["outcome"]), ([], [], "not_counted"))
        self.assertEqual(row["note"], "no icon byte found; declare hud: none if it draws nothing")

    def test_a_module_off_the_pickup_shelves_is_simply_not_counted(self):
        row = self.one(self.verify(self.module("alpha", system="map")), "/hud")
        self.assertEqual(row["outcome"], "not_counted")
        self.assertEqual(row["note"], "no icon byte found")


class VerifyPropose(VerifyFixture):
    """`--propose` fills only what a byte alone decides."""

    def proposal(self, directory):
        return self.verify(directory, "--propose")["proposal"]

    def test_a_single_proposable_footprint_fills_reach(self):
        self.assertEqual(self.proposal(self.source_module("alpha", WALL_SOURCE)).get("reach"), "wall-or-box")

    def test_two_footprints_propose_neither(self):
        directory = self.source_module(
            "alpha", 'main()\n{\n    include_zombie_weapon("halo_rifle_zm");\n    setdvar("halo_rifle_ammo", 1);\n}\n')
        self.assertNotIn("reach", self.proposal(directory))

    def test_machine_granted_and_menu_are_never_proposed(self):
        machine = self.source_module("alpha", 'main()\n{\n    level thread zombie_vending_init();\n}\n\n'
                                              'zombie_vending_init()\n{\n    wait 1;\n}\n',
                                     placements=[MACHINE_NEED])
        self.assertNotIn("reach", self.proposal(machine))
        granted = self.source_module("beta", SPAWN_SOURCE)
        self.assertNotIn("reach", self.proposal(granted))
        menu = self.source_module("gamma", 'main()\n{\n    wait 1;\n}\n', menu_route="Developer menu > Halo")
        self.assertNotIn("reach", self.proposal(menu))

    def test_a_declared_reach_is_never_re_proposed(self):
        self.assertNotIn("reach", self.proposal(self.source_module("alpha", WALL_SOURCE, reach="drop")))

    def test_an_icon_byte_proposes_hud_icon_and_nothing_proposes_hud_none(self):
        icon = self.module_with_assets("alpha", [VerifyHud.ICON_ASSET])
        self.assertEqual(self.proposal(icon).get("hud"), "icon")
        self.assertNotIn("hud", self.proposal(self.module("beta", system="perks")),
                         "hud: none is never proposed; a module that draws nothing is the author's statement")


if __name__ == "__main__":
    unittest.main()
