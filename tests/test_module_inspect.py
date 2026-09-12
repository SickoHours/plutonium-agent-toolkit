"""Producer fixtures for pat.module-inspect/1, using only synthetic declarations."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from plutonium_agent_toolkit import cli
from plutonium_agent_toolkit.core.errors import Failure
from plutonium_agent_toolkit.dev import compositions as c

ROOT = Path(__file__).resolve().parents[1]
MODULE = {"schema": 1, "id": "alpha", "version": "1.0", "bases": ["stock"], "maps": ["*"], "recipe": "project.json"}
PACK = {"schema": 1, "name": "stock_alpha_probe", "base": "stock", "map": "zm_transit", "modules": ["../alpha"]}


def invoke(path):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = cli.entry(["module", "inspect", str(path), "--json"])
    return code, json.loads(output.getvalue())


class InspectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"PAT_HOME": str(self.root / "pat-home")})
        self.env.start()
        self.addCleanup(self.env.stop)

    def write(self, data, name="module.json"):
        path = self.root / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def check_failure(self, data, field, name="module.json", code="input_invalid"):
        path = self.write(data, name)
        status, row = invoke(path)
        self.assertEqual(status, 1, row)
        self.assertEqual(row["error_code"], code, row)
        result = row["details"]["inspection"]
        self.assertEqual(result["file"], str(path))
        self.assertEqual(result["validation"], "invalid")
        self.assertIsNone(result["metadata"])
        self.assertEqual(result["diagnostics"][0]["field"], field, row)
        self.assertEqual(result["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        validator = c.validate_declaration_metadata if name == "module.json" else c.validate_composition_metadata
        with self.assertRaises(Failure) as caught:
            validator(data)
        self.assertEqual(caught.exception.code, row["error_code"])
        self.assertEqual(caught.exception.message, row["message"])
        self.assertEqual(caught.exception.details["field"], field)
        return row

    def test_declarations_without_payloads_and_exact_default_projection(self):
        path = self.write(MODULE)
        code, row = invoke(path)
        self.assertEqual(code, 0, row)
        self.assertEqual(row["schema_version"], 1)
        self.assertEqual(row["command"], "module inspect")
        self.assertRegex(row["request_id"], r"^[0-9a-f]{32}$")
        self.assertIn("at", row)
        self.assertIn("toolkit_version", row)
        result = row["result"]
        self.assertEqual(result["protocol"], "pat.module-inspect/1")
        self.assertEqual(result["validation_scope"], "declaration-only")
        self.assertEqual(result["validation"], "metadata-valid")
        self.assertEqual(result["diagnostics"], [])
        self.assertEqual(result["metadata"], {
            "id": "alpha", "version": "1.0", "game": "t6", "title": "alpha", "category": "module", "kind": None,
            "tags": [], "bases": ["stock"], "maps": ["*"], "dependencies": [], "conflicts": [], "origin": None,
            "donor": None, "distribution": "source", "menu_route": "", "payload": "recipe"})
        seed = dict(MODULE)
        seed.pop("recipe")
        seed["seed"] = "seed.json"
        for distribution in ("seed", "private", "source"):
            seed["distribution"] = distribution
            code, row = invoke(self.write(seed))
            self.assertEqual(code, 0, row)
            self.assertEqual(row["result"]["metadata"]["payload"], "seed")
            self.assertNotIn("provides", row["result"]["metadata"])
        self.assertFalse((self.root / "project.json").exists())
        self.assertFalse((self.root / "seed.json").exists())

    def test_composition_keeps_declared_order_and_omitted_metadata_is_validated(self):
        data = PACK | {"modules": [{"path": "../z", "role": "base"}, "../a",
                                  {"name": "owner/beta", "commit": "a" * 40, "path": "../missing"}],
                       "loads": ["../missing/base.ff"], "base_owned": ["../missing/list.txt"],
                       "budget": {"threads": 2}, "zone_header": [">level.ipak_read,common_zm"],
                       "decisions": [{"collision": "script,x", "owner": "alpha", "reason": ""}]}
        code, row = invoke(self.write(data, "composition.json"))
        self.assertEqual(code, 0, row)
        result = row["result"]["metadata"]
        self.assertEqual(result, {"name": "stock_alpha_probe", "title": "stock_alpha_probe", "game": "t6", "tags": [],
                                 "base": "stock", "map": "zm_transit", "origin": None, "donor": None,
                                 "members": [{"path": "../z", "role": "base", "name": None, "commit": None},
                                             {"path": "../a", "role": "module", "name": None, "commit": None},
                                             {"path": "../missing", "role": "module", "name": "owner/beta", "commit": "a" * 40}]})
        self.assertEqual(c.validate_composition_metadata(data)["decisions"][0]["reason"], "")
        self.assertEqual(c.validate_composition_metadata(data | {"tags": ["tag", "tag"]})["tags"], ["tag", "tag"])

    def test_module_field_decisions_match_authoritative_metadata_checks(self):
        cases = [("schema", 2, "/schema"), ("id", "BAD", "/id"), ("game", [], "/game"),
                 ("version", "", "/version"), ("title", " ", "/title"), ("category", "BAD", "/category"),
                 ("kind", "bad_kind", "/kind"), ("tags", ["x", "x"], "/tags"),
                 ("recipe", "../outside.json", "/recipe"), ("distribution", "private", "/distribution"),
                 ("bases", [{}], "/bases"), ("maps", [{}], "/maps"), ("menu_route", None, "/menu_route"),
                 ("source", {"repository": "http://example.invalid"}, "/source/repository"),
                 ("source", {"repository": "https://example.invalid", "commit": "x"}, "/source/commit"),
                 ("source", {"repository": "https://example.invalid", "extra/key~": 1}, "/source/extra~1key~0"),
                 ("dependencies", ["alpha"], "/dependencies/0"), ("conflicts", [5], "/conflicts/0"),
                 ("resource_contract", {"threads": True}, "/resource_contract/threads"),
                 ("resource_contract", {"extra": 1}, "/resource_contract/extra"),
                 ("provides", {"weapons": [1]}, "/provides/weapons"), ("provides", {"extra": []}, "/provides/extra"),
                 ("origin", "BAD", "/origin"), ("donor", "a\nb", "/donor"), ("extra/key~", 1, "/extra~1key~0")]
        for key, value, field in cases:
            with self.subTest(key=key, value=value):
                self.check_failure(MODULE | {key: value}, field)
        missing = dict(MODULE)
        missing.pop("version")
        self.check_failure(missing, "/version")
        row = self.check_failure(MODULE | {"unexpected": 1}, "/unexpected")
        self.assertIn("unexpected", row["message"])

    def test_composition_field_decisions_match_authoritative_metadata_checks(self):
        cases = [("schema", 2, "/schema"), ("name", "bad", "/name"), ("base", "bad-base", "/base"),
                 ("map", "*", "/map"), ("game", "unknown", "/game"), ("title", "", "/title"),
                 ("tags", [1], "/tags"), ("modules", [], "/modules"),
                 ("modules", [{"path": "../a", "role": "invalid"}], "/modules/0/role"),
                 ("modules", [{"path": "/absolute"}], "/modules/0/path"),
                 ("modules", [{"path": "../a", "extra": 1}], "/modules/0/extra"),
                 ("modules", [{"name": "bad"}], "/modules/0/name"),
                 ("modules", [{"name": "owner/a", "commit": "bad"}], "/modules/0/commit"),
                 ("modules", [{"commit": "a" * 40, "path": "../a"}], "/modules/0/commit"),
                 ("loads", [3], "/loads/0"), ("base_owned", [3], "/base_owned/0"),
                 ("budget", {"hud": -1}, "/budget/hud"), ("zone_header", ["bad"], "/zone_header"),
                 ("decisions", [{"collision": "x", "owner": "BAD"}], "/decisions/0/owner"),
                 ("decisions", [{"collision": "x", "owner": "alpha", "reason": None}], "/decisions/0/reason"),
                 ("decisions", [{"collision": "x", "owner": "alpha", "extra": 1}], "/decisions/0/extra")]
        for key, value, field in cases:
            with self.subTest(key=key, value=value):
                self.check_failure(PACK | {key: value}, field, "composition.json")
        self.check_failure(PACK | {"modules": ["../a", {"name": "owner/beta", "commit": "b" * 40}]},
                           "/modules/1/path", "composition.json", "input_missing")

    def test_bad_json_unknown_shape_unreadable_symlink_directory_and_oversize(self):
        for raw in (b'{', b'\xff', b'[' * 2000):
            with self.subTest(raw=raw[:10]):
                path = self.root / "module.json"
                path.write_bytes(raw)
                code, row = invoke(path)
                self.assertEqual(code, 1, row)
                result = row["details"]["inspection"]
                self.assertEqual(result["diagnostics"][0]["field"], "/")
                self.assertEqual(result["sha256"], hashlib.sha256(raw).hexdigest())
        path = self.write({}, "unknown.json")
        self.assertEqual(invoke(path)[1]["details"]["inspection"]["kind"], "unknown")
        target = self.write(MODULE)
        link = self.root / "link.json"
        link.symlink_to(target)
        large = self.root / "large.json"
        large.write_bytes(b" " * (c.MAX_DECLARATION_BYTES + 1))
        for path, error in [(link, "input_missing"), (self.root, "input_missing"),
                            (self.root / "missing.json", "input_missing"), (large, "input_limit")]:
            with self.subTest(path=path):
                code, row = invoke(path)
                self.assertEqual(code, 1, row)
                self.assertEqual(row["error_code"], error)
                self.assertIsNone(row["details"]["inspection"]["sha256"])
        with patch.object(c.os, "open", side_effect=PermissionError("denied")):
            self.assertIsNone(invoke(target)[1]["details"]["inspection"]["sha256"])

    def test_hash_is_the_exact_single_read_parsed_bytes_even_if_path_changes(self):
        path = self.write(MODULE)
        raw = (json.dumps(MODULE, indent=2) + "\n").encode()
        real_loads = json.loads
        def parse(text):
            path.write_text("invalid after read")
            return real_loads(text)
        with patch.object(c, "_read_inspection", return_value=raw) as read, patch.object(c.json, "loads", side_effect=parse):
            result = c.inspect(path)
        read.assert_called_once_with(path)
        self.assertEqual(result["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["metadata"]["id"], "alpha")
        raw = json.dumps(MODULE).encode()
        path.write_bytes(raw + b" " * (c.MAX_DECLARATION_BYTES - len(raw)))
        self.assertEqual(invoke(path)[0], 0)

    def test_inert_no_job_payload_discovery_process_network_or_state_writes(self):
        path = self.write(MODULE)
        before = sorted(self.root.rglob("*"))
        with contextlib.ExitStack() as stack:
            for target in ("plutonium_agent_toolkit.cli.run_job", "plutonium_agent_toolkit.core.jobs.Job.__init__",
                           "plutonium_agent_toolkit.core.config.load", "plutonium_agent_toolkit.dev.compositions.executable",
                           "plutonium_agent_toolkit.dev.seeds.load_manifest", "plutonium_agent_toolkit.dev.projects.load_recipe",
                           "subprocess.Popen", "socket.socket", "urllib.request.urlopen"):
                stack.enter_context(patch(target, side_effect=AssertionError(target)))
            self.assertEqual(invoke(path)[0], 0)
        self.assertEqual(sorted(self.root.rglob("*")), before)
        self.assertFalse(cli.is_job("module", "inspect"))
        self.assertTrue(cli.is_job("module", "plan"))
        self.assertTrue(cli.is_job("module", "build"))
        route = cli.find("module", "inspect")
        self.assertEqual((route.effect, route.status), ("inert", "implemented"))
        with self.assertRaises(Failure):
            cli.build_parser().parse_args(["module", "inspect", str(path), "--output", "unused"])

    def test_real_source_cli_uses_isolated_home_and_emits_one_envelope(self):
        path = self.write(MODULE)
        env = os.environ | {"PYTHONPATH": str(ROOT / "src"), "PAT_HOME": str(self.root / "isolated-home"),
                            "PYTHONDONTWRITEBYTECODE": "1"}
        proc = subprocess.run([sys.executable, "-m", "plutonium_agent_toolkit", "module", "inspect", str(path), "--json"],
                              env=env, cwd=self.root, capture_output=True, text=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        self.assertEqual(json.loads(proc.stdout)["result"]["metadata"]["id"], "alpha")
        self.assertFalse(Path(env["PAT_HOME"]).exists())

    def test_producer_schema_required_fields_match_success_and_failure_fixtures(self):
        schema = json.loads((ROOT / "schemas/module-inspect-v1.schema.json").read_text())
        for data, name, definition in [(MODULE, "module.json", "moduleMetadata"), (PACK, "composition.json", "compositionMetadata")]:
            _, row = invoke(self.write(data, name))
            self.assertEqual(set(row), set(schema["required"]) | {"result"})
            self.assertEqual(set(row["result"]), set(schema["$defs"]["inspection"]["required"]))
            metadata_schema = schema["$defs"][definition]
            self.assertEqual(set(row["result"]["metadata"]), set(metadata_schema["required"]))
            self.assertFalse(metadata_schema["additionalProperties"])
        row = self.check_failure(MODULE | {"extra": 1}, "/extra")
        self.assertEqual(set(row), set(schema["required"]) | {"error_code", "message", "details"})
        self.assertEqual(schema["$defs"]["inspection"]["properties"]["protocol"]["const"], "pat.module-inspect/1")
