import os
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
import networkx as nx

from .repository_tools import _get_target_repo

# Regular expressions for Java code elements
PACKAGE_RE = re.compile(r"package\s+([a-zA-Z0-9_.]+)\s*;")
IMPORT_RE = re.compile(r"import\s+([a-zA-Z0-9_.*]+)\s*;")

CLASS_RE = re.compile(
    r"((?:@\w+(?:\([^)]*\))?\s*)*)"  # Annotations
    r"(?:public\s+|protected\s+|private\s+)?(?:abstract\s+|final\s+)?"
    r"(class|interface|record|enum)\s+([A-Za-z0-9_]+)"  # Type & Name
    r"(?:\s+extends\s+([A-Za-z0-9_<>,\s]+))?"  # Extends
    r"(?:\s+implements\s+([A-Za-z0-9_<>,\s]+))?"  # Implements
    r"\s*\{",
    re.MULTILINE,
)

METHOD_RE = re.compile(
    r"((?:@\w+(?:\([^)]*\))?\s*)*)"  # Annotations
    r"(?:public\s+|protected\s+|private\s+)?(?:static\s+|final\s+)?"
    r"([A-Za-z0-9_<>,\[\]\s]+)\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)"  # Return type, Name, Parameters
    r"\s*(?:throws\s+[A-Za-z0-9_,\s]+)?\s*[{;]",
    re.MULTILINE,
)

ANNOTATION_PATH_RE = re.compile(r'@(?:RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)(?:\((?:value\s*=\s*)?["\']([^"\']*)["\']|\(\s*["\']([^"\']*)["\'])?')


def _clean_path(base: str, sub: str) -> str:
    """Combine base path and subpath into clean normalized URI."""
    base = base.strip().strip('"').strip("'")
    sub = sub.strip().strip('"').strip("'")
    if not base.startswith("/"):
        base = "/" + base if base else ""
    if base.endswith("/"):
        base = base[:-1]
    if sub and not sub.startswith("/"):
        sub = "/" + sub
    combined = (base + sub).strip()
    return combined if combined else "/"


def _extract_annotation_path(annotation_str: str) -> str:
    """Extract path string from a mapping annotation like @GetMapping('/{id}')."""
    match = ANNOTATION_PATH_RE.search(annotation_str)
    if match:
        return match.group(1) or match.group(2) or ""
    return ""


