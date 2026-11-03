"""
Unit tests for GitHub tools (PR creation, dry run, and Markdown generation).
"""

import os
import sys
import tempfile
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coding_agent.tools.github_tools import push_and_create_pull_request, _parse_repo_slug


class TestGitHubTools(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.test_dir.name).resolve()
        os.environ["TARGET_REPO_DIR"] = str(self.repo_path)
        os.environ["DRY_RUN"] = "true"
        os.environ["GITHUB_REPOSITORY"] = "demo-org/sample-app"

        # Initialize mock git repository
        subprocess.run(["git", "init"], cwd=str(self.repo_path), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "TestUser"], cwd=str(self.repo_path), check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(self.repo_path), check=True)

        dummy_file = self.repo_path / "README.md"
        dummy_file.write_text("# Test Repo\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=str(self.repo_path), check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(self.repo_path), check=True)
        subprocess.run(["git", "checkout", "-B", "DEMO-1"], cwd=str(self.repo_path), check=True)

    def tearDown(self):
        self.test_dir.cleanup()

    def test_parse_repo_slug_from_env(self):
        slug = _parse_repo_slug(self.repo_path)
        self.assertEqual(slug, "demo-org/sample-app")

    def test_dry_run_pull_request(self):
        res = push_and_create_pull_request(
            issue_key="DEMO-1",
            summary="Validate employee creation",
            description="Add validation annotations",
            acceptance_criteria="Check blank name and bad email",
            changes_summary="Added @NotBlank and @Email to Employee entity",
            test_summary="All tests passed",
        )

        self.assertTrue(res.get("success"))
        self.assertTrue(res.get("dry_run"))
        self.assertIn("mock-pr-1", res.get("pull_request_url"))
        self.assertIn("DEMO-1", res.get("pr_title"))
        self.assertIn("Acceptance Criteria", res.get("pr_body"))
        self.assertIn("Added @NotBlank", res.get("pr_body"))


if __name__ == "__main__":
    unittest.main()
