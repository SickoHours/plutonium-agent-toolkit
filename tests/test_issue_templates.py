"""Issue-form YAML must parse the way GitHub will read it: no flow-sequence options with commas."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class IssueTemplateTests(unittest.TestCase):
    def test_dropdown_options_are_block_lists(self):
        # Convention: never flow-style `options: [a, b]`. An item containing a comma (for
        # example a parenthesized description) silently splits into several items; block
        # style has no such trap and reads the same for every template.
        for path in (ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml"):
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"^\s*options:\s*\[", text, re.M),
                              f"{path.name}: use block-style options (one `- item` per line)")

    def test_every_form_has_name_description_and_body(self):
        for path in (ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml"):
            if path.name == "config.yml":
                continue
            text = path.read_text(encoding="utf-8")
            for key in ("name:", "description:", "body:"):
                self.assertIn(key, text, f"{path.name} lacks {key}")