def build_code_graph(repo_path: Optional[Path] = None) -> nx.DiGraph:
    """Parse the Java repository and build an in-memory NetworkX directed graph."""
    repo = repo_path or _get_target_repo()
    graph = nx.DiGraph()

    java_files = []
    for search_dir in ["src/main/java", "src/test/java"]:
        dir_path = repo / search_dir
        if dir_path.is_dir():
            java_files.extend(list(dir_path.rglob("*.java")))

    classes_by_name = {}

    # Phase 1: Discover classes, interfaces, records
    for jf in java_files:
        rel_path = jf.relative_to(repo).as_posix()
        try:
            content = jf.read_text(encoding="utf-8")
        except Exception:
            continue

        pkg_match = PACKAGE_RE.search(content)
        pkg = pkg_match.group(1) if pkg_match else ""

        for match in CLASS_RE.finditer(content):
            annotations = match.group(1).strip()
            kind = match.group(2)
            name = match.group(3)
            extends_clause = match.group(4) or ""
            implements_clause = match.group(5) or ""

            # Calculate approximate line number
            line_no = content[:match.start()].count("\n") + 1

            class_type = "class"
            if "@RestController" in annotations or "@Controller" in annotations:
                class_type = "controller"
            elif "@Service" in annotations:
                class_type = "service"
            elif "@Repository" in annotations or "Repository" in name:
                class_type = "repository"
            elif "@Entity" in annotations:
                class_type = "entity"
            elif "@SpringBootTest" in annotations or "Test" in name:
                class_type = "test"

            # Base route from @RequestMapping on class
            base_route = ""
            if "@RequestMapping" in annotations:
                base_route = _extract_annotation_path(annotations)

            node_id = f"CLASS:{name}"
            class_info = {
                "name": name,
                "node_id": node_id,
                "kind": kind,
                "type": class_type,
                "package": pkg,
                "file": rel_path,
                "line": line_no,
                "annotations": annotations,
                "base_route": base_route,
                "extends": extends_clause.strip(),
                "implements": implements_clause.strip(),
                "methods": [],
            }
            classes_by_name[name] = class_info
            graph.add_node(node_id, **class_info)

    # Phase 2: Parse methods, routes, and bean injection relationships
    for jf in java_files:
        rel_path = jf.relative_to(repo).as_posix()
        try:
            content = jf.read_text(encoding="utf-8")
        except Exception:
            continue

        for cls_name, cls_info in list(classes_by_name.items()):
            if cls_info["file"] != rel_path:
                continue

            for m_match in METHOD_RE.finditer(content):
                m_annot = m_match.group(1).strip()
                ret_type = m_match.group(2).strip()
                m_name = m_match.group(3).strip()
                params = m_match.group(4).strip()
                line_no = content[:m_match.start()].count("\n") + 1

                # Skip constructor or methods belonging to other classes
                if m_name == cls_name:
                    # Constructor injection: check if params inject other known beans
                    for param in params.split(","):
                        param_clean = param.strip()
                        if not param_clean:
                            continue
                        param_type = param_clean.split()[0].split("<")[0]
                        if param_type in classes_by_name and param_type != cls_name:
                            dep_node = f"CLASS:{param_type}"
                            graph.add_edge(cls_info["node_id"], dep_node, relationship="INJECTS")
                    continue

                method_info = {
                    "name": m_name,
                    "return_type": ret_type,
                    "parameters": params,
                    "annotations": m_annot,
                    "line": line_no,
                }
                cls_info["methods"].append(method_info)

                # HTTP Endpoints discovery for controllers
                http_methods = [
                    ("@GetMapping", "GET"),
                    ("@PostMapping", "POST"),
                    ("@PutMapping", "PUT"),
                    ("@DeleteMapping", "DELETE"),
                    ("@PatchMapping", "PATCH"),
                ]
                for annot_name, http_verb in http_methods:
                    if annot_name in m_annot:
                        subpath = _extract_annotation_path(m_annot)
                        full_path = _clean_path(cls_info.get("base_route", ""), subpath)
                        endpoint_id = f"ENDPOINT:{http_verb} {full_path}"

                        endpoint_info = {
                            "type": "endpoint",
                            "http_method": http_verb,
                            "path": full_path,
                            "handler_class": cls_name,
                            "handler_method": m_name,
                            "parameters": params,
                            "return_type": ret_type,
                            "file": rel_path,
                            "line": line_no,
                        }
                        graph.add_node(endpoint_id, **endpoint_info)
                        graph.add_edge(endpoint_id, cls_info["node_id"], relationship="HANDLED_BY")

            # Check entity managed by repository: extends JpaRepository<Employee, Long>
            ext = cls_info.get("extends", "")
            if "JpaRepository" in ext or "CrudRepository" in ext:
                match = re.search(r"(?:JpaRepository|CrudRepository)<([A-Za-z0-9_]+)", ext)
                if match:
                    entity_name = match.group(1)
                    if entity_name in classes_by_name:
                        graph.add_edge(cls_info["node_id"], f"CLASS:{entity_name}", relationship="MANAGES")

    return graph


def get_architecture_graph(issue_key: Optional[str] = None) -> dict:
    """Return a concise, high-level map of the Spring Boot application architecture.

    Provides all REST endpoints, service beans, repositories, JPA entities, and tests in one call.
    """
    try:
        graph = build_code_graph()
        controllers = []
        services = []
        repositories = []
        entities = []
        tests = []
        routes = []

        for node_id, data in graph.nodes(data=True):
            node_type = data.get("type")
            if node_type == "endpoint":
                routes.append({
                    "method": data.get("http_method"),
                    "path": data.get("path"),
                    "controller": data.get("handler_class"),
                    "handler": data.get("handler_method"),
                    "returns": data.get("return_type"),
                    "file": data.get("file"),
                    "line": data.get("line"),
                })
            elif node_type == "controller":
                injected = [v.replace("CLASS:", "") for u, v, d in graph.out_edges(node_id, data=True) if d.get("relationship") == "INJECTS"]
                controllers.append({
                    "name": data.get("name"),
                    "file": data.get("file"),
                    "base_route": data.get("base_route"),
                    "injects": injected,
                })
            elif node_type == "service":
                injected = [v.replace("CLASS:", "") for u, v, d in graph.out_edges(node_id, data=True) if d.get("relationship") == "INJECTS"]
                services.append({
                    "name": data.get("name"),
                    "file": data.get("file"),
                    "injects": injected,
                })
            elif node_type == "repository":
                manages = [v.replace("CLASS:", "") for u, v, d in graph.out_edges(node_id, data=True) if d.get("relationship") == "MANAGES"]
                repositories.append({
                    "name": data.get("name"),
                    "file": data.get("file"),
                    "manages": manages[0] if manages else "Unknown",
                    "custom_methods": [m["name"] for m in data.get("methods", [])],
                })
            elif node_type == "entity":
                entities.append({
                    "name": data.get("name"),
                    "file": data.get("file"),
                    "methods": [m["name"] for m in data.get("methods", [])],
                })
            elif node_type == "test":
                tests.append({
                    "name": data.get("name"),
                    "file": data.get("file"),
                })

        return {
            "total_endpoints": len(routes),
            "endpoints": sorted(routes, key=lambda r: (r["path"], r["method"])),
            "controllers": controllers,
            "services": services,
            "repositories": repositories,
            "entities": entities,
            "tests": tests,
            "summary": f"Discovered {len(routes)} REST endpoints, {len(services)} services, {len(repositories)} repositories, {len(entities)} entities across project.",
        }
    except Exception as exc:
        return {"error": f"Failed to build architecture graph: {exc}"}


