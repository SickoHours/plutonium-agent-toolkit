"""Target sets: ``pat target list|inspect|validate``, the ``placements`` field on module.json,
the plan-time placements check, and the ledger's ``--target`` query and per-target view.

Fixtures copy the shapes of the workspace's real files (a foundation descriptor, the Der Riese
location table's row shapes, a survival-location entry) with synthetic ids, hashes and paths.
"""
import contextlib
import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plutonium_agent_toolkit import cli
from plutonium_agent_toolkit.core.errors import Failure
from plutonium_agent_toolkit.dev import targets
from tests.test_compositions import CompositionFixture
from tests.test_dev_routes import invoke as job_invoke

SHA = "e3278aa14a7c3a9fbd631f92ea4657e9decb06520dea8dd298ccff41cfb08d24"
RECORD = "docs/example-locations/zm_factory.md"


def invoke(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.entry(argv)
    return code, json.loads(out.getvalue())


def literal_row(rid, kind="perk-machine", occupant="specialty_armorvest", origin=(1361.2, 374, 64.6), text=None, **extra):
    row = {"kind": kind, "id": rid, "site": f"vending_{rid.split('-')[-1]}", "occupant": occupant,
           "origin": list(origin), "angles": [0, -180, 0],
           "source": {"provider": "example-downloads", "record": RECORD, "citation": "P:22",
                      "file": "zombie_example_perk_machines.gsc", "line": 22, "sha256": SHA,
                      "text": text if text is not None else "(%s, %s, %s)" % tuple(origin)},
           "confidence": "high", "note": "Source literal; nothing here is a measured T6 placement."}
    row.update(extra)
    return row


def expression_row(rid, kind="perk-machine", occupant="specialty_fastreload", angles=True):
    return {"kind": kind, "id": rid, "site": "vending_sleight", "occupant": occupant, "origin": None, "angles": None,
            "expression": {"origin": 'GetEnt( "vending_sleight","targetname" ).origin + (7,0,0)',
                           "angles": 'GetEnt( "vending_sleight","targetname" ).angles' if angles else None},
            "source": {"provider": "example-downloads", "record": RECORD, "citation": "P:19",
                       "file": "zombie_example_perk_machines.gsc", "line": 19, "sha256": SHA,
                       "text": 'GetEnt( "vending_sleight","targetname" ).origin + (7,0,0)', "anchor_citations": ["P:9", "P:13"]},
            "confidence": "high", "note": "Source relation; absolute base transform not recovered."}


def fence_row(rid="stock-route-example", location="town"):
    """The shape the thin stock tables carry: one engine route registration, no transform,
    ``expression.angles`` null because the engine owns them."""
    return {"kind": "zone-fence", "id": rid, "site": "maps\\mp\\zm_example_standard", "occupant": None,
            "origin": None, "angles": None,
            "expression": {"origin": f'add_map_location_gamemode("zstandard", "{location}", ...);', "angles": None},
            "source": {"provider": "stock", "record": RECORD, "citation": "example zm_example_gamemodes.gsc:27",
                       "file": "scripts/zm/replaced/zm_example_gamemodes.gsc", "line": 27, "sha256": SHA,
                       "text": f'add_map_location_gamemode("zstandard", "{location}", ...);'},
            "confidence": "medium",
            "note": "Registration read from a replacement copy of the stock init; machines wait for the vanilla profile extractor."}


def table(target="dlc5-beta2/zm_factory/zclassic", location=None, route="stock", **overrides):
    foundation, map_id, mode = target.split("/")[:3]
    doc = {"schema": 1, "target": target, "foundation": foundation, "map": map_id, "mode": mode, "location": location,
           "title": "Example Map", "route": route, "records": [RECORD],
           "coordinate_note": "Origins are (x, y, z); angles are (pitch, yaw, roll) exactly as the source writes them.",
           "facts": {f: False for f in targets.TABLE_FACTS},
           "placements": [literal_row("ex-vending_jugg"), expression_row("ex-vending_sleight"),
                          literal_row("ex-wall-mp5k", kind="wall-buy", occupant="mp5k_zm", origin=(-620.359, -344.359, 69.125)),
                          literal_row("ex-gum-1", kind="gobblegum", occupant=None, origin=(100, 200, 64)),
                          literal_row("ex-pap", kind="pack-a-punch", occupant=None, origin=(1, 2, 3))]}
    doc.update(overrides)
    return doc


def thin_table(target="bo2-stock/zm_transit/zsurvival/town", location="town"):
    """A stock target as the workspace writes it today: the route registration and nothing
    else, with a shelf block, until a vanilla profile extractor fills in the machines."""
    return table(target=target, location=location, route="stock", title=location.title(),
                 shelf={"caption_key": "ZMUI_EXAMPLE_CAPS", "caption_source": "example gametypestable.csv:30",
                        "preview_material": "menu_zm_map_example_blit", "engine_location": location},
                 source_notes=["Stock target; the retained clones carry no stock location script."],
                 placements=[fence_row(f"stock-route-{location}", location)])


def survival_table(location="diner", route="bo2-reimagined", rows=None):
    key = f"bo2-stock/zm_transit/zsurvival/{location}"
    return table(target=key, location=location, route=route, title=location.title(),
                 placements=rows or [literal_row(f"{route}-perk-jugg"),
                                     literal_row(f"{route}-box", kind="mystery-box", occupant=None, origin=(5, 6, 7)),
                                     expression_row(f"{route}-fence", kind="zone-fence", occupant=None, angles=False)])


def survival_entry(location="diner", route="bo2-reimagined", **overrides):
    key = f"bo2-stock/zm_transit/zsurvival/{location}"
    entry = {"id": targets.target_id(key, route), "target": key, "kind": "survival-location", "foundation": "bo2-stock",
             "map": "zm_transit", "mode": "zsurvival", "location": location, "parent": "bo2-stock/zm_transit/zclassic",
             "title": location.title(), "caption": "GREEN RUN / SURVIVAL", "route": route,
             "fence": {"zones": ["zone_gas", "zone_roadside_east"], "rows": 2,
                       "citations": ["scripts/zm/locs/zm_transit_loc_example.gsc:9",
                                     "scripts/zm/locs/zm_transit_loc_example.gsc:14"]},
             "location_table": targets.table_relpath(key, route), "placements": None, "vanilla_profile": None,
             "art": {"preview": "menu_zm_transit_zsurvival_example", "loadscreen": None}, "ledger": []}
    entry.update(overrides)
    return entry


def stock_location_entry(location="town", parent="bo2-stock/zm_transit/zclassic"):
    """A shipped start location. Nuketown's shape: a map with no classic mode of its own has a
    stock location with no parent."""
    key = f"bo2-stock/zm_transit/zsurvival/{location}"
    return {"id": key, "target": key, "kind": "stock-location", "foundation": "bo2-stock", "map": "zm_transit",
            "mode": "zsurvival", "location": location, "parent": parent, "title": location.title(),
            "caption": "GREEN RUN / SURVIVAL", "route": "stock",
            "fence": {"zones": [], "rows": 1, "citations": ["scripts/zm/replaced/zm_transit_gamemodes.gsc:27"]},
            "location_table": targets.table_relpath(key, "stock"), "placements": 1, "vanilla_profile": None,
            "art": {"preview": "menu_zm_map_transit_blit_town", "loadscreen": None}, "ledger": []}


def stock_entry():
    key = "bo2-stock/zm_transit/zclassic"
    return {"id": key, "target": key, "kind": "stock-map", "foundation": "bo2-stock", "map": "zm_transit",
            "mode": "zclassic", "location": None, "parent": None, "title": "TranZit", "caption": "GREEN RUN", "route": "stock"}


class WorkspaceFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ws = self.root / "workspace"
        (self.ws / "foundations").mkdir(parents=True)
        (self.ws / "registry" / "locations").mkdir(parents=True)
        self.env = patch.dict(os.environ, {"PAT_HOME": str(self.root / "pat-home")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.foundation("bo2-stock", "stock", ["zm_transit"])
        self.foundation("dlc5-beta2", "b2", ["zm_factory", "zm_prototype"])

    def foundation(self, fid, prefix, maps):
        doc = {"schema": 1, "id": fid, "registry": "docs/FOUNDATIONS.md", "profile_prefix": prefix, "profile_links": {},
               "maps": {m: {"runtime_zones": ["common_zm", m], "link_loads": ["common_zm", m]} for m in maps},
               "mod_zone_header": [">game,T6", ">name,mod"], "techniqueset_map": {}, "note": "synthetic"}
        (self.ws / "foundations" / f"{fid}.json").write_text(json.dumps(doc), encoding="utf-8")

    def write_table(self, doc, key=None, route=None):
        key = key or doc["target"]
        path = self.ws / targets.table_relpath(key, route if route is not None else doc.get("route"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        return path

    def write_targets(self, entries, count=None, **extra):
        path = self.ws / "registry" / "targets.json"
        body = {"schema": 1, "entries": entries, **extra}
        if count is not None:
            body["targets"] = count
        path.write_text(json.dumps(body), encoding="utf-8")
        return path


class TableValidation(unittest.TestCase):
    """The workspace's location_table.py rules, made public."""

    def test_a_well_formed_table_has_no_diagnostics(self):
        self.assertEqual(targets.validate_table(table()), [])
        summary = targets.summarize_table(table())
        self.assertEqual(summary["placements"], 5)
        self.assertEqual(summary["by_kind"], {"gobblegum": 1, "pack-a-punch": 1, "perk-machine": 2, "wall-buy": 1})
        self.assertEqual((summary["literal"], summary["expression"]), (4, 1))
        self.assertEqual(summary["providers"], {"example-downloads": 5})

    def messages(self, doc):
        return [e["message"] for e in targets.validate_table(doc)]

    def test_target_string_must_equal_its_parts(self):
        self.assertTrue(any("must equal" in m for m in self.messages(table(target="dlc5-beta2/zm_factory/zclassic", map="zm_prototype"))))
        doc = table(); doc["target"] = "dlc5-beta2/zm_factory/zsurvival"
        self.assertTrue(any("must equal" in m for m in self.messages(doc)))

    def test_survival_target_needs_a_location(self):
        doc = table(target="bo2-stock/zm_transit/zsurvival")
        self.assertTrue(any("names its location" in m for m in self.messages(doc)))
        doc = table(target="bo2-stock/zm_transit/zsurvival/diner", location="diner")
        self.assertEqual(self.messages(doc), [])

    def test_six_facts_must_all_be_false(self):
        doc = table(); doc["facts"]["installed"] = True
        self.assertTrue(any("must be false" in m for m in self.messages(doc)))
        doc = table(); del doc["facts"]["captured"]
        self.assertTrue(any("exactly" in m for m in self.messages(doc)))

    def test_row_needs_literal_or_expression(self):
        doc = table(); doc["placements"][0].update(origin=None, angles=None)
        self.assertTrue(any("expression.origin" in m for m in self.messages(doc)))
        doc["placements"][0]["expression"] = {"origin": 'GetEnt("vending_jugg","targetname").origin'}
        self.assertEqual(self.messages(doc), [])
        doc = table(); doc["placements"][0]["origin"] = None
        self.assertTrue(any("angles without an origin" in m for m in self.messages(doc)))

    def test_vectors_are_three_numbers(self):
        doc = table(); doc["placements"][0]["origin"] = [1, 2]
        self.assertTrue(any("three-number" in m for m in self.messages(doc)))
        doc = table(); doc["placements"][0]["angles"] = ["0", "90", "0"]
        self.assertTrue(any("three-number" in m for m in self.messages(doc)))
        doc = table(); doc["placements"][0]["angles"] = [True, 0, 0]
        self.assertTrue(any("three-number" in m for m in self.messages(doc)))

    def test_unique_ids_known_kind_listed_record_and_confidence(self):
        doc = table(); doc["placements"].append(copy.deepcopy(doc["placements"][0]))
        self.assertTrue(any("duplicate placement id" in m for m in self.messages(doc)))
        doc = table(); doc["placements"][0]["kind"] = "teleporter"
        self.assertTrue(any("kind" in m for m in self.messages(doc)))
        doc = table(); doc["placements"][0]["source"]["record"] = "docs/other.md"
        self.assertTrue(any("not listed in records" in m for m in self.messages(doc)))
        doc = table(); doc["placements"][0]["source"]["line"] = None
        self.assertTrue(any("high confidence requires" in m for m in self.messages(doc)))
        doc = table(); doc["placements"][0]["confidence"] = "certain"
        self.assertTrue(any("confidence" in m for m in self.messages(doc)))
        doc = table(); doc["placements"][0]["source"]["sha256"] = "abc"
        self.assertTrue(any("64 hex" in m for m in self.messages(doc)))
        doc = table(); doc["records"] = ["/abs/record.md"]
        self.assertTrue(any("workspace-relative" in m for m in self.messages(doc)))

    def test_literal_origin_must_match_cited_text(self):
        doc = table(); doc["placements"][0]["origin"] = [1361.2, 374, 65]
        self.assertTrue(any("does not match cited text" in m for m in self.messages(doc)))
        # An accepted coordinate cited to a verdict is not a source literal and is not compared.
        doc = table(); doc["placements"][0]["source"]["citation"] = "Accepted Der Riese origin"; doc["placements"][0]["origin"] = [1, 1, 1]
        self.assertEqual(self.messages(doc), [])

    def test_notes_cannot_claim_a_t6_fact(self):
        for phrase in ("Verified on T6 in play mode", "accepted on beta 2", "Playable in solo"):
            doc = table(); doc["placements"][0]["note"] = phrase
            self.assertTrue(any("claims a T6 fact" in m for m in self.messages(doc)), phrase)

    def test_shape_defects_stop_early_with_one_message_each(self):
        self.assertEqual(targets.validate_table([])[0]["message"], "table must be a JSON object")
        doc = table(); del doc["records"]; doc["schema"] = 2
        messages = self.messages(doc)
        self.assertEqual(len(messages), 2)
        doc = table(); doc["placements"] = []
        self.assertTrue(any("non-empty list" in m for m in self.messages(doc)))

    def test_rotation_slot_needs_a_transform(self):
        doc = table(); doc["placements"][0].update(kind="rotation-slot", origin=None, angles=None)
        self.assertTrue(any("rotation slot" in m or "expression.origin" in m for m in self.messages(doc)))


class TargetKeys(unittest.TestCase):
    def test_parse_and_refuse(self):
        self.assertEqual(targets.parse_key("bo2-stock/zm_transit/zsurvival/diner"),
                         {"foundation": "bo2-stock", "map": "zm_transit", "mode": "zsurvival", "location": "diner"})
        self.assertEqual(targets.parse_key("dlc5-beta2/zm_factory/zclassic")["location"], None)
        for bad in ("zm_transit", "bo2-stock/zm_transit", "bo2-stock/zm_transit/classic", "bo2-stock/transit/zclassic",
                    "bo2-stock/zm_transit/zclassic/diner/extra", "BO2/zm_transit/zclassic", "../x/zm_transit/zclassic", 7):
            with self.assertRaises(Failure) as caught:
                targets.parse_key(bad)
            self.assertEqual(caught.exception.code, "invalid_arguments", bad)
        self.assertEqual(targets.target_key("bo2-stock", "zm_transit", "zsurvival", "town"), "bo2-stock/zm_transit/zsurvival/town")


class TargetEntries(unittest.TestCase):
    def errors(self, entry):
        return [e["message"] for e in targets.validate_entry(entry, 0)[1]]

    def test_survival_and_stock_entries_are_valid(self):
        self.assertEqual(self.errors(survival_entry()), [])
        self.assertEqual(self.errors(stock_entry()), [])
        parsed = targets.validate_entry(survival_entry(), 0)[0]
        self.assertEqual((parsed["kind"], parsed["parent"], parsed["route"]), ("survival-location", "bo2-stock/zm_transit/zclassic", "bo2-reimagined"))

    def test_parts_kind_parent_fence_and_route_rules(self):
        e = survival_entry(); e["map"] = "zm_nuked"
        self.assertTrue(any("must equal the id's" in m for m in self.errors(e)))
        e = survival_entry(); e["kind"] = "stock-map"
        self.assertTrue(any("has no location" in m for m in self.errors(e)))
        e = stock_entry(); e["kind"] = "survival-location"
        self.assertTrue(any("names a location" in m for m in self.errors(e)))
        e = survival_entry(); e["parent"] = "bo2-stock/zm_nuked/zclassic"
        self.assertTrue(any("parent" in m for m in self.errors(e)))
        e = stock_entry(); e["parent"] = "bo2-stock/zm_transit/zclassic"
        self.assertTrue(any("a map has no parent" in m for m in self.errors(e)))
        e = survival_entry(); e["fence"] = {"zones": ["zone_gas"]}
        self.assertTrue(any("wiki room label" in m for m in self.errors(e)))
        e = survival_entry(); e["route"] = ["bo2-reimagined", "t6-qol"]
        self.assertTrue(any("exactly one provider" in m for m in self.errors(e)))
        e = survival_entry(); e["kind"] = "custom"
        self.assertTrue(any("kind" in m for m in self.errors(e)))
        e = survival_entry(); e["location_table"] = "/abs/table.json"
        self.assertTrue(any("workspace-relative" in m for m in self.errors(e)))
        e = survival_entry(); e["extra"] = 1
        self.assertTrue(any("unknown fields" in m for m in self.errors(e)))
        self.assertEqual(targets.validate_entry({"id": "nope"}, 3)[0], None)


class RoutesOnAWorkspace(WorkspaceFixture):
    def test_list_reads_foundations_and_the_target_file_and_groups_by_parent(self):
        self.write_table(table())
        self.write_targets([stock_entry(), survival_entry("diner"), survival_entry("diner", route="t6-qol"),
                            stock_location_entry("town")], count=3)
        code, row = invoke(["target", "list", str(self.ws), "--json"])
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertEqual(result["protocol"], "pat.target/1")
        ids = [t["id"] for t in result["targets"]]
        self.assertEqual(ids, ["bo2-stock/zm_transit/zclassic",
                               "bo2-stock/zm_transit/zsurvival/diner@bo2-reimagined",
                               "bo2-stock/zm_transit/zsurvival/diner@t6-qol",
                               "bo2-stock/zm_transit/zsurvival/town",
                               "dlc5-beta2/zm_factory/zclassic", "dlc5-beta2/zm_prototype/zclassic"])
        by_id = {t["id"]: t for t in result["targets"]}
        self.assertEqual(by_id["dlc5-beta2/zm_factory/zclassic"]["kind"], "dlc5-map")
        self.assertEqual(by_id["dlc5-beta2/zm_factory/zclassic"]["title"], "Der Riese")
        self.assertEqual(by_id["dlc5-beta2/zm_factory/zclassic"]["location_table"], "registry/locations/dlc5-beta2/zm_factory/zclassic.json")
        self.assertEqual(by_id["dlc5-beta2/zm_factory/zclassic"]["base"], "b2")
        self.assertEqual(by_id["bo2-stock/zm_transit/zclassic"]["kind"], "stock-map")
        self.assertEqual(by_id["bo2-stock/zm_transit/zclassic"]["title"], "TranZit")
        self.assertIsNone(by_id["bo2-stock/zm_transit/zsurvival/diner@bo2-reimagined"]["location_table"])
        self.assertEqual(by_id["bo2-stock/zm_transit/zsurvival/diner@bo2-reimagined"]["route"], "bo2-reimagined")
        self.assertEqual(by_id["bo2-stock/zm_transit/zsurvival/town"]["kind"], "stock-location")
        # Two routes for one key are a pair the listing reports and never merges.
        self.assertEqual(by_id["bo2-stock/zm_transit/zsurvival/diner@t6-qol"]["route_choices"],
                         ["bo2-reimagined", "t6-qol"])
        self.assertEqual(result["route_choices"],
                         [{"target": "bo2-stock/zm_transit/zsurvival/diner", "routes": ["bo2-reimagined", "t6-qol"]}])
        groups = {g["parent"]: g for g in result["groups"]}
        green_run = groups["bo2-stock/zm_transit/zclassic"]
        self.assertEqual(green_run["title"], "TranZit")
        self.assertEqual([(c["id"].rsplit("/", 1)[-1], c["route"], c["location_table"]) for c in green_run["children"]],
                         [("diner@bo2-reimagined", "bo2-reimagined", False), ("diner@t6-qol", "t6-qol", False),
                          ("town", "stock", False)])
        self.assertEqual(groups["dlc5-beta2/zm_factory/zclassic"]["children"], [])
        self.assertEqual(result["counts"], {"entries": 6, "targets": 5, "with_location_table": 1, "route_choices": 1,
                                            "stock-map": 1, "stock-location": 1, "survival-location": 2,
                                            "dlc5-map": 2, "custom-map": 0})
        self.assertEqual(result["diagnostics"], [])
        self.assertEqual(result["foundations"]["dlc5-beta2"], {"base": "b2", "maps": ["zm_factory", "zm_prototype"]})

    def test_list_without_a_target_file_lists_the_foundations_maps_only(self):
        code, row = invoke(["target", "list", str(self.ws), "--json"])
        self.assertEqual(code, 0, row)
        self.assertIsNone(row["result"]["targets_file"])
        self.assertEqual(row["result"]["counts"]["targets"], 3)
        self.assertEqual(row["result"]["counts"]["with_location_table"], 0)
        self.assertEqual(row["result"]["route_choices"], [])

    def test_list_reports_target_file_defects_as_diagnostics_and_validate_refuses_them(self):
        bad = survival_entry(); bad["route"] = 5
        self.write_targets([stock_entry(), bad, survival_entry("diner"), survival_entry("diner", route="t6-qol")])
        code, row = invoke(["target", "list", str(self.ws), "--json"])
        self.assertEqual(code, 0, row)
        messages = [d["message"] for d in row["result"]["diagnostics"]]
        self.assertTrue(any("names exactly one provider" in m for m in messages), messages)
        self.assertTrue(any("duplicate target id" in m for m in messages), messages)
        code, row = invoke(["target", "validate", str(self.ws), "--json"])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")
        self.assertFalse(row["details"]["report"]["ok"])

    def test_inspect_returns_entry_and_table_summary(self):
        self.write_table(table())
        code, row = invoke(["target", "inspect", str(self.ws), "dlc5-beta2/zm_factory/zclassic", "--json"])
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertTrue(result["listed"])
        self.assertEqual(result["entry"]["kind"], "dlc5-map")
        lt = result["location_table"]
        self.assertEqual(lt["validation"], "valid")
        self.assertEqual(lt["summary"]["placements"], 5)
        self.assertEqual(lt["summary"]["by_kind"]["perk-machine"], 2)
        self.assertEqual(lt["path"], "registry/locations/dlc5-beta2/zm_factory/zclassic.json")
        self.assertEqual(len(lt["sha256"]), 64)
        # A listed target without a table: entry, no table, exit 0.
        code, row = invoke(["target", "inspect", str(self.ws), "dlc5-beta2/zm_prototype/zclassic", "--json"])
        self.assertEqual(code, 0, row)
        self.assertIsNone(row["result"]["location_table"])
        # Neither listed nor tabled: input_missing with the parsed key in details.
        code, row = invoke(["target", "inspect", str(self.ws), "bo2-stock/zm_transit/zsurvival/diner", "--json"])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_missing")
        self.assertEqual(row["details"]["location"], "diner")
        code, row = invoke(["target", "inspect", str(self.ws), "diner", "--json"])
        self.assertEqual(code, 2, row)
        self.assertEqual(row["error_code"], "invalid_arguments")

    def test_inspect_reports_a_malformed_table_without_raising(self):
        doc = table(); doc["facts"]["installed"] = True
        self.write_table(doc)
        code, row = invoke(["target", "inspect", str(self.ws), "dlc5-beta2/zm_factory/zclassic", "--json"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["location_table"]["validation"], "invalid")
        self.assertTrue(any("must be false" in d["message"] for d in row["result"]["location_table"]["diagnostics"]))

    def test_validate_checks_every_table_its_path_and_the_target_file(self):
        self.write_table(table())
        self.write_table(survival_table("diner", route="bo2-reimagined"))
        self.write_targets([stock_entry(), survival_entry("diner", route="bo2-reimagined")])
        code, row = invoke(["target", "validate", str(self.ws), "--json"])
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertTrue(result["ok"])
        self.assertEqual([t["path"] for t in result["tables"]],
                         ["registry/locations/bo2-stock/zm_transit/zsurvival/diner.bo2-reimagined.json",
                          "registry/locations/dlc5-beta2/zm_factory/zclassic.json"])
        self.assertTrue(all(t["ok"] and t["listed"] for t in result["tables"]))
        self.assertEqual(result["unlisted_tables"], [])
        # A table at the wrong path for its target.
        self.write_table(table(target="dlc5-beta2/zm_prototype/zclassic"), key="dlc5-beta2/zm_sumpf/zclassic")
        code, row = invoke(["target", "validate", str(self.ws), "--json"])
        self.assertEqual(code, 1, row)
        messages = [d["message"] for d in row["details"]["report"]["diagnostics"]]
        self.assertTrue(any("must equal its path" in m for m in messages), messages)
        self.assertIn("registry/locations/dlc5-beta2/zm_sumpf/zclassic.json", row["details"]["report"]["unlisted_tables"])
        (self.ws / "registry/locations/dlc5-beta2/zm_sumpf/zclassic.json").unlink()
        # A listed table that does not exist (the workspace's L3 gate).
        self.write_targets([stock_entry(), survival_entry("cornfield")])
        code, row = invoke(["target", "validate", str(self.ws), "--json"])
        self.assertEqual(code, 1, row)
        messages = [d["message"] for d in row["details"]["report"]["diagnostics"]]
        self.assertTrue(any("does not exist" in m for m in messages), messages)
        # A table named at a path its id and route do not produce.
        self.write_targets([stock_entry(), survival_entry("diner", route="bo2-reimagined")
                            | {"location_table": "registry/locations/bo2-stock/zm_transit/zsurvival/diner.json"}])
        code, row = invoke(["target", "validate", str(self.ws), "--json"])
        self.assertEqual(code, 1, row)
        messages = [d["message"] for d in row["details"]["report"]["diagnostics"]]
        self.assertTrue(any("the path this id and route name" in m for m in messages), messages)

    def test_validate_reports_unreadable_tables_and_a_missing_workspace(self):
        (self.ws / "registry/locations/broken.json").write_text("{not json", encoding="utf-8")
        code, row = invoke(["target", "validate", str(self.ws), "--json"])
        self.assertEqual(code, 1, row)
        self.assertTrue(any("not valid UTF-8 JSON" in d["message"] for d in row["details"]["report"]["diagnostics"]))
        code, row = invoke(["target", "list", str(self.root / "nowhere"), "--json"])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_missing")

    def test_routes_are_registered_inert_and_implemented(self):
        code, row = invoke(["manifest", "--json"])
        by_id = {r["id"]: r for r in row["result"]["routes"]}
        for action in ("list", "inspect", "validate"):
            route = by_id[f"target.{action}"]
            self.assertEqual((route["effect"], route["status"]), ("inert", "implemented"), action)
            self.assertIn("docs/target-sets.md", route["notes"])


class TwoRoutesOneTarget(WorkspaceFixture):
    """A location two community routes both provide: two tables, two entries, one key. The
    registry records the pair and never picks; the choice is refused at plan time instead."""

    def setUp(self):
        super().setUp()
        self.write_table(survival_table("diner", route="bo2-reimagined"))
        self.write_table(survival_table("diner", route="t6-qol"))
        self.write_targets([stock_entry(), survival_entry("diner", route="bo2-reimagined"),
                            survival_entry("diner", route="t6-qol")], count=2)

    def test_both_tables_validate_and_the_pair_is_reported_not_merged(self):
        code, row = invoke(["target", "validate", str(self.ws), "--json"])
        self.assertEqual(code, 0, row)
        result = row["result"]
        self.assertTrue(result["ok"])
        # Three foundation maps plus the two Diner entries; four distinct keys.
        self.assertEqual(result["entries"], 5)
        self.assertEqual(result["targets"], 4)
        self.assertEqual(sorted(t["route"] for t in result["tables"]), ["bo2-reimagined", "t6-qol"])
        self.assertEqual(result["route_choices"],
                         [{"target": "bo2-stock/zm_transit/zsurvival/diner", "routes": ["bo2-reimagined", "t6-qol"]}])

    def test_inspect_refuses_to_choose_and_answers_a_named_route(self):
        code, row = invoke(["target", "inspect", str(self.ws), "bo2-stock/zm_transit/zsurvival/diner", "--json"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["outcome"], "route_choice")
        self.assertEqual(row["result"]["routes"], ["bo2-reimagined", "t6-qol"])
        self.assertIsNone(row["result"]["location_table"])
        self.assertIn("never a merge", row["result"]["detail"])
        for argv in (["bo2-stock/zm_transit/zsurvival/diner", "--route", "t6-qol"],
                     ["bo2-stock/zm_transit/zsurvival/diner@t6-qol"]):
            code, row = invoke(["target", "inspect", str(self.ws), *argv, "--json"])
            self.assertEqual(code, 0, row)
            self.assertEqual(row["result"]["outcome"], "one")
            self.assertEqual(row["result"]["entry"]["route"], "t6-qol")
            self.assertEqual(row["result"]["location_table"]["route"], "t6-qol")
            self.assertEqual(row["result"]["location_table"]["path"],
                             "registry/locations/bo2-stock/zm_transit/zsurvival/diner.t6-qol.json")
        code, row = invoke(["target", "inspect", str(self.ws), "bo2-stock/zm_transit/zsurvival/diner@t6-qol",
                            "--route", "bo2-reimagined", "--json"])
        self.assertEqual(code, 2, row)
        self.assertEqual(row["error_code"], "invalid_arguments")

    def test_two_entries_on_one_route_are_a_duplicate(self):
        self.write_targets([stock_entry(), survival_entry("diner"), survival_entry("diner")])
        code, row = invoke(["target", "validate", str(self.ws), "--json"])
        self.assertEqual(code, 1, row)
        messages = [d["message"] for d in row["details"]["report"]["diagnostics"]]
        self.assertTrue(any("duplicate target id" in m for m in messages), messages)

    def test_table_for_refuses_an_ambiguous_key_and_resolves_a_named_one(self):
        with self.assertRaises(Failure) as caught:
            targets.table_for(self.ws, "bo2-stock/zm_transit/zsurvival/diner")
        self.assertEqual(caught.exception.code, "invalid_arguments")
        self.assertEqual(caught.exception.details["routes"], ["bo2-reimagined", "t6-qol"])
        resolved = targets.table_for(self.ws, "bo2-stock/zm_transit/zsurvival/diner@bo2-reimagined")
        self.assertEqual(resolved["route"], "bo2-reimagined")
        self.assertEqual(resolved["path"], "registry/locations/bo2-stock/zm_transit/zsurvival/diner.bo2-reimagined.json")
        # A bare key with one table needs no discriminator.
        self.write_table(table())
        self.assertEqual(targets.table_for(self.ws, "dlc5-beta2/zm_factory/zclassic")["route"], "stock")


class StockTargetsAndCounts(WorkspaceFixture):
    """The shapes the workspace's own stock rows carry: a route registration and nothing else,
    a shelf block, a start location with no classic target of its own, and the counts the file
    states about itself."""

    def test_a_thin_stock_table_validates(self):
        doc = thin_table()
        self.assertEqual(targets.validate_table(doc, "town.json"), [])
        self.write_table(doc)
        self.write_targets([stock_entry(), stock_location_entry("town")], count=2)
        code, row = invoke(["target", "validate", str(self.ws), "--json"])
        self.assertEqual(code, 0, row)
        self.assertTrue(row["result"]["ok"])
        code, row = invoke(["target", "inspect", str(self.ws), "bo2-stock/zm_transit/zsurvival/town", "--json"])
        self.assertEqual(code, 0, row)
        summary = row["result"]["location_table"]["summary"]
        self.assertEqual(summary["placements"], 1)
        self.assertEqual(summary["by_kind"], {"zone-fence": 1})
        self.assertEqual(summary["literal"], 0)
        self.assertEqual(summary["expression"], 1)

    def test_expression_angles_may_be_null(self):
        doc = table(placements=[expression_row("ex-1", angles=False)])
        self.assertEqual(targets.validate_table(doc, "t.json"), [])
        doc = table(placements=[expression_row("ex-1") | {"expression": {"origin": 5}}])
        self.assertTrue(any("strings or nulls" in e["message"] for e in targets.validate_table(doc, "t.json")))

    def test_a_start_location_without_a_parent_only_where_the_map_has_no_classic_target(self):
        # Nuketown's shape: survival only, so the location is a top-level row.
        entry = stock_location_entry("nuked", parent=None)
        self.write_targets([entry])
        code, row = invoke(["target", "list", str(self.ws), "--json"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["diagnostics"], [])
        groups = {g["parent"]: g for g in row["result"]["groups"]}
        self.assertIn("bo2-stock/zm_transit/zsurvival/nuked", groups)
        # Beside a classic target of the same map, a parentless location is a defect.
        self.write_targets([stock_entry(), entry])
        code, row = invoke(["target", "list", str(self.ws), "--json"])
        self.assertTrue(any("may not sit beside" in d["message"] for d in row["result"]["diagnostics"]))
        # A community location always names its parent.
        self.write_targets([stock_entry(), survival_entry("diner", parent=None)])
        code, row = invoke(["target", "list", str(self.ws), "--json"])
        self.assertTrue(any("names that map's target as its parent" in d["message"] for d in row["result"]["diagnostics"]))

    def test_the_file_counts_its_distinct_targets_and_entries_count_their_rows(self):
        self.write_table(survival_table("diner", route="bo2-reimagined"))
        self.write_table(survival_table("diner", route="t6-qol"))
        # Two entries, one key: the count is of keys, not entries, so the entry count is wrong.
        self.write_targets([stock_entry(), survival_entry("diner"), survival_entry("diner", route="t6-qol")], count=3)
        code, row = invoke(["target", "validate", str(self.ws), "--json"])
        self.assertEqual(code, 1, row)
        self.assertTrue(any("counts the distinct target keys: 2" in d["message"]
                            for d in row["details"]["report"]["diagnostics"]))
        self.write_targets([stock_entry(), survival_entry("diner", placements=99),
                            survival_entry("diner", route="t6-qol")], count=2)
        code, row = invoke(["target", "validate", str(self.ws), "--json"])
        self.assertEqual(code, 1, row)
        self.assertTrue(any("placements says 99 but" in d["message"] for d in row["details"]["report"]["diagnostics"]))
        self.write_targets([stock_entry(), survival_entry("diner", placements=3),
                            survival_entry("diner", route="t6-qol", placements=3)], count=2)
        code, row = invoke(["target", "validate", str(self.ws), "--json"])
        self.assertEqual(code, 0, row)

    def test_a_fence_cites_its_route_script(self):
        entry = survival_entry("diner")
        entry["fence"] = {"zones": ["zone_gas"], "rows": 1, "citations": ["the wiki's Diner room list"]}
        self.write_targets([stock_entry(), entry])
        code, row = invoke(["target", "list", str(self.ws), "--json"])
        self.assertTrue(any("a wiki room label is not a fence" in d["message"] for d in row["result"]["diagnostics"]))
        entry["fence"] = {"zones": ["zone_gas"], "rows": 1, "source": {"file": "scripts/zm/locs/zm_transit_loc_diner.gsc", "line": 9}}
        self.write_targets([stock_entry(), entry])
        code, row = invoke(["target", "list", str(self.ws), "--json"])
        self.assertEqual(row["result"]["diagnostics"], [])

    def test_a_route_table_may_not_be_named_as_a_stock_one(self):
        doc = survival_table("diner", route="t6-qol")
        self.write_table(doc, route="stock")   # <location>.json while the header says t6-qol
        code, row = invoke(["target", "validate", str(self.ws), "--json"])
        self.assertEqual(code, 1, row)
        messages = [d["message"] for d in row["details"]["report"]["diagnostics"]]
        self.assertTrue(any("never share a file" in m for m in messages), messages)


class PlacementsField(unittest.TestCase):
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
        return {"schema": 1, "id": "perk_example", "version": "1.0", "bases": ["b2"], "maps": ["zm_factory"], "recipe": "project.json", **overrides}

    def test_absent_adds_nothing_and_a_valid_field_is_echoed_normalized(self):
        code, row = self.inspect(self.declaration())
        self.assertEqual(code, 0, row)
        self.assertNotIn("placements", row["result"]["metadata"])
        needs = [{"needs": "perk-machine", "occupant": "specialty_armorvest", "count": 1, "fallback": "rotation-slot"},
                 {"needs": "wall-buy", "occupant": "mp9_zm", "count": 1, "fallback": "refuse"},
                 {"needs": "pack-a-punch", "count": 1, "fallback": "refuse"},
                 {"needs": "gobblegum", "count": "any", "fallback": "spawn-room-default"},
                 {"needs": "wunderfizz"}]
        code, row = self.inspect(self.declaration(placements=needs))
        self.assertEqual(code, 0, row)
        echoed = row["result"]["metadata"]["placements"]
        self.assertEqual(echoed[2], {"needs": "pack-a-punch", "occupant": None, "count": 1, "fallback": "refuse"})
        self.assertEqual(echoed[3]["count"], "any")
        self.assertEqual(echoed[4], {"needs": "wunderfizz", "occupant": None, "count": 1, "fallback": "refuse"})
        schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/module-inspect-v1.schema.json").read_text())
        props = schema["$defs"]["moduleMetadata"]["properties"]["placements"]
        self.assertEqual(props["items"]["properties"]["needs"]["enum"], list(targets.KINDS))
        self.assertEqual(props["items"]["properties"]["fallback"]["enum"], list(targets.FALLBACKS))

    def test_defects_are_pointed_at(self):
        for value, field in (
            ({"needs": "perk-machine"}, "/placements"),
            ([{"needs": "teleporter"}], "/placements/0/needs"),
            ([{"needs": "perk-machine", "count": 0}], "/placements/0/count"),
            ([{"needs": "perk-machine", "count": "some"}], "/placements/0/count"),
            ([{"needs": "perk-machine", "count": True}], "/placements/0/count"),
            ([{"needs": "perk-machine", "fallback": "guess"}], "/placements/0/fallback"),
            ([{"needs": "perk-machine", "occupant": ""}], "/placements/0/occupant"),
            ([{"needs": "perk-machine", "where": [1, 2, 3]}], "/placements/0/where"),
            (["perk-machine"], "/placements/0"),
        ):
            code, row = self.inspect(self.declaration(placements=value))
            self.assertEqual(code, 1, row)
            self.assertEqual(row["error_code"], "input_invalid")
            self.assertEqual(row["details"]["inspection"]["diagnostics"][0]["field"], field, value)


class PlacementResolution(unittest.TestCase):
    def modules(self, *needs_lists):
        return [{"id": f"m{i}", "placements": needs} for i, needs in enumerate(needs_lists)]

    def test_occupant_match_first_then_any_free_row_consumed_once(self):
        doc = table()
        doc["placements"].append(literal_row("ex-vending_sleight_b", occupant="specialty_fastreload", origin=(5, 5, 5)))
        result = targets.resolve_placements(self.modules(
            [{"needs": "perk-machine", "occupant": "specialty_fastreload", "count": 1, "fallback": "refuse"}],
            [{"needs": "perk-machine", "occupant": "specialty_armorvest", "count": 1, "fallback": "refuse"}],
            [{"needs": "perk-machine", "occupant": "specialty_rof", "count": 1, "fallback": "rotation-slot"}],
            [{"needs": "perk-machine", "occupant": None, "count": 1, "fallback": "refuse"}]), doc, "dlc5-beta2/zm_factory/zclassic")
        rows = result["needs"]
        self.assertEqual(rows[0]["rows"], ["ex-vending_sleight"]); self.assertTrue(rows[0]["occupant_matched"])
        self.assertEqual(rows[1]["rows"], ["ex-vending_jugg"])
        self.assertEqual(rows[2]["rows"], ["ex-vending_sleight_b"]); self.assertFalse(rows[2]["occupant_matched"])
        self.assertEqual(rows[3]["outcome"], "refused")
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["free_rows"], 3)

    def test_fallback_any_and_no_table(self):
        result = targets.resolve_placements(self.modules(
            [{"needs": "gobblegum", "occupant": None, "count": "any", "fallback": "spawn-room-default"},
             {"needs": "rotation-slot", "occupant": None, "count": 2, "fallback": "omit"},
             {"needs": "perk-machine", "occupant": "specialty_x", "count": 1, "fallback": "rotation-slot"}]), table(), "dlc5-beta2/zm_factory/zclassic")
        by_kind = {r["needs"]: r for r in result["needs"]}
        self.assertEqual(by_kind["gobblegum"]["outcome"], "satisfied")
        self.assertEqual(by_kind["rotation-slot"]["outcome"], "fallback")
        self.assertEqual(by_kind["perk-machine"]["outcome"], "satisfied")
        self.assertEqual(result["outcome"], "passed")
        self.assertIn("1 on fallback", result["detail"])
        # Two perk machines wanted, one left: count 2 with rotation-slot fallback reports the slot rows the table has (none).
        result = targets.resolve_placements(self.modules([{"needs": "perk-machine", "occupant": None, "count": 3, "fallback": "rotation-slot"}]), table(), "t")
        self.assertEqual(result["needs"][0]["outcome"], "fallback")
        self.assertEqual(result["needs"][0]["fallback_rows_in_table"], 0)
        result = targets.resolve_placements(self.modules([{"needs": "perk-machine", "occupant": None, "count": 1, "fallback": "refuse"}]), None, "t")
        self.assertEqual(result["needs"][0]["outcome"], "no_table")
        self.assertEqual(result["outcome"], "not_counted")
        self.assertEqual(targets.resolve_placements([{"id": "m", "placements": None}], table(), "t")["outcome"], "not_counted")


class PlanPlacementsCheck(CompositionFixture):
    """``module plan --workspace W --target KEY``: the check, per target, without generating a provider."""

    def setUp(self):
        super().setUp()
        self.ws = self.root / "workspace"
        (self.ws / "foundations").mkdir(parents=True)
        (self.ws / "registry" / "locations" / "dlc5-beta2" / "zm_factory").mkdir(parents=True)
        (self.ws / "foundations" / "dlc5-beta2.json").write_text(json.dumps({"schema": 1, "id": "dlc5-beta2", "profile_prefix": "b2", "maps": {"zm_factory": {}}}))
        self.table_path = self.ws / "registry/locations/dlc5-beta2/zm_factory/zclassic.json"
        self.table_path.write_text(json.dumps(table()), encoding="utf-8")

    def plan(self, comp, *extra):
        return job_invoke(["module", "plan", str(comp), "--output", self.out(), *extra])

    def test_plan_lists_needs_without_a_target_and_resolves_them_with_one(self):
        self.module("jugg", bases=["b2"], maps=["zm_factory"], placements=[{"needs": "perk-machine", "occupant": "specialty_armorvest", "fallback": "rotation-slot"}])
        self.module("wall", bases=["b2"], maps=["zm_factory"], placements=[{"needs": "wall-buy", "occupant": "mp9_zm", "count": 2, "fallback": "refuse"}])
        self.module("plain", bases=["b2"], maps=["zm_factory"])
        comp = self.composition(["jugg", "wall", "plain"], name="b2_perks_test", base="b2", map_id="zm_factory")
        code, row = self.plan(comp)
        self.assertEqual(code, 0, row)
        placements = row["result"]["placements"]
        self.assertEqual(len(placements), 1)
        self.assertEqual(placements[0]["outcome"], "not_counted")
        self.assertEqual([n["module"] for n in placements[0]["needs"]], ["jugg", "wall"])
        self.assertTrue(all(n["outcome"] == "no_table" for n in placements[0]["needs"]))
        checks = {c["id"]: c for c in row["result"]["checks"]}
        self.assertEqual(checks["placements:b2/zm_factory"]["outcome"], "not_counted")
        plan = json.loads((Path(row["result"]["output"]) / "plan.json").read_text())
        by_module = {r["id"]: r for r in plan["modules"]}
        self.assertEqual(by_module["jugg"]["placements"][0]["needs"], "perk-machine")
        self.assertIsNone(by_module["plain"]["placements"])
        # With the workspace and target: jugg is satisfied by the occupant row; two wall buys are wanted, one wall row exists, fallback refuse.
        code, row = self.plan(comp, "--workspace", str(self.ws), "--target", "dlc5-beta2/zm_factory/zclassic")
        self.assertEqual(code, 1, row)
        self.assertEqual(row["error_code"], "input_invalid")
        check = next(c for c in row["details"]["checks"] if c["id"] == "placements:dlc5-beta2/zm_factory/zclassic")
        self.assertEqual(check["outcome"], "failed")
        receipt = json.loads(Path(row["receipt"]).read_text())
        self.assertIn(str(self.table_path.resolve()), receipt["inputs"], "the consumed table is a hashed input")

    def test_plan_passes_when_every_need_has_a_row_or_fallback_and_reports_per_target(self):
        self.module("jugg", bases=["b2"], maps=["zm_factory"], placements=[{"needs": "perk-machine", "occupant": "specialty_armorvest", "fallback": "refuse"}])
        self.module("gum", bases=["b2"], maps=["zm_factory"], placements=[{"needs": "gobblegum", "count": "any", "fallback": "spawn-room-default"}])
        self.module("wf", bases=["b2"], maps=["zm_factory"], placements=[{"needs": "wunderfizz", "fallback": "omit"}])
        comp = self.composition(["jugg", "gum", "wf"], name="b2_perks_test", base="b2", map_id="zm_factory")
        code, row = self.plan(comp, "--workspace", str(self.ws), "--target", "dlc5-beta2/zm_factory/zclassic", "--target", "dlc5-beta2/zm_factory/zsurvival/lab")
        self.assertEqual(code, 0, row)
        by_target = {p["target"]: p for p in row["result"]["placements"]}
        self.assertEqual(by_target["dlc5-beta2/zm_factory/zclassic"]["outcome"], "passed")
        self.assertEqual({n["module"]: n["outcome"] for n in by_target["dlc5-beta2/zm_factory/zclassic"]["needs"]},
                         {"jugg": "satisfied", "gum": "satisfied", "wf": "fallback"})
        self.assertEqual(by_target["dlc5-beta2/zm_factory/zsurvival/lab"]["outcome"], "not_counted")
        self.assertIsNone(by_target["dlc5-beta2/zm_factory/zsurvival/lab"]["table_path"])
        self.assertFalse((Path(row["result"]["output"]) / "provider").exists(), "no provider module is generated")

    def test_target_argument_rules(self):
        self.module("jugg", bases=["b2"], maps=["zm_factory"], placements=[{"needs": "perk-machine", "fallback": "refuse"}])
        comp = self.composition(["jugg"], name="b2_perks_test", base="b2", map_id="zm_factory")
        code, row = self.plan(comp, "--target", "dlc5-beta2/zm_factory/zclassic")
        self.assertEqual(code, 2, row); self.assertIn("--workspace", row["message"])
        code, row = self.plan(comp, "--workspace", str(self.ws), "--target", "dlc5-beta2/zm_prototype/zclassic")
        self.assertEqual(code, 2, row); self.assertIn("planned for zm_factory", row["message"])
        code, row = self.plan(comp, "--workspace", str(self.ws), "--target", "factory")
        self.assertEqual(code, 2, row)
        doc = table(); doc["facts"]["installed"] = True
        self.table_path.write_text(json.dumps(doc))
        code, row = self.plan(comp, "--workspace", str(self.ws), "--target", "dlc5-beta2/zm_factory/zclassic")
        self.assertEqual(code, 1, row)
        self.assertIn("invalid", row["message"])
        # No member declares placements and no target: nothing is added.
        self.module("plain", bases=["b2"], maps=["zm_factory"])
        code, row = self.plan(self.composition(["plain"], name="b2_plain_test", base="b2", map_id="zm_factory"))
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["placements"], [])
        self.assertFalse(any(c["id"].startswith("placements:") for c in row["result"]["checks"]))

    def test_a_location_two_routes_provide_is_refused_until_one_is_named(self):
        """Two providers of one target are refused at plan time, the way two ``replaceFunc``
        owners of one function are: the plan names the pair and does not merge or pick."""
        for route in ("bo2-reimagined", "t6-qol"):
            key = "dlc5-beta2/zm_factory/zsurvival/lab"
            path = self.ws / targets.table_relpath(key, route)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(table(target=key, location="lab", route=route)), encoding="utf-8")
        self.module("jugg", bases=["b2"], maps=["zm_factory"],
                    placements=[{"needs": "perk-machine", "occupant": "specialty_armorvest", "fallback": "refuse"}])
        comp = self.composition(["jugg"], name="b2_perks_test", base="b2", map_id="zm_factory")
        code, row = self.plan(comp, "--workspace", str(self.ws), "--target", "dlc5-beta2/zm_factory/zsurvival/lab")
        self.assertEqual(code, 2, row)
        self.assertEqual(row["error_code"], "invalid_arguments")
        self.assertIn("provided by 2 routes", row["message"])
        code, row = self.plan(comp, "--workspace", str(self.ws), "--target", "dlc5-beta2/zm_factory/zsurvival/lab@t6-qol")
        self.assertEqual(code, 0, row)
        placement = row["result"]["placements"][0]
        self.assertEqual(placement["route"], "t6-qol")
        self.assertEqual(placement["outcome"], "passed")
        self.assertEqual(placement["table_path"], "registry/locations/dlc5-beta2/zm_factory/zsurvival/lab.t6-qol.json")
        checks = {c["id"]: c for c in row["result"]["checks"]}
        self.assertEqual(checks["placements:dlc5-beta2/zm_factory/zsurvival/lab@t6-qol"]["outcome"], "passed")


class LedgerPerTarget(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"PAT_HOME": str(self.root / "pat-home")})
        self.env.start()
        self.addCleanup(self.env.stop)
        receipt = {"path": ".local/example/build.json", "sha256": "1" * 64}
        rows = [
            {"type": "built-alone", "receipt": receipt, "offline_verified": True, "scope": {"base": "stock", "foundation": "bo2-stock", "map": "zm_transit"}},
            {"type": "built-alone", "receipt": receipt, "offline_verified": True, "scope": {"base": "stock", "foundation": "bo2-stock", "map": "zm_transit", "location": "diner"}},
            {"type": "game-tested", "run": "run-1", "result": "passed", "installed": True, "loaded_and_playable": True,
             "scope": {"base": "stock", "map": "zm_transit", "location": "diner", "mode": "solo"}},
            {"type": "player-accepted", "outcome": "rejected", "record": {"path": "modules/example/docs/ACCEPTED.json"},
             "scope": {"base": "stock", "map": "zm_transit", "location": "town"}},
        ]
        (self.root / "evidence.json").write_text(json.dumps({"schema": 1, "subject": {"id": "example"}, "rows": rows}))
        (self.root / "module.json").write_text(json.dumps({"schema": 1, "id": "example", "version": "1", "bases": ["stock"], "maps": ["zm_transit"], "recipe": "project.json"}))

    def test_by_target_keeps_each_location_apart_and_target_flag_queries_one(self):
        code, row = invoke(["module", "state", "--ledger", str(self.root), "--json"])
        self.assertEqual(code, 0, row)
        by_target = {(t["base"], t["map"], t["location"]): t["facts"] for t in row["result"]["by_target"]}
        self.assertEqual(set(by_target), {("stock", "zm_transit", None), ("stock", "zm_transit", "diner"), ("stock", "zm_transit", "town")})
        self.assertEqual(by_target[("stock", "zm_transit", None)]["installed"]["value"], None)
        self.assertEqual(by_target[("stock", "zm_transit", "diner")]["installed"]["value"], True)
        self.assertEqual(by_target[("stock", "zm_transit", "diner")]["offline_verified"]["rows"], [1])
        self.assertEqual(by_target[("stock", "zm_transit", "town")]["player_accepted"]["value"], False)
        code, row = invoke(["module", "state", "--ledger", str(self.root), "--target", "bo2-stock/zm_transit/zsurvival/diner", "--json"])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["query"], {"base": None, "foundation": "bo2-stock", "map": "zm_transit", "location": "diner", "package": None})
        self.assertEqual(row["result"]["facts"]["offline_verified"]["rows"], [1])
        self.assertIsNone(row["result"]["facts"]["installed"]["value"], "the game-tested Diner row names no foundation, so a foundation query does not see it")
        code, row = invoke(["module", "state", "--ledger", str(self.root), "--target", "bo2-stock/zm_transit/zsurvival/diner", "--map", "zm_nuked", "--json"])
        self.assertEqual(code, 2, row)
        code, row = invoke(["module", "state", "--ledger", str(self.root), "--target", "zm_transit", "--json"])
        self.assertEqual(code, 2, row)

    def test_proposal_keeps_a_verdicts_location(self):
        from plutonium_agent_toolkit.dev import ledger
        self.assertEqual(ledger._scope_from({"base": "stock", "map": "zm_transit", "location": "diner"}, {}),
                         {"base": "stock", "maps": ["zm_transit"], "location": "diner"})
        self.assertEqual(ledger._scope_from({"foundation": "bo2-stock", "map": "zm_transit"}, {"bo2-stock": "stock"}),
                         {"base": "stock", "foundation": "bo2-stock", "maps": ["zm_transit"]})


if __name__ == "__main__":
    unittest.main()
