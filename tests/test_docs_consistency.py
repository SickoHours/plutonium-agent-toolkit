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

    def test_knowledge_index_lists_only_existing_pages_and_every_page(self):
        index = read("docs/knowledge/README.md")
        pages = sorted(p.name for p in (ROOT / "docs/knowledge").glob("*.md") if p.name != "README.md")
        self.assertTrue(pages)
        for name in pages:
            self.assertIn(f"]({name})", index, f"docs/knowledge/README.md does not link {name}")
        for name in re.findall(r"\]\(([A-Za-z0-9_.-]+\.md)\)", index):
            self.assertTrue((ROOT / "docs/knowledge" / name).is_file(), name)
        for name in pages:
            lines = read(f"docs/knowledge/{name}").splitlines()
            self.assertLessEqual(len(lines), 150, f"{name}: knowledge pages stay under 150 lines")

    def test_playbooks_have_the_five_sections_and_name_only_registered_routes(self):
        import plutonium_agent_toolkit.cli  # noqa: F401  (imports every routes.py, populating the registry)
        from plutonium_agent_toolkit.core.discovery import routes

        registered = {f"{r.group} {r.action}" for r in routes()}
        index = read("docs/playbooks/README.md")
        books = sorted(p.name for p in (ROOT / "docs/playbooks").glob("*.md") if p.name != "README.md")
        self.assertTrue(books)
        headings = ["## Preconditions", "## Steps", "## Do not", "## Stop conditions", "## Report"]
        for name in books:
            self.assertIn(f"]({name})", index, f"docs/playbooks/README.md does not link {name}")
            text = read(f"docs/playbooks/{name}")
            positions = [text.find(h + "\n") for h in headings]
            self.assertTrue(all(pos >= 0 for pos in positions), f"{name}: missing one of {headings}")
            self.assertEqual(positions, sorted(positions), f"{name}: sections out of order")
            for group, action in re.findall(r"`pat ([a-z]+) ([a-z-]+)", text):
                if group in ("version", "manifest", "describe", "doctor", "configure"):
                    continue
                self.assertIn(f"{group} {action}", registered, f"{name}: `pat {group} {action}` is not a route")

    def test_unverified_routes_point_agents_at_the_qualification_playbook(self):
        # A row that says a route is unverified on some host must send the agent to measure it,
        # not leave "not run" as a dead end; the playbook and its links must exist.
        self.assertTrue((ROOT / "docs/playbooks/qualify-on-this-host.md").is_file())
        support = read("docs/SUPPORT.md")
        self.assertIn("## When a route is unverified on your host", support)
        self.assertIn("playbooks/qualify-on-this-host.md", support)
        for banned in ("Not run natively", "**no native run**", "**No native run**"):
            self.assertNotIn(banned, support, f"SUPPORT.md: {banned!r} without a next action")
        for doc in ("AGENTS.md", "docs/FOR-AGENTS.md", "skills/pat-help/SKILL.md", "skills/plutonium-agent-toolkit/SKILL.md"):
            self.assertIn("qualify-on-this-host.md", read(doc), doc)

    def test_agents_and_skill_route_to_knowledge_and_playbooks(self):
        agents = read("AGENTS.md")
        self.assertIn("docs/knowledge/README.md", agents)
        self.assertIn("docs/playbooks/README.md", agents)
        self.assertIn("## Work efficiently", agents)
        for rule in ("at most once per session", "status: succeeded", "delivery_uncertain", "Rebuild only after an input changed"):
            self.assertIn(rule, agents, rule)
        skill = read("skills/plutonium-agent-toolkit/SKILL.md")
        self.assertIn("docs/playbooks/", skill)
        self.assertIn("docs/knowledge/README.md", skill)
        for_agents = read("docs/FOR-AGENTS.md")
        self.assertIn("docs/knowledge/", for_agents)
        self.assertIn("docs/playbooks/", for_agents)

    def test_no_arbitrary_console_promise_anywhere_in_agent_docs(self):
        # The no-escape-hatch rule must not be contradicted by the malleability language.
        for doc in ("AGENTS.md", "docs/FOR-AGENTS.md", "skills/plutonium-agent-toolkit/SKILL.md"):
            text = read(doc).lower()
            self.assertIn("escape hatch", text, f"{doc} should keep the no-arbitrary-console rule explicit")


if __name__ == "__main__":
    unittest.main()
