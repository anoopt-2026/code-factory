"""
Unit tests for repository tools (filesystem, git, and testing).
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coding_agent.tools.repository_tools import (
    _safe_file,
    list_project_files,
    read_project_file,
    write_project_file,
    run_project_tests,
    commit_changes,
)


class TestRepositoryTools(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.test_dir.name).resolve()
        os.environ["TARGET_REPO_DIR"] = str(self.repo_path)
        os.environ["MOCK_TESTS"] = "true"

    def tearDown(self):
        self.test_dir.cleanup()

    def test_safe_file_prevents_escape(self):
        with self.assertRaises(ValueError):
            _safe_file(self.repo_path, "../outside.txt")

    def test_safe_file_protects_env_files(self):
        with self.assertRaises(ValueError):
            _safe_file(self.repo_path, ".env")
        with self.assertRaises(ValueError):
            _safe_file(self.repo_path, ".env.production")

    def test_safe_file_protects_agent_dir(self):
        with self.assertRaises(ValueError):
            _safe_file(self.repo_path, ".code-factory-agent/run_agent.py")

    def test_safe_file_protects_keys(self):
        with self.assertRaises(ValueError):
            _safe_file(self.repo_path, "server.key", for_write=True)

    def test_write_and_read_project_file(self):
        content = "public class Hello { public static void main(String[] args) {} }"
        res = write_project_file("src/main/java/Hello.java", content)
        self.assertTrue(res.get("success"))

        read_res = read_project_file("src/main/java/Hello.java")
        self.assertEqual(read_res.get("content"), content)

    def test_list_project_files_recursive(self):
        write_project_file("pom.xml", "<project></project>")
        write_project_file("src/main/java/App.java", "class App {}")

        res = list_project_files(".", recursive=True)
        paths = [e["path"] for e in res.get("entries", [])]
        self.assertIn("pom.xml", paths)
        self.assertIn("src/main/java/App.java", paths)

    def test_mock_test_execution(self):
        write_project_file("pom.xml", "<project></project>")
        test_res = run_project_tests("DEMO-1")
        self.assertTrue(test_res.get("tests_passed"))
        self.assertEqual(test_res.get("exit_code"), 0)

    def test_prepare_feature_branch_stops_if_branch_exists(self):
        from coding_agent.tools.repository_tools import prepare_feature_branch, _git
        # First preparation: creates KAN-4
        b1 = prepare_feature_branch("KAN-4")
        self.assertEqual(b1.get("branch"), "KAN-4")

        # Calling while already on KAN-4: idempotent, returns active branch
        b1_again = prepare_feature_branch("KAN-4")
        self.assertEqual(b1_again.get("branch"), "KAN-4")

        # Switching to base branch and attempting to re-prepare KAN-4: fails gracefully because branch already exists
        base = b1.get("base_branch", "master")
        _git(self.repo_path, "checkout", base)
        b2 = prepare_feature_branch("KAN-4")
        self.assertIn("error", b2)
        self.assertIn("already exists", b2["error"])


if __name__ == "__main__":
    unittest.main()
