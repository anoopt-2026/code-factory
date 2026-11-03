"""
Unit tests for Jira tools (mock and live parsing).
"""

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coding_agent.tools.jira_tools import (
    get_jira_issue,
    _flatten_adf,
    _extract_acceptance_criteria_from_text,
    _is_mock_mode,
)


class TestJiraTools(unittest.TestCase):

    def setUp(self):
        os.environ["MOCK_JIRA"] = "true"
        os.environ["MOCK_MODE"] = "true"

    def test_mock_mode_builtin_demo1(self):
        issue = get_jira_issue("DEMO-1")
        self.assertNotIn("error", issue)
        self.assertEqual(issue["issue_key"], "DEMO-1")
        self.assertIn("Validation", issue["summary"])
        self.assertTrue(len(issue["acceptance_criteria"]) > 0)
        self.assertEqual(issue["issue_type"], "Story")
        self.assertTrue(issue.get("is_mock"))

    def test_mock_mode_builtin_cut2(self):
        issue = get_jira_issue("CUT-2")
        self.assertNotIn("error", issue)
        self.assertEqual(issue["issue_key"], "CUT-2")
        self.assertIn("Update", issue["summary"])

    def test_mock_mode_arbitrary_key(self):
        issue = get_jira_issue("PROJ-999")
        self.assertNotIn("error", issue)
        self.assertEqual(issue["issue_key"], "PROJ-999")
        self.assertIn("PROJ-999", issue["summary"])

    def test_invalid_key_format(self):
        issue = get_jira_issue("invalid_ticket_123")
        self.assertIn("error", issue)

    def test_flatten_adf_basic(self):
        sample_adf = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "This is a requirement."}],
                },
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "Criterion 1"}],
                                }
                            ],
                        },
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "Criterion 2"}],
                                }
                            ],
                        },
                    ],
                },
            ],
        }
        flattened = _flatten_adf(sample_adf)
        self.assertIn("This is a requirement.", flattened)
        self.assertIn("- Criterion 1", flattened)
        self.assertIn("- Criterion 2", flattened)

    def test_extract_acceptance_criteria_from_text(self):
        desc = (
            "Story description here.\n\n"
            "Acceptance Criteria:\n"
            "1. Given employee exists, return 200.\n"
            "2. When employee is not found, return 404.\n\n"
            "Technical Notes:\n"
            "Use JPA."
        )
        ac = _extract_acceptance_criteria_from_text(desc)
        self.assertIn("Given employee exists", ac)
        self.assertNotIn("Technical Notes", ac)


if __name__ == "__main__":
    unittest.main()
