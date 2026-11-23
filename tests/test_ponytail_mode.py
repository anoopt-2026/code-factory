"""
Unit tests for Ponytail Mode minimal and maintainable code generation.
"""

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coding_agent.agent import root_agent, PONYTAIL_PRINCIPLES, is_ponytail_mode_enabled, SYSTEM_INSTRUCTION
from run_agent import parse_args, setup_environment


class TestPonytailMode(unittest.TestCase):

    def setUp(self):
        self.original_env = os.environ.get("PONYTAIL_MODE")

    def tearDown(self):
        if self.original_env is not None:
            os.environ["PONYTAIL_MODE"] = self.original_env
        else:
            os.environ.pop("PONYTAIL_MODE", None)

    def test_ponytail_mode_default_enabled(self):
        """Ponytail mode is enabled by default."""
        os.environ.pop("PONYTAIL_MODE", None)
        self.assertTrue(is_ponytail_mode_enabled())

    def test_ponytail_mode_explicit_toggle(self):
        """Ponytail mode respects environment variable overrides."""
        os.environ["PONYTAIL_MODE"] = "false"
        self.assertFalse(is_ponytail_mode_enabled())

        os.environ["PONYTAIL_MODE"] = "true"
        self.assertTrue(is_ponytail_mode_enabled())

        os.environ["PONYTAIL_MODE"] = "1"
        self.assertTrue(is_ponytail_mode_enabled())

        os.environ["PONYTAIL_MODE"] = "0"
        self.assertFalse(is_ponytail_mode_enabled())

    def test_ponytail_principles_content(self):
        """Verify that all 5 Ponytail principles are comprehensively codified."""
        # 1. Reuse existing implementations
        self.assertIn("REUSE EXISTING IMPLEMENTATIONS", PONYTAIL_PRINCIPLES)
        self.assertIn("inspect existing", PONYTAIL_PRINCIPLES.lower())

        # 2. Minimal code changes
        self.assertIn("MINIMAL CODE CHANGES", PONYTAIL_PRINCIPLES)
        self.assertIn("strictly necessary", PONYTAIL_PRINCIPLES.lower())

        # 3. YAGNI principle
        self.assertIn("YAGNI", PONYTAIL_PRINCIPLES)
        self.assertIn("speculative features", PONYTAIL_PRINCIPLES.lower())

        # 4. Architecture compliance
        self.assertIn("ARCHITECTURE COMPLIANCE", PONYTAIL_PRINCIPLES)
        self.assertIn("naming conventions", PONYTAIL_PRINCIPLES.lower())

        # 5. Implementation & diff review
        self.assertIn("DIFF REVIEW", PONYTAIL_PRINCIPLES)
        self.assertIn("get_git_diff", PONYTAIL_PRINCIPLES)

    def test_system_instruction_incorporates_ponytail(self):
        """Agent system instruction mandates Ponytail Mode across planning and review."""
        instruction = SYSTEM_INSTRUCTION.lower()
        self.assertIn("ponytail", instruction)
        self.assertIn("reuse existing", instruction)
        self.assertIn("minimal", instruction)
        self.assertIn("yagni", instruction)
        self.assertIn("architecture compliance", instruction)
        self.assertIn("get_git_diff", instruction)

    def test_cli_ponytail_arguments(self):
        """Verify CLI parser handles --ponytail and --no-ponytail flags."""
        import sys
        old_argv = sys.argv

        try:
            sys.argv = ["run_agent.py", "--ticket", "DEMO-1", "--ponytail"]
            args = parse_args()
            self.assertTrue(args.ponytail)
            setup_environment(args)
            self.assertEqual(os.environ.get("PONYTAIL_MODE"), "true")

            sys.argv = ["run_agent.py", "--ticket", "DEMO-1", "--no-ponytail"]
            args = parse_args()
            self.assertFalse(args.ponytail)
            setup_environment(args)
            self.assertEqual(os.environ.get("PONYTAIL_MODE"), "false")
        finally:
            sys.argv = old_argv

    def test_jira_to_github_pr_workflow_unbroken(self):
        """Ensure existing Jira to GitHub PR pipeline tools remain bound to the root agent."""
        tool_names = [fn.__name__ for fn in root_agent.tools]
        expected_tools = [
            "get_jira_issue",
            "prepare_feature_branch",
            "get_architecture_graph",
            "query_code_graph",
            "list_project_files",
            "read_project_file",
            "write_project_file",
            "run_project_tests",
            "get_git_status",
            "get_git_diff",
            "commit_changes",
            "push_and_create_pull_request",
        ]
        for expected in expected_tools:
            self.assertIn(expected, tool_names, f"Tool '{expected}' missing from root_agent.")


if __name__ == "__main__":
    unittest.main()
