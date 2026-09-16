"""Stock content: a declaration for what the game already ships, and the ledger row that says so.

``distribution: stock`` is a declaration with no bytes to build -- no recipe, no seed, no package
-- because its payload is the base itself. It is on the shelf so a map's baseline stands beside
what can be added to it. The planner never builds, stages or counts one, but what it provides is
still what the map already has, so a box registration naming a stock weapon passes. The ledger's
``shipped`` row is the provenance half: it states that the game ships this on these maps and it
feeds none of the six facts, because shipping with the game is not offline verification.

Specified in docs/MODULES.md ("Stock content") and docs/evidence-ledger.md. Every fixture here is
synthetic: no game, no package, no real map.
"""
import contextlib
import io
import json
import unittest
from pathlib import Path

from plutonium_agent_toolkit import cli
from plutonium_agent_toolkit.core.errors import Failure
from plutonium_agent_toolkit.dev import compositions as c
from plutonium_agent_toolkit.dev import ledger
from tests.test_compositions import CompositionFixture, declaration
from tests.test_dev_routes import invoke

SCOPE = {"base": "stock", "foundation": "bo2-stock", "maps": ["zm_transit"]}
SHIPPED = {"type": "shipped", "scope": SCOPE,
           "record": {"path": "knowledge/decompiled/stock/maps/mp/zombies/_zm_perks.gsc", "sha256": "a" * 64},
           "citations": [{"file": "bo2-stock/zm_transit/maps/mp/zm_transit.gsc", "line": 90, "sha256": "b" * 64,
                          "text": "level.zombiemode_using_juggernaut_perk = 1;"}],
           "note": "Shipped with the game on these maps. Not built, not installed, not played here."}
CITATION = {"file": "bo2-stock/zm_transit/maps/mp/zm_transit.gsc", "line": 90, "sha256": "b" * 64,
            "text": "level.zombiemode_using_juggernaut_perk = 1;"}
VANILLA = {"zm_transit": {"present": True, "cost": {"value": 2500, "file": "maps/mp/zombies/_zm_perks.gsc", "line": 1698},
                          "entity_sites": [{"kind": "machine", "key": "targetname", "value": "vending_jugg"}],
                          "count": "unknown", "count_note": "The scripts iterate getentarray and state no count.",
                          "rotation": None}}


def stock_declaration(mid="vanilla_perks_juggernog", **overrides):
    """A stock declaration: no payload at all, and an origin that says whose content it is."""
    row = declaration(mid, **overrides)
    row.pop("recipe", None)
    row.pop("resource_contract", None)
    row.setdefault("distribution", "stock")
    row.setdefault("origin", "vanilla")
    row.setdefault("category", "perks")
    row.update(overrides)
    return row


def inspect_declaration(path):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = cli.entry(["module", "inspect", str(path), "--json"])
    return code, json.loads(output.getvalue())