def query_code_graph(query_type: str, target: str = "", issue_key: Optional[str] = None) -> dict:
    """Query the project code graph for specific architectural elements.

    Args:
        query_type: Type of query: 'routes', 'dependencies', 'symbol', 'impact'.
        target: Target name, path, or symbol depending on query_type.
        issue_key: Optional Jira ticket key for context.
    """
    try:
        graph = build_code_graph()
        q = query_type.lower().strip()

        if q in ("routes", "endpoints"):
            matching = []
            for node_id, data in graph.nodes(data=True):
                if data.get("type") == "endpoint":
                    if not target or target.lower() in data.get("path", "").lower() or target.upper() == data.get("http_method"):
                        matching.append({
                            "endpoint": f"{data.get('http_method')} {data.get('path')}",
                            "controller": data.get("handler_class"),
                            "handler": data.get("handler_method"),
                            "parameters": data.get("parameters"),
                            "returns": data.get("return_type"),
                            "file": data.get("file"),
                            "line": data.get("line"),
                        })
            return {"query": query_type, "target": target, "results": matching}

        elif q in ("dependencies", "deps"):
            target_clean = target.strip()
            node_id = f"CLASS:{target_clean}"
            if not graph.has_node(node_id):
                return {"error": f"Symbol '{target_clean}' not found in code graph."}

            depends_on = [v.replace("CLASS:", "") for u, v, d in graph.out_edges(node_id, data=True)]
            depended_by = [u.replace("CLASS:", "") for u, v, d in graph.in_edges(node_id, data=True)]

            return {
                "symbol": target_clean,
                "depends_on (outbound)": depends_on,
                "depended_by (inbound)": depended_by,
                "file": graph.nodes[node_id].get("file"),
                "line": graph.nodes[node_id].get("line"),
            }

        elif q == "symbol":
            target_clean = target.strip()
            results = []
            for node_id, data in graph.nodes(data=True):
                if data.get("name") == target_clean:
                    results.append({
                        "symbol": data.get("name"),
                        "type": data.get("type"),
                        "kind": data.get("kind"),
                        "file": data.get("file"),
                        "line": data.get("line"),
                        "package": data.get("package"),
                        "methods": [m["name"] for m in data.get("methods", [])],
                    })
                # Check method match
                for m in data.get("methods", []):
                    if m["name"] == target_clean:
                        results.append({
                            "method": m["name"],
                            "class": data.get("name"),
                            "return_type": m["return_type"],
                            "parameters": m["parameters"],
                            "file": data.get("file"),
                            "line": m["line"],
                        })
            return {"query": "symbol", "target": target_clean, "matches": results}

        elif q in ("impact", "blast_radius"):
            target_clean = target.strip()
            node_id = f"CLASS:{target_clean}"
            if not graph.has_node(node_id):
                return {"error": f"Class '{target_clean}' not found in code graph."}

            # Find all upstream nodes that reach target_clean (inbound ancestors)
            upstream = nx.ancestors(graph, node_id)
            impacted_classes = [n.replace("CLASS:", "").replace("ENDPOINT:", "") for n in upstream]

            return {
                "target": target_clean,
                "impacted_components": impacted_classes,
                "total_impacted": len(impacted_classes),
                "summary": f"Modifying {target_clean} directly or indirectly impacts: {', '.join(impacted_classes) if impacted_classes else 'None'}",
            }

        else:
            return {"error": f"Unsupported query_type '{query_type}'. Use 'routes', 'dependencies', 'symbol', or 'impact'."}

    except Exception as exc:
        return {"error": f"Failed to execute code graph query: {exc}"}
