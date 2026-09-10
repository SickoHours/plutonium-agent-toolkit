"""Backend child helper for Windows: the parent assigns this process to a Job Object
before sending the real argv on stdin, so the whole backend tree inherits the job."""
import json
import subprocess
import sys

line = sys.stdin.buffer.readline(1024 * 1024)
argv = json.loads(line)
if not isinstance(argv, list) or not argv or any(not isinstance(item, str) for item in argv):
    sys.exit(2)
sys.exit(subprocess.call(argv, stdin=subprocess.DEVNULL))
