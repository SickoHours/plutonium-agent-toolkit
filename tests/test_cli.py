"""Contract tests that run on any platform. No backend, network or game access."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from plutonium_agent_toolkit import __version__
from plutonium_agent_toolkit.cli import entry
from plutonium_agent_toolkit.core import config
from plutonium_agent_toolkit.core.discovery import EFFECTS, routes


def invoke(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = entry(argv)
    return code, json.loads(buf.getvalue())


class IsolatedHome(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.previous = os.environ.get("PAT_HOME")
        os.environ["PAT_HOME"] = self.temp.name
        self.addCleanup(self._restore)

    def _restore(self):
        if self.previous is None:
            os.environ.pop("PAT_HOME", None)
        else:
            os.environ["PAT_HOME"] = self.previous


class DiscoveryTests(IsolatedHome):
    def test_version_reports_package_version_and_platform(self):
        code, row = invoke(["version"])
        self.assertEqual(code, 0)
        self.assertTrue(row["ok"])
        self.assertEqual(row["result"]["version"], __version__)
        self.assertIn("native_windows", row["result"]["platform"])

    def test_manifest_lists_every_registered_route_once(self):
        code, row = invoke(["manifest"])
        self.assertEqual(code, 0)
        ids = [r["id"] for r in row["result"]["routes"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), len(routes()))
        for r in row["result"]["routes"]:
            self.assertIn(r["effect"], EFFECTS)
            self.assertIn(r["status"], ("available", "planned", "unsupported"))
            self.assertEqual(r["argv"][:1], ["pat"])

    def test_describe_known_and_unknown_routes(self):
        code, row = invoke(["describe", "dev", "setup"])
        self.assertEqual(code, 0)
        self.assertEqual(row["result"]["id"], "dev.setup")
        code, row = invoke(["describe", "dev", "nope"])
        self.assertEqual(code, 2)
        self.assertEqual(row["error_code"], "unknown_route")

    def test_planned_routes_refuse_with_not_implemented_and_run_nothing(self):
        for argv in (["gsc", "compile", "x.gsc"], ["game", "launch"], ["capture", "start"], ["test", "start"]):
            code, row = invoke(argv)
            self.assertEqual(code, 1, argv)
            self.assertEqual(row["error_code"], "not_implemented", argv)
            self.assertEqual(row["details"]["route"]["status"], "planned")

    def test_usage_errors_exit_two(self):
        code, row = invoke(["definitely-not-a-group"])
        self.assertEqual(code, 2)
        self.assertEqual(row["error_code"], "invalid_arguments")

    def test_every_response_carries_schema_version_and_request_id(self):
        for argv in (["version"], ["describe", "x", "y"], ["game", "info"]):
            _, row = invoke(argv)
            self.assertEqual(row["schema_version"], 1)
            self.assertEqual(row["toolkit_version"], __version__)
            self.assertRegex(row["request_id"], r"^[0-9a-f]{32}$")


class ConfigTests(IsolatedHome):
    def test_configure_requires_absolute_paths_and_rejects_unknown_keys(self):
        code, row = invoke(["configure", "--plutonium-storage-t6", "relative/path"])
        self.assertEqual(code, 1)
        self.assertEqual(row["error_code"], "config_invalid")
        home = Path(self.temp.name)
        (home / "config.json").write_text(json.dumps({"typo_key": str(home)}))
        code, row = invoke(["doctor"])
        self.assertEqual(code, 0)
        self.assertFalse(row["result"]["configuration"]["ok"])
        self.assertEqual(row["result"]["configuration"]["error"]["error_code"], "config_invalid")

    def test_configure_saves_and_doctor_reads_back(self):
        storage = Path(self.temp.name) / "storage" / "t6"
        storage.mkdir(parents=True)
        code, row = invoke(["configure", "--plutonium-storage-t6", str(storage)])
        self.assertEqual(code, 0)
        self.assertEqual(row["result"]["saved"], ["plutonium_storage_t6"])
        self.assertEqual(config.load()["plutonium_storage_t6"], str(storage))
        code, row = invoke(["doctor"])
        self.assertEqual(code, 0)
        self.assertEqual(row["result"]["configuration"]["config"]["plutonium_storage_t6"], str(storage))
        # Nothing is installed, so doctor's overall ok is False even where the platform is supported.
        self.assertFalse(row["result"]["backends"]["ok"])

    def test_setup_plan_never_downloads_and_setup_requires_windows_elsewhere(self):
        code, row = invoke(["dev", "setup", "--plan"])
        self.assertEqual(code, 0)
        self.assertTrue(row["result"]["plan"])
        self.assertFalse(row["result"]["executes_installers"])
        self.assertTrue(all(not p["optional"] for p in row["result"]["programs"]))
        if os.name != "nt":
            code, row = invoke(["dev", "setup", "--only", "gsc"])
            self.assertEqual(code, 1)
            self.assertEqual(row["error_code"], "unsupported_platform")


if __name__ == "__main__":
    unittest.main()