class StockDeclaration(unittest.TestCase):
    """What a declaration with no bytes may say, and what it may not."""

    def test_stock_is_a_distribution(self):
        self.assertEqual(c.DISTRIBUTIONS, ("source", "seed", "private", "stock"))

    def test_a_stock_declaration_validates_with_no_payload(self):
        metadata = c.validate_declaration_metadata(stock_declaration())
        self.assertEqual(metadata["distribution"], "stock")
        self.assertEqual(metadata["payload"], "stock")
        self.assertIsNone(metadata["payload_path"])
        self.assertEqual(metadata["origin"], "vanilla")

    def test_the_payload_rule_is_relaxed_before_the_distribution_check_not_only_the_enum(self):
        """A stock declaration names no payload, so the refusal that fires first must be gone."""
        plain = dict(stock_declaration(), distribution="source")
        with self.assertRaises(Failure) as caught:
            c.validate_declaration_metadata(plain)
        self.assertEqual(caught.exception.details["field"], "/recipe")
        self.assertIn("exactly one payload", caught.exception.message)

    def test_a_recipe_a_seed_or_recipes_is_refused_on_a_stock_declaration(self):
        for field, value in (("recipe", "project.json"), ("seed", "seed.json"),
                             ("recipes", {"bo2-stock/zm_transit": "recipe-stock.json"})):
            with self.subTest(field=field):
                with self.assertRaises(Failure) as caught:
                    c.validate_declaration_metadata(stock_declaration(**{field: value}))
                self.assertEqual(caught.exception.code, "input_invalid")
                self.assertEqual(caught.exception.details["field"], "/" + field)

    def test_stock_content_origin_is_vanilla(self):
        for origin in ("bo3", "unverified", "saints-row"):
            with self.subTest(origin=origin):
                with self.assertRaises(Failure) as caught:
                    c.validate_declaration_metadata(stock_declaration(origin=origin))
                self.assertEqual(caught.exception.code, "input_invalid")
                self.assertEqual(caught.exception.details["field"], "/origin")
                self.assertIn("stock content's origin is 'vanilla'", caught.exception.message)

    def test_a_stock_declaration_without_an_origin_is_refused(self):
        row = stock_declaration()
        row.pop("origin")
        with self.assertRaises(Failure) as caught:
            c.validate_declaration_metadata(row)
        self.assertEqual(caught.exception.details["field"], "/origin")

    def test_donor_stays_optional(self):
        self.assertIsNone(c.validate_declaration_metadata(stock_declaration())["donor"])
        credit = "Treyarch, Black Ops II Zombies"
        self.assertEqual(c.validate_declaration_metadata(stock_declaration(donor=credit))["donor"], credit)

    def test_provides_may_be_empty_or_absent(self):
        row = stock_declaration()
        row.pop("provides", None)
        self.assertEqual(c.validate_declaration_metadata(row)["provides"], {})
        self.assertEqual(c.validate_declaration_metadata(stock_declaration(provides={}))["provides"], {})


class VanillaBlock(unittest.TestCase):
    """``vanilla`` carries what the stock scripts show per map. Bounded, never interpreted."""

    def test_a_stock_declaration_carries_it_and_inspection_echoes_it(self):
        metadata = c.validate_declaration_metadata(stock_declaration(vanilla=VANILLA))
        self.assertEqual(metadata["vanilla"], VANILLA)

    def test_a_non_stock_declaration_carrying_it_is_refused(self):
        with self.assertRaises(Failure) as caught:
            c.validate_declaration_metadata(declaration("alpha", vanilla=VANILLA))
        self.assertEqual(caught.exception.code, "input_invalid")
        self.assertEqual(caught.exception.details["field"], "/vanilla")
        self.assertIn("stock", caught.exception.message)

    def test_absent_is_absent(self):
        self.assertIsNone(c.validate_declaration_metadata(stock_declaration())["vanilla"])

    def test_it_is_an_object_of_lowercase_keys(self):
        for value in ([], "zm_transit", 4, {"ZM_Transit": {}}, {"": {}}, {"has space": {}}, {"a" * 65: {}},
                      {"zm_transit": {"Cost": 1}}):
            with self.subTest(value=value):
                with self.assertRaises(Failure) as caught:
                    c.validate_declaration_metadata(stock_declaration(vanilla=value))
                self.assertEqual(caught.exception.details["field"], "/vanilla")

    def test_leaf_values_are_json_scalars_lists_or_objects(self):
        for leaf in (True, False, None, 0, 2500, 1.5, "unknown", [], {}, [{"file": "x.gsc", "line": 1}]):
            with self.subTest(leaf=leaf):
                row = stock_declaration(vanilla={"zm_transit": {"cost": leaf}})
                self.assertEqual(c.validate_declaration_metadata(row)["vanilla"]["zm_transit"]["cost"], leaf)

    def test_it_is_bounded(self):
        big = {"zm_transit": {"note": "x" * (c.MAX_VANILLA_BYTES + 1)}}
        with self.assertRaises(Failure) as caught:
            c.validate_declaration_metadata(stock_declaration(vanilla=big))
        self.assertEqual(caught.exception.code, "input_limit")
        self.assertEqual(caught.exception.details["field"], "/vanilla")


