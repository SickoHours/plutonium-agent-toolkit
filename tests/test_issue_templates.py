"""Issue-form YAML must parse the way GitHub will read it: no flow-sequence options with commas."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class IssueTemplateTests(unittest.TestCase):
    def test_dropdown_options_are_block_lists(self):
        for path in (ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml"):
            text = path.read_text(encoding="utf-8")
            for m in re.finditer(r"^\s*options:\s*\[(.*)\]\s*$", text, re.M):
                self.assertNotIn(",", re.sub(r"'[^']*'|\"[^\"]*\"", "", m.group(1)),
                                 f"{path.name}: flow-style options with unquoted commas split into extra items")

    def test_every_form_has_name_description_and_body(self):
        for path in (ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml"):
            if path.name == "config.yml":
                continue
            text = path.read_text(encoding="utf-8")
            for key in ("name:", "description:", "body:"):
                self.assertIn(key, text, f"{path.name} lacks {key}")
