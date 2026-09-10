import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReleaseToolTests(unittest.TestCase):
    def run_tool(self, name, *args):
        proc = subprocess.run([sys.executable, str(ROOT / "tools" / name), *args], capture_output=True, text=True, cwd=ROOT)
        return proc.returncode, json.loads(proc.stdout)

    def test_private_scan_is_clean(self):
        code, report = self.run_tool("private_scan.py")
        self.assertEqual(code, 0, json.dumps(report.get("hits"), indent=1))

    def test_release_check_agrees_on_version(self):
        code, report = self.run_tool("release_check.py")
        self.assertEqual(code, 0, report.get("problems"))
        code, report = self.run_tool("release_check.py", "--tag", report["expected_tag"])
        self.assertEqual(code, 0, report.get("problems"))
        code, report = self.run_tool("release_check.py", "--tag", "v9.9.9")
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
