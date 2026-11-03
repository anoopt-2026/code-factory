"""
End-to-end integration test for CodeFactoryAgent tools in offline/mock mode.
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

from coding_agent.tools.jira_tools import get_jira_issue
from coding_agent.tools.repository_tools import (
    prepare_feature_branch,
    list_project_files,
    read_project_file,
    write_project_file,
    run_project_tests,
    get_git_status,
    commit_changes,
)
from coding_agent.tools.github_tools import push_and_create_pull_request


class TestAgentEndToEndWorkflow(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.test_dir.name).resolve()

        # Set environment for full offline mock run
        os.environ["TARGET_REPO_DIR"] = str(self.repo_path)
        os.environ["MOCK_JIRA"] = "true"
        os.environ["MOCK_MODE"] = "true"
        os.environ["MOCK_TESTS"] = "true"
        os.environ["DRY_RUN"] = "true"
        os.environ["GITHUB_REPOSITORY"] = "demo-org/sample-springboot-app"

        # Baseline git repo setup
        subprocess.run(["git", "init"], cwd=str(self.repo_path), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "TestAgent"], cwd=str(self.repo_path), check=True)
        subprocess.run(["git", "config", "user.email", "testagent@example.com"], cwd=str(self.repo_path), check=True)

        # Baseline files
        (self.repo_path / "pom.xml").write_text("<project></project>", encoding="utf-8")
        src_dir = self.repo_path / "src" / "main" / "java" / "com" / "demo"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "App.java").write_text("package com.demo;\npublic class App {}", encoding="utf-8")

        subprocess.run(["git", "add", "-A"], cwd=str(self.repo_path), check=True)
        subprocess.run(["git", "commit", "-m", "chore: initial baseline commit"], cwd=str(self.repo_path), check=True)

    def tearDown(self):
        self.test_dir.cleanup()

    def test_complete_offline_workflow(self):
        ticket = "DEMO-1"

        # 1. Fetch Jira issue
        jira_issue = get_jira_issue(ticket)
        self.assertEqual(jira_issue["issue_key"], ticket)
        self.assertIn("Validation", jira_issue["summary"])

        # 2. Prepare feature branch
        branch_res = prepare_feature_branch(ticket)
        self.assertEqual(branch_res["branch"], ticket)

        # 3. Explore files
        files_res = list_project_files(".", recursive=True)
        file_paths = [f["path"] for f in files_res.get("entries", [])]
        self.assertIn("pom.xml", file_paths)
        self.assertIn("src/main/java/com/demo/App.java", file_paths)

        # 4. Implement changes (simulate agent code modification)
        updated_code = (
            "package com.demo;\n"
            "// Updated according to DEMO-1\n"
            "public class App {\n"
            "    public boolean validate() { return true; }\n"
            "}\n"
        )
        write_res = write_project_file("src/main/java/com/demo/App.java", updated_code)
        self.assertTrue(write_res.get("success"))

        # 5. Run tests
        tests_res = run_project_tests(ticket)
        self.assertTrue(tests_res.get("tests_passed"))

        # 6. Check Git Status
        status_res = get_git_status()
        self.assertEqual(status_res.get("branch"), ticket)
        self.assertIn("App.java", status_res.get("status"))

        # 7. Commit changes
        commit_res = commit_changes(f"feat({ticket}): implement employee validation")
        self.assertTrue(commit_res.get("success"))
        self.assertIsNotNone(commit_res.get("commit"))

        # 8. Create Pull Request
        pr_res = push_and_create_pull_request(
            issue_key=ticket,
            summary=jira_issue.get("summary"),
            description=jira_issue.get("description"),
            acceptance_criteria=jira_issue.get("acceptance_criteria"),
            changes_summary="Added validation method and updated App.java",
            test_summary="Diagnostic tests executed successfully.",
        )
        self.assertTrue(pr_res.get("success"))
        self.assertTrue(pr_res.get("dry_run"))
        self.assertEqual(pr_res.get("branch"), ticket)


if __name__ == "__main__":
    unittest.main()