class StockInspection(CompositionFixture):
    """``pat module inspect`` on a declaration with no payload."""

    def stock_module(self, mid="vanilla_perks_juggernog", **overrides):
        d = self.root / "modules" / mid
        d.mkdir(parents=True, exist_ok=True)
        (d / "module.json").write_text(json.dumps(stock_declaration(mid, **overrides), indent=2))
        return d

    def test_inspect_reports_the_payload_as_stock(self):
        path = self.stock_module(vanilla=VANILLA, provides={"perks": ["specialty_armorvest"]}) / "module.json"
        code, row = inspect_declaration(path)
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertEqual(result["validation"], "metadata-valid")
        self.assertEqual(result["metadata"]["payload"], "stock")
        self.assertEqual(result["metadata"]["distribution"], "stock")
        self.assertEqual(result["metadata"]["origin"], "vanilla")
        self.assertEqual(result["metadata"]["vanilla"], VANILLA)

    def test_a_declaration_that_names_no_vanilla_block_echoes_none(self):
        code, row = inspect_declaration(self.stock_module() / "module.json")
        self.assertEqual(code, 0, row)
        self.assertNotIn("vanilla", row["result"]["metadata"])

    def test_an_origin_that_is_not_vanilla_is_refused_by_the_route(self):
        path = self.stock_module(origin="bo3") / "module.json"
        code, row = inspect_declaration(path)
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertEqual(row["details"]["inspection"]["diagnostics"][0]["field"], "/origin")


class StockInAComposition(CompositionFixture):
    """A stock member is planned, never built: it is the base's own content."""

    def stock_module(self, mid="vanilla_perks_juggernog", **overrides):
        d = self.root / "modules" / mid
        d.mkdir(parents=True, exist_ok=True)
        (d / "module.json").write_text(json.dumps(stock_declaration(mid, **overrides), indent=2))
        return d

    def plan(self, modules, **extra):
        comp = self.composition(modules, **extra)
        code, row = invoke(["module", "plan", str(comp), "--allow-unqualified", "--output", self.out()])
        return code, row

    def test_a_stock_member_is_listed_under_stock_and_counts_nothing(self):
        self.stock_module(provides={"perks": ["specialty_armorvest"], "models": ["zombie_vending_jugg"]})
        self.module("alpha")
        code, row = self.plan(["vanilla_perks_juggernog", "alpha"])
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertEqual(result["stock"], [{"id": "vanilla_perks_juggernog", "version": "0.1.0",
                                            "provides": {"perks": ["specialty_armorvest"],
                                                         "models": ["zombie_vending_jugg"]}}])
        self.assertEqual(result["scripts"], 1, "only the recipe member's script is compiled")
        self.assertEqual(result["seeds"], 0)
        self.assertEqual(result["adapters"], 0)
        self.assertEqual(result["assets"], 0)
        self.assertEqual(sorted(m["id"] for m in result["modules"]), ["alpha", "vanilla_perks_juggernog"])
        self.assertEqual(next(m for m in result["modules"] if m["id"] == "vanilla_perks_juggernog")["payload"], "stock")
        plan = json.loads((Path(row["result"]["receipt"]).parent / "plan.json").read_text())
        self.assertEqual(plan["footprint"]["vanilla_perks_juggernog"], {"rawfiles": 0, "soundbanks": [], "scripts": 0})
        self.assertEqual([s["module"] for s in plan["scripts"]], ["alpha"])

    def test_a_stock_member_alone_builds_nothing_and_adds_no_pool(self):
        self.stock_module(provides={"weapons": ["zombie_perk_bottle_jugg"], "soundbanks": ["jugg.all"]},
                          resource_contract={"threads": 4, "entities": 0, "hud": 0, "network_fields": 7})
        code, row = self.plan(["vanilla_perks_juggernog"], budget={"threads": 0, "entities": 0, "hud": 0, "network_fields": 0})
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["resource_totals"],
                         {"threads": 0, "entities": 0, "hud": 0, "network_fields": 0},
                         "stock content is the budget baseline, never a contribution to it")
        plan = json.loads((Path(row["result"]["receipt"]).parent / "plan.json").read_text())
        banks = [check for check in plan["checks"] if check["id"] == "pool:assets.soundbank"]
        self.assertTrue(all(check.get("contribution") in (None, 0) for check in banks), banks)

    def test_a_client_box_registration_of_a_weapon_a_stock_member_provides_passes(self):
        """A stock weapon is on the map already: registering it in the box is not a missing weapon."""
        self.stock_module("vanilla_weapons_m1911", provides={"weapons": ["m1911_zm"]})
        d = self.module("wave", provides={"weapons": []})
        (d / "scripts" / "wave.csc").write_text(
            'init()\n{\n    foreach (weapon in strtok("m1911_zm", " "))\n        addzombieboxweapon(weapon, getweaponmodel(weapon), 0);\n}\n')
        recipe = json.loads((d / "project.json").read_text())
        recipe["scripts"].append({"source": "scripts/wave.csc", "target": "scripts/zm/wave.csc", "instance": "client"})
        (d / "project.json").write_text(json.dumps(recipe, indent=2))
        code, row = self.plan(["vanilla_weapons_m1911", "wave"])
        self.assertEqual(code, 0, row)
        rows = [check for check in row["result"]["checks"] if check["id"].startswith("box-registration:")]
        self.assertEqual([check["outcome"] for check in rows], ["passed"], rows)
        self.assertIn("m1911_zm", rows[0]["detail"])

    def test_a_stock_member_is_judged_on_its_declared_bases_and_maps_like_any_other(self):
        self.stock_module(bases=["stock"], maps=["zm_prison"])
        comp = self.composition(["vanilla_perks_juggernog"], name="stock_vanilla_test", map_id="zm_transit")
        code, row = invoke(["module", "plan", str(comp), "--output", self.out()])
        self.assertEqual(code, 1, row)
        kinds = {refusal["kind"] for refusal in row["details"]["refusals"]}
        self.assertEqual(kinds, {"unqualified_map"})
        self.assertEqual(row["details"]["unqualified"],
                         [{"id": "vanilla_perks_juggernog", "declared_bases": ["stock"],
                           "declared_maps": ["zm_prison"], "base": "stock", "map": "zm_transit"}])


