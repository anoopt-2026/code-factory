"""Unit tests for CodeGraph tools and service layer."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coding_agent.services.codegraph_service import CodeGraphService
from coding_agent.tools.codegraph_tools import (
    find_callers_and_callees,
    get_code_graph_summary,
    get_dependency_context,
    get_symbol_definition,
    search_symbols,
)


class TestCodeGraphTools(unittest.TestCase):
    """Test suite verifying CodeGraph tools query parsing, path sandboxing, and graceful fallback."""

    SAMPLE_JAVA_ENTITY = """package com.demo.employee.entity;

import jakarta.persistence.*;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;

@Entity
@Table(name = "employees")
public class Employee {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @NotBlank
    private String name;

    @Email
    private String email;

    public Employee() {}
    public Long getId() { return id; }
    public String getEmail() { return email; }
    public void setEmail(String email) { this.email = email; }
}
"""

    SAMPLE_JAVA_SERVICE = """package com.demo.employee.service;

import com.demo.employee.entity.Employee;
import org.springframework.stereotype.Service;

@Service
public class EmployeeService {
    public Employee create(Employee employee) {
        return employee;
    }
}
"""

    SAMPLE_JAVA_CONTROLLER = """package com.demo.employee.controller;

import com.demo.employee.entity.Employee;
import com.demo.employee.service.EmployeeService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import jakarta.validation.Valid;

@RestController
@RequestMapping("/employees")
public class EmployeeController {
    private final EmployeeService service;

    public EmployeeController(EmployeeService service) {
        this.service = service;
    }

    @PostMapping
    public ResponseEntity<Employee> create(@Valid @RequestBody Employee employee) {
        Employee created = service.create(employee);
        return ResponseEntity.ok(created);
    }
}
"""

    SAMPLE_JAVA_TEST = """package com.demo.employee.controller;

