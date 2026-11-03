"""
Unit tests for Code Graph tools (AST parsing, architecture graph, and queries).
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coding_agent.tools.codegraph_tools import (
    build_code_graph,
    get_architecture_graph,
    query_code_graph,
)


class TestCodeGraphTools(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.test_dir.name).resolve()
        os.environ["TARGET_REPO_DIR"] = str(self.repo_path)

        # Setup mock Spring Boot files
        controller_dir = self.repo_path / "src" / "main" / "java" / "com" / "demo" / "controller"
        service_dir = self.repo_path / "src" / "main" / "java" / "com" / "demo" / "service"
        repo_dir = self.repo_path / "src" / "main" / "java" / "com" / "demo" / "repository"
        entity_dir = self.repo_path / "src" / "main" / "java" / "com" / "demo" / "entity"

        for d in [controller_dir, service_dir, repo_dir, entity_dir]:
            d.mkdir(parents=True, exist_ok=True)

        (entity_dir / "Employee.java").write_text(
            "package com.demo.entity;\n"
            "import jakarta.persistence.*;\n"
            "@Entity @Table(name = \"employees\")\n"
            "public class Employee {\n"
            "    @Id private Long id;\n"
            "    private String name;\n"
            "    public Long getId() { return id; }\n"
            "}\n",
            encoding="utf-8",
        )

        (repo_dir / "EmployeeRepository.java").write_text(
            "package com.demo.repository;\n"
            "import org.springframework.data.jpa.repository.JpaRepository;\n"
            "import com.demo.entity.Employee;\n"
            "public interface EmployeeRepository extends JpaRepository<Employee, Long> {\n"
            "    boolean existsByEmail(String email);\n"
            "}\n",
            encoding="utf-8",
        )

        (service_dir / "EmployeeService.java").write_text(
            "package com.demo.service;\n"
            "import org.springframework.stereotype.Service;\n"
            "import com.demo.repository.EmployeeRepository;\n"
            "@Service\n"
            "public class EmployeeService {\n"
            "    private final EmployeeRepository repository;\n"
            "    public EmployeeService(EmployeeRepository repository) { this.repository = repository; }\n"
            "    public Employee create(Employee e) { return repository.save(e); }\n"
            "}\n",
            encoding="utf-8",
        )

        (controller_dir / "EmployeeController.java").write_text(
            "package com.demo.controller;\n"
            "import org.springframework.web.bind.annotation.*;\n"
            "import org.springframework.http.ResponseEntity;\n"
            "import com.demo.service.EmployeeService;\n"
            "import com.demo.entity.Employee;\n"
            "@RestController\n"
            "@RequestMapping(\"/employees\")\n"
            "public class EmployeeController {\n"
            "    private final EmployeeService service;\n"
            "    public EmployeeController(EmployeeService service) { this.service = service; }\n"
            "    @PostMapping\n"
            "    public ResponseEntity<Employee> create(@RequestBody Employee e) {\n"
            "        return ResponseEntity.ok(service.create(e));\n"
            "    }\n"
            "    @GetMapping(\"/{id}\")\n"
            "    public ResponseEntity<Employee> findById(@PathVariable Long id) {\n"
            "        return ResponseEntity.ok(null);\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.test_dir.cleanup()

    def test_build_code_graph(self):
        graph = build_code_graph(self.repo_path)
        self.assertTrue(graph.has_node("CLASS:EmployeeController"))
        self.assertTrue(graph.has_node("CLASS:EmployeeService"))
        self.assertTrue(graph.has_node("CLASS:EmployeeRepository"))
        self.assertTrue(graph.has_node("CLASS:Employee"))
        self.assertTrue(graph.has_node("ENDPOINT:POST /employees"))
        self.assertTrue(graph.has_node("ENDPOINT:GET /employees/{id}"))

        # Verify dependency injection edge: Controller -> Service -> Repository
        self.assertTrue(graph.has_edge("CLASS:EmployeeController", "CLASS:EmployeeService"))
        self.assertTrue(graph.has_edge("CLASS:EmployeeService", "CLASS:EmployeeRepository"))
        self.assertTrue(graph.has_edge("CLASS:EmployeeRepository", "CLASS:Employee"))

    def test_get_architecture_graph(self):
        res = get_architecture_graph()
        self.assertNotIn("error", res)
        self.assertEqual(res["total_endpoints"], 2)
        paths = [ep["path"] for ep in res["endpoints"]]
        self.assertIn("/employees", paths)
        self.assertIn("/employees/{id}", paths)

    def test_query_code_graph_routes(self):
        res = query_code_graph(query_type="routes", target="POST")
        self.assertNotIn("error", res)
        self.assertEqual(len(res["results"]), 1)
        self.assertEqual(res["results"][0]["endpoint"], "POST /employees")

    def test_query_code_graph_dependencies(self):
        res = query_code_graph(query_type="dependencies", target="EmployeeController")
        self.assertNotIn("error", res)
        self.assertIn("EmployeeService", res["depends_on (outbound)"])

    def test_query_code_graph_impact(self):
        res = query_code_graph(query_type="impact", target="EmployeeRepository")
        self.assertNotIn("error", res)
        self.assertIn("EmployeeService", res["impacted_components"])
        self.assertIn("EmployeeController", res["impacted_components"])


if __name__ == "__main__":
    unittest.main()
