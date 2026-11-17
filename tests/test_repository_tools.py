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

    def test_prepare_feature_branch_collision_counter(self):
        from coding_agent.tools.repository_tools import prepare_feature_branch
        # First preparation: creates KAN-4
        b1 = prepare_feature_branch("KAN-4")
        self.assertEqual(b1.get("branch"), "KAN-4")

        # Second preparation when KAN-4 is already present in local branch list: creates KAN-4-1
        b2 = prepare_feature_branch("KAN-4")
        self.assertEqual(b2.get("branch"), "KAN-4-1")

        # Third preparation: creates KAN-4-2
        b3 = prepare_feature_branch("KAN-4")
        self.assertEqual(b3.get("branch"), "KAN-4-2")


if __name__ == "__main__":
    unittest.main()