import com.demo.employee.entity.Employee;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest
public class EmployeeValidationTest {
    @Test
    void testValidEmail() {
        Employee emp = new Employee();
        emp.setEmail("test@example.com");
    }
}
"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.temp_dir.name).resolve()

        # Build realistic Spring Boot directory structure
        src_main = self.repo_dir / "src" / "main" / "java" / "com" / "demo" / "employee"
        src_test = self.repo_dir / "src" / "test" / "java" / "com" / "demo" / "employee" / "controller"
        (src_main / "entity").mkdir(parents=True)
        (src_main / "service").mkdir(parents=True)
        (src_main / "controller").mkdir(parents=True)
        src_test.mkdir(parents=True)

        (src_main / "entity" / "Employee.java").write_text(self.SAMPLE_JAVA_ENTITY, encoding="utf-8")
        (src_main / "service" / "EmployeeService.java").write_text(self.SAMPLE_JAVA_SERVICE, encoding="utf-8")
        (src_main / "controller" / "EmployeeController.java").write_text(self.SAMPLE_JAVA_CONTROLLER, encoding="utf-8")
        (src_test / "EmployeeValidationTest.java").write_text(self.SAMPLE_JAVA_TEST, encoding="utf-8")

        # Secret file that should never be indexed
        (self.repo_dir / ".env").write_text("SECRET_KEY=12345", encoding="utf-8")

        # Set TARGET_REPO_DIR to point to temporary test repo
        self.original_target = os.environ.get("TARGET_REPO_DIR")
        os.environ["TARGET_REPO_DIR"] = str(self.repo_dir)
        os.environ["CODEGRAPH_ENABLED"] = "true"

        # Initialize CodeGraphService for test repository
        self.service = CodeGraphService.get_instance(target_repo=self.repo_dir, force_refresh=True)
        self.service.ensure_indexed(force=True)

    def tearDown(self):
        if self.service:
            self.service.close()
        CodeGraphService._instance = None
        if self.original_target:
            os.environ["TARGET_REPO_DIR"] = self.original_target
        else:
            os.environ.pop("TARGET_REPO_DIR", None)
        self.temp_dir.cleanup()

    def test_search_symbols_success(self):
        """Verify search_symbols locates classes and fields matching query."""
        res = search_symbols("Employee")
        self.assertIn("symbols", res)
        self.assertGreater(res["total_matches"], 0)
        names = [s["name"] for s in res["symbols"]]
        self.assertIn("Employee", names)
        self.assertIn("EmployeeController", names)
        self.assertIn("EmployeeService", names)

    def test_search_symbols_empty_query(self):
        """Verify search_symbols rejects empty query."""
        res = search_symbols("")
        self.assertIn("error", res)

    def test_get_symbol_definition_success(self):
        """Verify get_symbol_definition returns detailed symbol metadata and snippet."""
        res = get_symbol_definition("EmployeeController")
        self.assertEqual(res.get("name"), "EmployeeController")
        self.assertEqual(res.get("component_type"), "Controller")
        self.assertIn("RestController", res.get("annotations", []))
        self.assertIn("EmployeeController", res.get("source_snippet", ""))

    def test_get_symbol_definition_nonexistent(self):
        """Verify get_symbol_definition returns error for unknown symbol."""
        res = get_symbol_definition("NonExistentClass")
        self.assertIn("error", res)

    def test_get_symbol_definition_empty_name(self):
        """Verify get_symbol_definition rejects empty name."""
        res = get_symbol_definition("")
        self.assertIn("error", res)

    def test_find_callers_and_callees_success(self):
        """Verify find_callers_and_callees discovers method invocations and injections."""
        res = find_callers_and_callees("EmployeeController")
        self.assertEqual(res.get("symbol"), "EmployeeController")
        outbound = res.get("callees_outbound", [])
        self.assertTrue(any("service" in c["target"].lower() for c in outbound))

    def test_find_callers_and_callees_empty_name(self):
        """Verify find_callers_and_callees rejects empty name."""
        res = find_callers_and_callees("")
        self.assertIn("error", res)

    def test_get_dependency_context_success(self):
        """Verify get_dependency_context provides complete context package and related tests."""
        res = get_dependency_context("Employee")
        self.assertEqual(res.get("name"), "Employee")
        self.assertIn("formatted_context", res)
        self.assertIn("EmployeeValidationTest", "".join(res.get("related_tests", [])))

    def test_get_dependency_context_empty_name(self):
        """Verify get_dependency_context rejects empty name."""
        res = get_dependency_context("")
        self.assertIn("error", res)

    def test_get_code_graph_summary_success(self):
        """Verify get_code_graph_summary returns structured architectural layers."""
        res = get_code_graph_summary()
        self.assertIn("layers", res)
        layers = res["layers"]
        self.assertIn("EmployeeController", layers.get("controllers", []))
        self.assertIn("EmployeeService", layers.get("services", []))
        self.assertIn("Employee", layers.get("entities", []))
        self.assertIn("EmployeeValidationTest", layers.get("tests", []))

    def test_codegraph_disabled_fallback(self):
        """Verify tools return graceful disabled status when CODEGRAPH_ENABLED=false."""
        with patch.dict(os.environ, {"CODEGRAPH_ENABLED": "false"}):
            res = search_symbols("Employee")
            self.assertEqual(res.get("status"), "disabled")
            self.assertIn("fallback", res)

    def test_codegraph_unavailable_parser_fallback(self):
        """Verify tools return graceful unavailable status when tree-sitter parser is missing."""
        with patch.object(CodeGraphService, "is_parser_available", return_value=False):
            # Refresh instance with parser unavailable
            svc = CodeGraphService(target_repo=self.repo_dir, use_memory_db=True)
            res = svc.search_symbols("Employee")
            self.assertEqual(res.get("status"), "unavailable")
            self.assertIn("fallback", res)

    def test_path_isolation_excludes_secrets_and_git(self):
        """Verify secret files (.env) and excluded directories are strictly omitted from index."""
        indexer = self.service.indexer
        java_files = indexer._find_java_files()
        for f in java_files:
            self.assertTrue(f.endswith(".java"))
            self.assertFalse(".env" in f)
            self.assertFalse(".git" in f)

    def test_incremental_indexing_skips_unchanged_files(self):
        """Verify re-indexing unchanged files returns 0 indexed files."""
        count = self.service.indexer.index_repository(force=False)
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
