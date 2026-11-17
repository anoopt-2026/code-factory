
"""Unit tests for CodeGraph tools and service layer."""

import os
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
    """Test CodeGraph tools, indexing, path isolation, and graceful fallback."""

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

        self.original_target = os.environ.get("TARGET_REPO_DIR")
        self.original_enabled = os.environ.get("CODEGRAPH_ENABLED")

        # Create a realistic Spring Boot directory structure.
        src_main = (
            self.repo_dir
            / "src"
            / "main"
            / "java"
            / "com"
            / "demo"
            / "employee"
        )
        src_test = (
            self.repo_dir
            / "src"
            / "test"
            / "java"
            / "com"
            / "demo"
            / "employee"
            / "controller"
        )

        (src_main / "entity").mkdir(parents=True)
        (src_main / "service").mkdir(parents=True)
        (src_main / "controller").mkdir(parents=True)
        src_test.mkdir(parents=True)

        (src_main / "entity" / "Employee.java").write_text(
            self.SAMPLE_JAVA_ENTITY, encoding="utf-8"
        )
        (src_main / "service" / "EmployeeService.java").write_text(
            self.SAMPLE_JAVA_SERVICE, encoding="utf-8"
        )
        (src_main / "controller" / "EmployeeController.java").write_text(
            self.SAMPLE_JAVA_CONTROLLER, encoding="utf-8"
        )
        (src_test / "EmployeeValidationTest.java").write_text(
            self.SAMPLE_JAVA_TEST, encoding="utf-8"
        )

        # Secret file that must not be indexed.
        (self.repo_dir / ".env").write_text(
            "SECRET_KEY=12345", encoding="utf-8"
        )

        os.environ["TARGET_REPO_DIR"] = str(self.repo_dir)
        os.environ["CODEGRAPH_ENABLED"] = "true"

        # Initialize and index the temporary repository.
        CodeGraphService._instance = None
        self.service = CodeGraphService.get_instance(
            target_repo=self.repo_dir,
            force_refresh=True,
        )
        self.service.ensure_indexed(force=True)

    def tearDown(self):
        if getattr(self, "service", None):
            self.service.close()

        CodeGraphService._instance = None

        if self.original_target is not None:
            os.environ["TARGET_REPO_DIR"] = self.original_target
        else:
            os.environ.pop("TARGET_REPO_DIR", None)

        if self.original_enabled is not None:
            os.environ["CODEGRAPH_ENABLED"] = self.original_enabled
        else:
            os.environ.pop("CODEGRAPH_ENABLED", None)

        self.temp_dir.cleanup()

    def test_search_symbols_success(self):
        """Verify symbol search locates matching classes."""
        res = search_symbols("Employee")

        self.assertIn("symbols", res)
        self.assertGreater(res["total_matches"], 0)

        names = [symbol["name"] for symbol in res["symbols"]]
        self.assertIn("Employee", names)
        self.assertIn("EmployeeController", names)
        self.assertIn("EmployeeService", names)

    def test_search_symbols_empty_query(self):
        """Verify symbol search rejects an empty query."""
        res = search_symbols("")

        self.assertIn("error", res)

    def test_get_symbol_definition_success(self):
        """Verify symbol definition includes metadata and source snippet."""
        res = get_symbol_definition("EmployeeController")

        self.assertEqual(res.get("name"), "EmployeeController")
        self.assertEqual(res.get("component_type"), "Controller")
        self.assertIn("RestController", res.get("annotations", []))
        self.assertIn(
            "EmployeeController",
            res.get("source_snippet", ""),
        )

    def test_get_symbol_definition_nonexistent(self):
        """Verify an unknown symbol returns an error."""
        res = get_symbol_definition("NonExistentClass")

        self.assertIn("error", res)

    def test_get_symbol_definition_empty_name(self):
        """Verify an empty symbol name is rejected."""
        res = get_symbol_definition("")

        self.assertIn("error", res)

    def test_find_callers_and_callees_success(self):
        """Verify caller/callee discovery identifies service dependencies."""
        res = find_callers_and_callees("EmployeeController")

        self.assertEqual(res.get("symbol"), "EmployeeController")

        outbound = res.get("callees_outbound", [])
        self.assertTrue(
            any("service" in item["target"].lower() for item in outbound)
        )

    def test_find_callers_and_callees_empty_name(self):
        """Verify an empty symbol name is rejected."""
        res = find_callers_and_callees("")

        self.assertIn("error", res)

    def test_get_dependency_context_success(self):
        """Verify dependency context includes related source and tests."""
        res = get_dependency_context("Employee")

        self.assertEqual(res.get("name"), "Employee")
        self.assertIn("formatted_context", res)
        self.assertIn(
            "EmployeeValidationTest",
            "".join(res.get("related_tests", [])),
        )

    def test_get_dependency_context_empty_name(self):
        """Verify an empty symbol name is rejected."""
        res = get_dependency_context("")

        self.assertIn("error", res)

    def test_get_code_graph_summary_success(self):
        """Verify the summary contains the expected architectural layers."""
        res = get_code_graph_summary()

        self.assertIn("layers", res)
        layers = res["layers"]

        self.assertIn(
            "EmployeeController",
            layers.get("controllers", []),
        )
        self.assertIn(
            "EmployeeService",
            layers.get("services", []),
        )
        self.assertIn(
            "Employee",
            layers.get("entities", []),
        )
        self.assertIn(
            "EmployeeValidationTest",
            layers.get("tests", []),
        )

    def test_codegraph_disabled_fallback(self):
        """Verify tools gracefully handle CodeGraph being disabled."""
        with patch.dict(os.environ, {"CODEGRAPH_ENABLED": "false"}):
            res = search_symbols("Employee")

        self.assertEqual(res.get("status"), "disabled")
        self.assertIn("fallback", res)

    def test_codegraph_unavailable_parser_fallback(self):
        """Verify graceful fallback when Tree-sitter is unavailable."""
        with patch.object(
            CodeGraphService,
            "is_parser_available",
            return_value=False,
        ):
            service = CodeGraphService(
                target_repo=self.repo_dir,
                use_memory_db=True,
            )
            res = service.search_symbols("Employee")

        self.assertEqual(res.get("status"), "unavailable")
        self.assertIn("fallback", res)

    def test_path_isolation_excludes_secrets_and_git(self):
        """Verify secret files and Git directories are excluded from indexing."""
        indexer = self.service.indexer
        java_files = indexer._find_java_files()

        for file_path in java_files:
            self.assertTrue(file_path.endswith(".java"))
            self.assertNotIn(".env", file_path)
            self.assertNotIn(".git", file_path)

    def test_incremental_indexing_skips_unchanged_files(self):
        """Verify unchanged files are skipped during incremental indexing."""
        count = self.service.indexer.index_repository(force=False)

        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
