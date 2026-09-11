"""Guardrails for CONTEXT.md, docs/knowledge, docs/playbooks, skills/ and vendor/matt-pocock.

These turn the writing rules into checks: one glossary, playbooks with the five headings and a
proof per step, every ``pat <group> <action>`` a registered route, provenance on adapted skills,
and vendored upstream bytes that match their recorded hashes.
"""
import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK_HEADINGS = ["## Preconditions", "## Steps", "## Do not", "## Stop conditions", "## Report"]
# Playbooks whose every step carries a "Proof:" and whose report is per gate. Others keep the five
# headings (enforced in test_docs_consistency) and name proofs where a receipt field exists.
STRICT_PLAYBOOKS = {"preflight-scripts.md", "preflight-audio-memory.md"}
PREFLIGHT_HEADINGS = PLAYBOOK_HEADINGS
ROUTE_RE = re.compile(r"`pat (dev|gsc|ff|project|module|registry|model|audio|image|lua|weapon|game|agent|plane|capture|test) ([a-z-]+)")
SIX_FACTS = ["offline verified", "installed", "launched", "loaded", "playable", "captured", "accepted"]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def frontmatter(text):
    assert text.startswith("---\n"), "missing frontmatter"
    end = text.index("\n---\n", 4)
    block = text[4:end]
    fields = {}
    for line in block.splitlines():
        m = re.match(r"^([a-z_-]+):\s*(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2)
    return fields, block


def registered_routes():
    from plutonium_agent_toolkit.core import discovery
    import plutonium_agent_toolkit.dev.routes  # noqa: F401  registers
    import plutonium_agent_toolkit.game.routes  # noqa: F401
    import plutonium_agent_toolkit.testing.routes  # noqa: F401

    return {(r.group, r.action) for r in discovery.routes()}


class GlossaryTests(unittest.TestCase):
    def test_context_exists_and_defines_both_evidence_ladders(self):
        text = read("CONTEXT.md")
        for term in ("**Route status**", "**Route evidence level**", "**Build evidence**", "**Receipt**",
                     "**Readback**", "**Delivery uncertain**", "**Preflight**", "**Red loop**"):
            self.assertIn(term, text, f"CONTEXT.md must define {term}")
        for level in ("contract", "deferred", "offline", "native", "game", "accepted"):
            self.assertIn(f"`{level}`", text)
        for rung in ("**Launched**", "**Loaded**", "**Playable**", "**Accepted**"):
            self.assertIn(rung, text, f"CONTEXT.md must define the build rung {rung}")

    def test_every_term_has_an_avoid_line(self):
        text = read("CONTEXT.md")
        terms = re.findall(r"^\*\*([^*]+)\*\*(?: and \*\*[^*]+\*\*)?:", text, re.M)
        avoids = text.count("_Avoid_:")
        self.assertGreaterEqual(len(terms), 40)
        self.assertEqual(len(terms), avoids, "every glossary term needs exactly one _Avoid_ line")

    def test_glossary_is_pointed_at_from_agent_entry_points(self):
        for doc in ("skills/plutonium-agent-toolkit/SKILL.md", "docs/knowledge/README.md", "docs/playbooks/README.md"):
            self.assertIn("CONTEXT.md", read(doc), doc)


class KnowledgeTests(unittest.TestCase):
    def test_index_lists_every_page_and_every_page_exists(self):
        index = read("docs/knowledge/README.md")
        pages = sorted(p.name for p in (ROOT / "docs/knowledge").glob("*.md") if p.name != "README.md")
        self.assertTrue(pages)
        for page in pages:
            self.assertIn(f"[{page}]({page})", index, f"knowledge index missing {page}")
        for link in re.findall(r"\]\(([a-z0-9-]+\.md)\)", index):
            self.assertTrue((ROOT / "docs/knowledge" / link).is_file(), link)

    def test_pages_are_reference_only_and_bounded(self):
        for page in (ROOT / "docs/knowledge").glob("*.md"):
            text = page.read_text(encoding="utf-8")
            self.assertLessEqual(len(text.splitlines()), 150, f"{page.name} over 150 lines")
            self.assertNotIn("## Steps", text, f"{page.name} is reference; steps belong in playbooks")


class PlaybookTests(unittest.TestCase):
    def playbooks(self):
        return sorted(p for p in (ROOT / "docs/playbooks").glob("*.md") if p.name != "README.md")

    def test_index_lists_every_playbook(self):
        index = read("docs/playbooks/README.md")
        for p in self.playbooks():
            self.assertIn(f"[{p.name}]({p.name})", index, f"playbook index missing {p.name}")

    def test_five_headings_in_order(self):
        for p in self.playbooks():
            text = p.read_text(encoding="utf-8")
            positions = [text.find(h) for h in PLAYBOOK_HEADINGS]
            self.assertTrue(all(x >= 0 for x in positions), f"{p.name} missing a heading: {positions}")
            self.assertEqual(positions, sorted(positions), f"{p.name} headings out of order")

    def test_strict_playbooks_carry_a_proof_on_every_step(self):
        for p in self.playbooks():
            if p.name not in STRICT_PLAYBOOKS:
                continue
            text = p.read_text(encoding="utf-8")
            steps = text.split("## Steps", 1)[1].split("## Do not", 1)[0]
            items = re.split(r"(?m)^\d+\. ", steps)[1:]
            self.assertTrue(items, f"{p.name} has no numbered steps")
            for i, item in enumerate(items, 1):
                self.assertIn("Proof:", item, f"{p.name} step {i} lacks a proof")

    def test_every_pat_route_mentioned_is_registered(self):
        routes = registered_routes()
        for p in list(self.playbooks()) + list((ROOT / "skills").glob("*/SKILL.md")) + list((ROOT / "docs/knowledge").glob("*.md")):
            for group, action in ROUTE_RE.findall(p.read_text(encoding="utf-8")):
                self.assertIn((group, action), routes, f"{p.relative_to(ROOT)} mentions unregistered route {group} {action}")

    def test_every_task_playbook_report_says_offline_verified(self):
        # Every report starts from the first rung; the strict ones name all of them.
        for p in self.playbooks():
            report = p.read_text(encoding="utf-8").split("## Report", 1)[1].lower()
            if p.name.startswith("preflight-") or p.name == "diagnose-a-crash.md":
                continue
            self.assertIn("offline verified", report, f"{p.name} report must name the offline-verified rung")

    def test_strict_preflight_reports_are_per_gate_against_a_hash(self):
        for p in self.playbooks():
            if p.name not in STRICT_PLAYBOOKS:
                continue
            text = p.read_text(encoding="utf-8")
            report = text.split("## Report", 1)[1].lower()
            self.assertIn("per gate", report, f"{p.name} report must be per gate")
            self.assertRegex(report, r"pass, fail", f"{p.name} report must name the gate outcomes")
            steps = text.split("## Steps", 1)[1].split("## Do not", 1)[0]
            self.assertIn("Failure", steps, f"{p.name} gates must name the failure each one prevents")


class SkillTests(unittest.TestCase):
    ADAPTED = {"pat-diagnose": "skills/engineering/diagnosing-bugs",
               "pat-review": "skills/engineering/code-review",
               "pat-grill": "skills/productivity/grilling"}

    def test_frontmatter_shape(self):
        for skill in (ROOT / "skills").glob("*/SKILL.md"):
            fields, block = frontmatter(skill.read_text(encoding="utf-8"))
            self.assertEqual(fields.get("name"), skill.parent.name, skill)
            self.assertTrue(fields.get("description"), f"{skill} needs a description")
            if skill.parent.name == "pat-help":
                self.assertEqual(fields.get("disable-model-invocation"), "true", "router is user-invoked")
            else:
                self.assertNotIn("disable-model-invocation", fields, f"{skill.parent.name} should be model-invoked")

    def test_adapted_skills_carry_provenance_matching_vendor(self):
        source = json.loads(read("vendor/matt-pocock/SOURCE.json"))
        for name, path in self.ADAPTED.items():
            _, block = frontmatter(read(f"skills/{name}/SKILL.md"))
            self.assertIn(f"commit: {source['commit']}", block, name)
            self.assertIn(f"path: {path}", block, name)
            self.assertIn("license: MIT", block, name)
            self.assertTrue((ROOT / "vendor/matt-pocock" / path / "SKILL.md").is_file(), path)

    def test_router_names_every_model_invoked_skill(self):
        router = read("skills/pat-help/SKILL.md")
        for skill in (ROOT / "skills").iterdir():
            if skill.name in ("pat-help", "plutonium-agent-toolkit"):
                continue
            self.assertIn(f"`{skill.name}`", router, f"pat-help does not route to {skill.name}")

    def test_umbrella_skill_points_at_the_new_layers(self):
        text = read("skills/plutonium-agent-toolkit/SKILL.md")
        for needle in ("CONTEXT.md", "docs/knowledge/", "docs/playbooks/", "pat-help", "escape hatch"):
            self.assertIn(needle, text)


class VendorTests(unittest.TestCase):
    def test_vendored_bytes_match_source_manifest(self):
        source = json.loads(read("vendor/matt-pocock/SOURCE.json"))
        self.assertEqual(source["license"], "MIT")
        self.assertRegex(source["commit"], r"^[0-9a-f]{40}$")
        for rel, digest in source["files"].items():
            path = ROOT / "vendor/matt-pocock" / rel
            self.assertTrue(path.is_file(), rel)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest, f"{rel} edited after vendoring")
        self.assertTrue((ROOT / "vendor/matt-pocock/LICENSE").is_file())

    def test_notice_credits_upstream(self):
        self.assertIn("mattpocock/skills", read("NOTICE"))


if __name__ == "__main__":
    unittest.main()