class ShippedRow(unittest.TestCase):
    """The ledger row that says the game ships this here. It feeds no fact."""

    def test_shipped_is_a_row_type(self):
        self.assertIn("shipped", ledger.TYPES)

    def test_a_shipped_row_validates(self):
        row = ledger.validate_row(SHIPPED, "/rows/0")
        self.assertEqual(row["type"], "shipped")
        self.assertEqual(row["scope"], {"base": "stock", "foundation": "bo2-stock", "maps": ["zm_transit"]})
        self.assertEqual(row["record"]["sha256"], "a" * 64)
        self.assertEqual(row["citations"], [CITATION])
        self.assertIn("Shipped with the game", row["note"])

    def test_the_declaration_designs_example_row_validates(self):
        """The row the vanilla design writes beside a stock declaration: the scope it ships at, the
        decompile it was read from, and the lines inside it that say so."""
        row = ledger.validate_row(
            {"type": "shipped",
             "scope": {"base": "b2", "foundation": "dlc5-beta2", "maps": ["zm_factory", "zm_sumpf"]},
             "record": {"path": "knowledge/decompiled/stock/patch_zm/maps/mp/zombies/_zm_perks.gsc",
                        "sha256": "0" * 64},
             "citations": [
                 {"file": "dlc5-beta2/zm_factory/maps/mp/zm_factory.gsc", "line": 90, "sha256": "1" * 64,
                  "text": "level.zombiemode_using_juggernaut_perk = 1;"},
                 {"file": "dlc5-beta2/zm_sumpf/maps/mp/zm_sumpf.gsc", "line": 44, "sha256": "2" * 64,
                  "text": "level.zombiemode_using_juggernaut_perk = 1;"},
                 {"file": "foundations/dlc5-beta2 base listing zm_factory-inspect-list.txt", "line": 4919,
                  "sha256": "3" * 64, "text": "material, mc/mtl_zombie_vending_jugg"}],
             "note": "Shipped with the base on these maps. Not built, not installed, not played here."},
            "/rows/0")
        self.assertEqual(row["scope"]["maps"], ["zm_factory", "zm_sumpf"])
        self.assertEqual([c["line"] for c in row["citations"]], [90, 44, 4919])
        self.assertNotIn("at", row, "a generated row carries no timestamp")

    def test_a_row_without_a_record_is_refused_at_the_record(self):
        """What the row was read from is the row: a scope with nothing behind it states nothing."""
        with self.assertRaises(Failure) as caught:
            ledger.validate_row({"type": "shipped", "scope": SCOPE}, "/rows/0")
        self.assertEqual(caught.exception.code, "input_invalid")
        self.assertEqual(caught.exception.details["field"], "/rows/0/record")

    def test_note_and_citations_are_optional_and_scope_is_not(self):
        record = {"path": "knowledge/decompiled/stock/maps/mp/zombies/_zm_perks.gsc", "sha256": "a" * 64}
        self.assertEqual(ledger.validate_row({"type": "shipped", "scope": SCOPE, "record": record}, "/rows/0"),
                         {"type": "shipped", "record": record,
                          "scope": {"base": "stock", "foundation": "bo2-stock", "maps": ["zm_transit"]}})
        with self.assertRaises(Failure) as caught:
            ledger.validate_row({"type": "shipped", "record": record}, "/rows/0")
        self.assertEqual(caught.exception.code, "input_invalid")
        self.assertEqual(caught.exception.details["field"], "/rows/0/scope")

    def test_a_citation_names_a_file_a_line_a_digest_and_the_text(self):
        for missing in ("file", "line", "sha256", "text"):
            partial = {key: value for key, value in CITATION.items() if key != missing}
            with self.assertRaises(Failure, msg=missing) as caught:
                ledger.validate_row(dict(SHIPPED, citations=[partial]), "/rows/0")
            self.assertEqual(caught.exception.details["field"], f"/rows/0/citations/0/{missing}")
        for bad, where in ((dict(CITATION, line=0), "line"), (dict(CITATION, line=True), "line"),
                           (dict(CITATION, sha256="A" * 64), "sha256"), (dict(CITATION, text="  "), "text"),
                           (dict(CITATION, page=1), "page")):
            with self.assertRaises(Failure, msg=str(bad)) as caught:
                ledger.validate_row(dict(SHIPPED, citations=[bad]), "/rows/0")
            self.assertEqual(caught.exception.details["field"], f"/rows/0/citations/0/{where}")

    def test_at_most_sixty_four_citations(self):
        self.assertEqual(len(ledger.validate_row(dict(SHIPPED, citations=[CITATION] * 64), "/rows/0")["citations"]), 64)
        with self.assertRaises(Failure) as caught:
            ledger.validate_row(dict(SHIPPED, citations=[CITATION] * 65), "/rows/0")
        self.assertEqual(caught.exception.details["field"], "/rows/0/citations")
        with self.assertRaises(Failure) as caught:
            ledger.validate_row(dict(SHIPPED, citations="maps/mp/zm_transit.gsc:90"), "/rows/0")
        self.assertEqual(caught.exception.details["field"], "/rows/0/citations")

    def test_citations_belong_to_a_shipped_row_only(self):
        row = {"type": "agent-reviewed", "scope": SCOPE, "outcome": "passed", "citations": [CITATION]}
        with self.assertRaises(Failure) as caught:
            ledger.validate_row(row, "/rows/0")
        self.assertEqual(caught.exception.details["field"], "/rows/0/citations")

    def test_a_shipped_row_states_none_of_the_six_facts(self):
        self.assertEqual(ledger.row_facts(ledger.validate_row(SHIPPED, "/rows/0")), {})

    def test_an_unknown_field_is_refused(self):
        with self.assertRaises(Failure) as caught:
            ledger.validate_row(dict(SHIPPED, offline_verified=True), "/rows/0")
        self.assertEqual(caught.exception.code, "input_invalid")

    def test_the_facts_stay_null_and_shipped_is_reported_per_scope(self):
        book = {"schema": 1, "subject": {"id": "vanilla_perks_juggernog"},
                "rows": [ledger.validate_row(SHIPPED, "/rows/0")]}
        derived = ledger.facts(book, base="stock", map_id="zm_transit")
        self.assertEqual({fact: derived["facts"][fact]["value"] for fact in ledger.FACTS},
                         {fact: None for fact in ledger.FACTS})
        self.assertEqual(derived["shipped"], {"value": True, "rows": [0]})
        self.assertEqual(derived["history"]["shipped"], 1)
        self.assertEqual(derived["scopes"], [
            {"scope": {"base": "stock", "foundation": "bo2-stock", "map": "zm_transit", "location": None},
             "facts": {fact: {"value": None, "rows": []} for fact in ledger.FACTS},
             "shipped": {"value": True, "rows": [0]}}])
        self.assertEqual(derived["by_target"], [
            {"base": "stock", "map": "zm_transit", "location": None,
             "facts": {fact: {"value": None, "rows": []} for fact in ledger.FACTS},
             "shipped": {"value": True, "rows": [0]}}])

    def test_a_map_the_row_does_not_name_is_not_shipped(self):
        book = {"schema": 1, "subject": {"id": "vanilla_perks_juggernog"},
                "rows": [ledger.validate_row(SHIPPED, "/rows/0")]}
        self.assertEqual(ledger.facts(book, map_id="zm_prison")["shipped"], {"value": False, "rows": []})

    def test_a_ledger_with_no_shipped_row_says_false(self):
        book = {"schema": 1, "subject": {"id": "alpha"}, "rows": []}
        self.assertEqual(ledger.facts(book)["shipped"], {"value": False, "rows": []})


