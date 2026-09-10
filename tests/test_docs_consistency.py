"""Guardrails for the agent-facing docs. Cheap checks that turned two review findings into tests.

These keep AGENTS.md and FOR-AGENTS.md honest without a human re-reading them every change:
the credentials prohibition cannot silently vanish again, and the route-status vocabulary cannot
drift from the code or get conflated with SUPPORT.md's evidence levels.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS = {"available", "implemented", "planned", "deferred", "unsupported"}
EVIDENCE = {"contract", "offline", "native", "game", "accepted"}
# Every document a user or their agent reads before trusting a platform claim.
USER_DOCS = ("README.md", "SETUP-PROMPT.md", "docs/GETTING-STARTED.md", "docs/SUPPORT.md",
             "skills/plutonium-agent-toolkit/SKILL.md", "AGENTS.md", "docs/FOR-AGENTS.md", "CONTRIBUTING.md",
             "examples/hello-zm/README.md", "pyproject.toml")
UNBACKED = ("any OS", "any operating system", "macOS", "Mac OS", "OS X", "MacOS", "darwin")
QUALIFIERS = ("untested", "not claimed", "not supported", "no pinned", "no pins")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


class DocsConsistencyTests(unittest.TestCase):
    def test_route_status_vocabulary_matches_the_code(self):
        from plutonium_agent_toolkit.core import discovery

        self.assertEqual(set(discovery.STATUS), STATUS, "STATUS changed; update the agent docs too")

    def test_agents_md_forbids_credentials(self):
        text = read("AGENTS.md").lower()
        self.assertTrue(
            ("password" in text and "token" in text and ("credential" in text or "login" in text)),
            "AGENTS.md must explicitly forbid asking for or using passwords, tokens and credentials",
        )

    def test_support_is_named_canonical_for_evidence_levels(self):
        for doc in ("AGENTS.md", "docs/FOR-AGENTS.md"):
            text = read(doc)
            self.assertIn("docs/SUPPORT.md" if doc == "AGENTS.md" else "SUPPORT.md", text, doc)
            self.assertRegex(text, r"(?i)canonical", f"{doc} should defer to SUPPORT.md as canonical for evidence levels")

    def test_support_matrix_defines_every_evidence_level(self):
        text = read("docs/SUPPORT.md")
        for level in EVIDENCE:
            self.assertRegex(text, rf"(?m)^\|\s*{level}\s*\|", f"SUPPORT.md evidence table missing {level}")

    def test_claude_md_imports_agents(self):
        self.assertIn("@AGENTS.md", read("CLAUDE.md"))

    def test_for_agents_doc_exists_and_is_linked(self):
        self.assertTrue((ROOT / "docs/FOR-AGENTS.md").is_file())
        self.assertIn("docs/FOR-AGENTS.md", read("AGENTS.md"))

    def test_no_unbacked_platform_claims(self):
        # macOS has no pinned backends and no receipt; "any OS" would claim it. A line may name
        # macOS only to say it is untested / not claimed / has no pins.
        for doc in USER_DOCS:
            for number, line in enumerate(read(doc).splitlines(), 1):
                if any(phrase in line for phrase in UNBACKED) and not any(q in line for q in QUALIFIERS):
                    self.fail(f"{doc}:{number}: unbacked platform claim: {line.strip()[:120]}")

    def test_support_platform_table_names_both_supported_hosts(self):
        text = read("docs/SUPPORT.md")
        self.assertIn("Windows 11", text)
        self.assertRegex(text, r"Arch Linux \(Omarchy\)")
        self.assertRegex(text, r"(?m)^\| macOS \|.*untested")

    def test_support_links_only_receipts_that_exist(self):
        text = read("docs/SUPPORT.md")
        for rel in set(re.findall(r"\]\((receipts/[^)]+\.json)\)", text)):
            self.assertTrue((ROOT / "docs" / rel).is_file(), rel)

    def test_no_arbitrary_console_promise_anywhere_in_agent_docs(self):
        # The no-escape-hatch rule must not be contradicted by the malleability language.
        for doc in ("AGENTS.md", "docs/FOR-AGENTS.md", "skills/plutonium-agent-toolkit/SKILL.md"):
            text = read(doc).lower()
            self.assertIn("escape hatch", text, f"{doc} should keep the no-arbitrary-console rule explicit")


if __name__ == "__main__":
    unittest.main()
