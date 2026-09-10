import json
import tempfile
import unittest
from pathlib import Path

from plutonium_agent_toolkit.core import receipts
from plutonium_agent_toolkit.core.errors import Failure


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_output_dir_must_be_new(self):
        out = receipts.new_output_dir(self.root / "job-1")
        self.assertTrue(out.is_dir())
        with self.assertRaises(Failure) as ctx:
            receipts.new_output_dir(out)
        self.assertEqual(ctx.exception.code, "output_exists")

    def test_receipt_round_trip_and_verify_detects_change(self):
        out = receipts.new_output_dir(self.root / "job-2")
        (out / "mod.ff").write_bytes(b"fastfile")
        outputs = receipts.inventory(out)
        path = receipts.write(out, command="ff link", argv=["pat", "ff", "link"], status="succeeded", exit_code=0,
                              inputs={"zone.txt": "0" * 64}, outputs=outputs)
        row = json.loads(path.read_text())
        self.assertEqual(row["status"], "succeeded")
        self.assertRegex(row["job_id"], r"^[0-9a-f]{32}$")
        self.assertTrue(receipts.verify_outputs(path)["verified"])
        (out / "mod.ff").write_bytes(b"changed")
        report = receipts.verify_outputs(path)
        self.assertFalse(report["verified"])
        self.assertEqual(report["changed"], ["mod.ff"])


if __name__ == "__main__":
    unittest.main()
