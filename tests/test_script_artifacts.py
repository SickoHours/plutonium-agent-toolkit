"""Synthetic header-v1 fixtures; no game assets or private compiler inputs."""
from pathlib import Path

from plutonium_agent_toolkit.core.errors import Failure
from plutonium_agent_toolkit.dev.script_artifacts import check_t6_string_pool, T6_PC_MAGIC
from tests.test_dev_routes import DevRouteFixture, invoke


def artifact(pool):
    header = bytearray(64)
    header[:8] = T6_PC_MAGIC
    header[12:16] = (64 + len(pool)).to_bytes(4, "little")
    return bytes(header) + pool


class ScriptArtifactTests(DevRouteFixture):
    def check(self, data):
        path = self.root / "synthetic.gsc"
        path.write_bytes(data)
        return check_t6_string_pool(path)

    def test_65535_start_passes_even_when_final_string_extends_past_limit(self):
        result = self.check(artifact(b"a" * (65535 - 64 - 1) + b"\0final\0"))
        self.assertEqual(result["maximum_string_start"], 65535)
        self.assertGreater(result["pool_end"], 65535)

    def test_65536_start_fails(self):
        with self.assertRaises(Failure) as caught:
            self.check(artifact(b"a" * (65536 - 64 - 1) + b"\0bad\0"))
        self.assertEqual(caught.exception.code, "backend_failed")
        self.assertEqual(caught.exception.details["string_start"], 65536)

    def test_wrap_collision_with_valid_earlier_start_still_fails(self):
        # 65600 truncates to64, which names the first valid string. A lookup-only
        # disassembly check could succeed while silently reading the wrong string.
        with self.assertRaises(Failure) as caught:
            self.check(artifact(b"a" * (65600 - 64 - 1) + b"\0collision\0"))
        self.assertEqual(caught.exception.details["string_start"] & 0xFFFF, 64)

    def test_single_long_string_is_representable(self):
        self.assertEqual(self.check(artifact(b"a" * 70000 + b"\0"))["maximum_string_start"], 64)

    def test_empty_pool(self):
        self.assertIsNone(self.check(artifact(b""))["maximum_string_start"])

    def test_malformed_boundaries_magic_and_unterminated_pool(self):
        too_low = bytearray(artifact(b"ok\0")); too_low[12:16] = (63).to_bytes(4, "little")
        too_high = bytearray(artifact(b"ok\0")); too_high[12:16] = (999).to_bytes(4, "little")
        for data in (b"", b"x" * 64, bytes(too_low), bytes(too_high), artifact(b"unterminated")):
            with self.subTest(data=data[:16]):
                with self.assertRaises(Failure):
                    self.check(data)

    def test_compile_failure_receipt_server_and_client(self):
        for suffix in ("gsc", "csc"):
            src = self.root / ("overflow." + suffix)
            src.write_text("init() {} // STRING_POOL_OVERFLOW")
            output = self.out()
            code, row = invoke(["gsc", "compile", str(src), "--output", output])
            self.assertEqual(code, 1, row)
            self.assertEqual(row["error_code"], "backend_failed")
            self.assertEqual(row["details"]["check"], "t6-string-pool")
            import json
            self.assertEqual(json.loads((Path(output) / "receipt.json").read_text())["status"], "failed")

    def test_success_records_check_but_dry_run_and_iw5_do_not_claim_one(self):
        src = self.root / "ok.gsc"; src.write_text("init() {}")
        code, row = invoke(["gsc", "compile", str(src), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["artifact_checks"][0]["check"], "t6-string-pool")
        code, row = invoke(["gsc", "check", str(src), "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertNotIn("artifact_checks", row["result"])
        code, row = invoke(["gsc", "compile", str(src), "--game", "iw5", "--output", self.out()])
        self.assertEqual(code, 0, row)
        self.assertEqual(row["result"]["artifact_checks"], [])

    def test_project_build_refuses_before_staging_or_linking(self):
        code, row = invoke(["project", "init", "--name", "overflow_project", "--output", self.out()])
        self.assertEqual(code, 0, row)
        project = Path(row["result"]["output"])
        source = next((project / "scripts").glob("*.gsc"))
        source.write_text(source.read_text() + "\n// STRING_POOL_OVERFLOW\n")
        output = self.out()
        code, row = invoke(["project", "build", str(project / "project.json"), "--output", output])
        self.assertEqual(code, 1, row)
        self.assertEqual(row["details"]["check"], "t6-string-pool")
        self.assertFalse((Path(output) / "packages" / "mod.ff").exists())
