"""The protocol strings results carry, and the manifest's claim about them.

A reader on the other side of a route pins a literal (`pat.module-inspect/1`) and refuses a
result it does not recognize. That only works if the manifest's `result_protocol` and the
strings the code actually emits are the same set, so both directions are checked here: no row
may name a protocol no source file emits, and no source file may emit a protocol this file
does not know about. A new protocol fails this test until it is listed here and, if a route
returns it, on that route's row.
"""
import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from plutonium_agent_toolkit.cli import entry
from plutonium_agent_toolkit.core import source
from plutonium_agent_toolkit.core.discovery import routes

SRC = Path(__file__).resolve().parent.parent / "src" / "plutonium_agent_toolkit"
LITERAL = re.compile(r'"(pat\.[a-z-]+/[0-9]+)"|\'(pat\.[a-z-]+/[0-9]+)\'')

# Every protocol string the toolkit emits. `pat.module-ledger/1` has no row of its own: it is
# what `module state --ledger` answers with, the other half of a route whose row names the
# derived-state protocol instead.
KNOWN = {
    "pat.module-accept/1",
    "pat.module-changelog/1",
    "pat.module-inspect/1",
    "pat.module-ledger-add/1",
    "pat.module-ledger-proposal/1",
    "pat.module-ledger/1",
    "pat.module-plan/1",
    "pat.module-qualify/1",
    "pat.module-state/1",
    "pat.module-verify/1",
    "pat.target/1",
    "pat.test-plan/1",
    "pat.work-status/1",
    "pat.workspace-catalog/1",
}


def emitted():
    """Protocols the code produces. `routes.py` is excluded on purpose: it declares the claim,
    so counting it would let a row vouch for itself."""
    found = set()
    for path in SRC.rglob("*.py"):
        if path.name == "routes.py":
            continue
        for a, b in LITERAL.findall(path.read_text(encoding="utf-8")):
            found.add(a or b)
    return found


def invoke(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = entry(argv)
    return code, json.loads(buf.getvalue())


class ResultProtocolTests(unittest.TestCase):
    def test_source_emits_exactly_the_known_protocols(self):
        self.assertEqual(emitted(), KNOWN)

    def test_every_route_row_carries_the_field(self):
        for route in routes():
            row = route.to_dict()
            self.assertIn("result_protocol", row, route.id)
            self.assertTrue(row["result_protocol"] is None or isinstance(row["result_protocol"], str), route.id)

    def test_named_protocols_are_emitted_somewhere_in_src(self):
        live = emitted()
        named = {r.id: r.result_protocol for r in routes() if r.result_protocol}
        self.assertTrue(named)
        for route_id, protocol in named.items():
            self.assertIn(protocol, live, route_id)

    def test_plan_and_state_rows_name_the_connection_protocols(self):
        by_id = {r.id: r.result_protocol for r in routes()}
        self.assertEqual(by_id["module.plan"], "pat.module-plan/1")
        self.assertEqual(by_id["module.state"], "pat.module-state/1")

    def test_manifest_json_carries_result_protocol_on_every_row(self):
        with tempfile.TemporaryDirectory() as home:
            previous = os.environ.get("PAT_HOME")
            os.environ["PAT_HOME"] = home
            try:
                code, doc = invoke(["manifest", "--json"])
            finally:
                if previous is None:
                    os.environ.pop("PAT_HOME", None)
                else:
                    os.environ["PAT_HOME"] = previous
        self.assertEqual(code, 0)
        rows = doc["result"]["routes"]
        self.assertTrue(all("result_protocol" in row for row in rows))
        self.assertEqual({row["result_protocol"] for row in rows if row["result_protocol"]} - KNOWN, set())


class SourceIdentityTests(unittest.TestCase):
    def test_this_checkout_reports_its_commit(self):
        identity = source.identity()
        self.assertEqual(set(identity), {"source_commit", "dirty"})
        if identity["source_commit"] is None:
            self.assertIsNone(identity["dirty"])
            return
        self.assertRegex(identity["source_commit"], r"^[0-9a-f]{40}$")
        self.assertIsInstance(identity["dirty"], bool)

    def test_a_directory_outside_a_checkout_is_unknown(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(source.identity(Path(empty) / "plutonium_agent_toolkit"),
                             {"source_commit": None, "dirty": None})

    def test_never_raises_when_git_is_unusable(self):
        previous = os.environ.get("PATH")
        os.environ["PATH"] = ""
        try:
            self.assertEqual(source.identity(), {"source_commit": None, "dirty": None})
        finally:
            if previous is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = previous

    def test_version_result_carries_both_fields(self):
        with tempfile.TemporaryDirectory() as home:
            previous = os.environ.get("PAT_HOME")
            os.environ["PAT_HOME"] = home
            try:
                code, doc = invoke(["version", "--json"])
            finally:
                if previous is None:
                    os.environ.pop("PAT_HOME", None)
                else:
                    os.environ["PAT_HOME"] = previous
        self.assertEqual(code, 0)
        result = doc["result"]
        self.assertIn("source_commit", result)
        self.assertIn("dirty", result)
        self.assertTrue(result["source_commit"] is None or re.fullmatch(r"[0-9a-f]{40}", result["source_commit"]))
        self.assertTrue(result["dirty"] is None or isinstance(result["dirty"], bool))


if __name__ == "__main__":
    unittest.main()