class ShippedThroughTheRoutes(CompositionFixture):
    """``module ledger-add`` writes one, ``module state --ledger`` reports it."""

    def module_dir(self):
        d = self.root / "modules" / "vanilla_perks_juggernog"
        d.mkdir(parents=True, exist_ok=True)
        (d / "module.json").write_text(json.dumps(stock_declaration(), indent=2))
        return d

    def test_ledger_add_accepts_a_shipped_row_and_module_state_reports_it(self):
        d = self.module_dir()
        row_file = self.root / "shipped.json"
        row_file.write_text(json.dumps(SHIPPED))
        code, added = invoke(["module", "ledger-add", str(d), "--row", str(row_file), "--json"])
        self.assertEqual(code, 0, added)
        result = added["result"]
        self.assertEqual(result["created"], True)
        self.assertEqual(result["rows_after"], 1)
        self.assertEqual(result["appended"], [0])
        self.assertEqual(result["validation"], "valid")
        self.assertEqual(result["rows"][0]["type"], "shipped")
        book = json.loads((d / "evidence.json").read_text())
        self.assertEqual(book["rows"][0]["type"], "shipped")

        code, state = invoke(["module", "state", "--ledger", str(d), "--base", "stock",
                              "--map", "zm_transit", "--json"])
        self.assertEqual(code, 0, state)
        reported = state["result"]
        self.assertEqual(reported["validation"], "valid")
        self.assertEqual(reported["shipped"], {"value": True, "rows": [0]})
        self.assertEqual({fact: reported["facts"][fact]["value"] for fact in ledger.FACTS},
                         {fact: None for fact in ledger.FACTS},
                         "shipping with the game is none of the six facts")
        self.assertEqual(reported["history"]["shipped"], 1)
        self.assertTrue(reported["scopes"][0]["shipped"]["value"])

    def test_inspect_validates_a_shipped_row_beside_the_declaration(self):
        d = self.module_dir()
        (d / "evidence.json").write_text(json.dumps(
            {"schema": 1, "subject": {"id": "vanilla_perks_juggernog"}, "rows": [SHIPPED]}, indent=2))
        code, row = inspect_declaration(d / "module.json")
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["ledger"]["validation"], "valid")
        self.assertEqual(row["result"]["ledger"]["types"], ["shipped"])


if __name__ == "__main__":
    unittest.main()
