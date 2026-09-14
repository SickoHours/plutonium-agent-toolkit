"""`pat manifest` must name the declared function-replacement fields on the module routes.

An agent discovers the replacement contract from discovery data before it reads a declaration;
if the notes omit the field names, the contract is invisible until a plan fails.
"""
import unittest

from plutonium_agent_toolkit.core import discovery
from tests.test_dev_routes import invoke

FIELDS = ("replaces.functions", "replaces.files", "entry.replace", "entry.register")


class ReplacementManifestData(unittest.TestCase):
    def rows(self):
        import plutonium_agent_toolkit.cli  # noqa: F401  (registers every routes.py)
        return {r["id"]: r for r in discovery.manifest({"supported": True})["routes"]}

    def test_module_inspect_notes_name_every_replacement_field(self):
        notes = self.rows()["module.inspect"]["notes"]
        for field in FIELDS:
            self.assertIn(field, notes)

    def test_module_plan_notes_name_every_replacement_field(self):
        notes = self.rows()["module.plan"]["notes"]
        for field in FIELDS:
            self.assertIn(field, notes)

    def test_notes_state_the_declaration_limits(self):
        inspect_notes = self.rows()["module.inspect"]["notes"]
        self.assertIn("256", inspect_notes)
        self.assertIn("64", inspect_notes)


class ReplacementManifestRoute(unittest.TestCase):
    def test_invoke_manifest_exposes_the_same_notes(self):
        code, row = invoke(["manifest"])
        self.assertEqual(code, 0, row)
        by_id = {r["id"]: r for r in row["result"]["routes"]}
        for rid in ("module.inspect", "module.plan"):
            for field in FIELDS:
                self.assertIn(field, by_id[rid]["notes"], f"{rid} must name {field}")


if __name__ == "__main__":
    unittest.main()
