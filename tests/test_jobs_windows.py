"""Native Windows behaviour of the job runner (skipped elsewhere).

Found on the first native qualification run: a backend tree terminated through the Job
Object keeps its inherited handle to the step log for up to a scheduler tick after
``process.wait()`` returns, so deleting the job directory right after ``run()`` failed with
ERROR_SHARING_VIOLATION about one time in ten.
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from plutonium_agent_toolkit.core import jobs
from plutonium_agent_toolkit.core.errors import BACKEND_TIMEOUT, Failure


@unittest.skipUnless(os.name == "nt", "Windows Job Object runner only")
class WindowsJobRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_wait_until_released_blocks_while_another_handle_is_open(self):
        from plutonium_agent_toolkit.core import _winjob

        path = self.root / "held.log"
        path.write_bytes(b"x")
        with path.open("ab"):
            started = time.monotonic()
            self.assertFalse(_winjob.wait_until_released(path, timeout=0.2))
            self.assertGreaterEqual(time.monotonic() - started, 0.2)
        self.assertTrue(_winjob.wait_until_released(path, timeout=0.2))
        self.assertTrue(_winjob.wait_until_released(self.root / "missing.log", timeout=0.2))

    def test_timed_out_backend_leaves_step_log_deletable_immediately(self):
        sleeper = [sys.executable, "-c", "import time; time.sleep(5)"]
        for i in range(12):
            job = jobs.Job(self.root / f"job-{i:02d}", "test", ["test"], timeout=30)
            with self.assertRaises(Failure) as caught:
                job.run(sleeper, timeout=0.25)
            self.assertEqual(caught.exception.code, BACKEND_TIMEOUT)
            os.unlink(job.root / "step-01.log")  # must not raise ERROR_SHARING_VIOLATION


if __name__ == "__main__":
    unittest.main()
