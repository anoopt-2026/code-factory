"""Targeted code intelligence and graph context retrieval for Gemini reasoning."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .db import CodeGraphDatabase

logger = logging.getLogger(__name__)


class CodeGraphRetriever:
    """Translates raw graph data into compact, bounded architectural summaries and targeted context packages."""

    def __init__(self, root_dir: Path, db: CodeGraphDatabase):
        self.root = root_dir.resolve()
        self.db = db

    def get_project_summary(self) -> Dict[str, Any]:
        """Generate a compact, structured breakdown of architectural layers and key components."""
        stats = self.db.get_project_stats()
        controllers = [s.name for s in self.db.get_symbols_by_component_type("Controller")]
        services = [s.name for s in self.db.get_symbols_by_component_type("Service")]
        repositories = [s.name for s in self.db.get_symbols_by_component_type("Repository")]
        entities = [s.name for s in self.db.get_symbols_by_component_type("Entity")]
        applications = [s.name for s in self.db.get_symbols_by_component_type("Application")]
        tests = [s.name for s in self.db.get_symbols_by_component_type("Test")]

        summary_lines = [
            f"Repository Root: {self.root}",
            f"Indexed Files: {stats['files_count']} | Symbols: {stats['symbols_count']}",
            f"Dependency Graph: {stats['resolved_dependencies_count']} resolved edges, {stats['unresolved_dependencies_count']} external/unresolved edges",
            "Layers Discovered:",
            f"  - Controllers: {', '.join(controllers) if controllers else 'None'}",
            f"  - Services: {', '.join(services) if services else 'None'}",
            f"  - Repositories: {', '.join(repositories) if repositories else 'None'}",
            f"  - Entities: {', '.join(entities) if entities else 'None'}",
            f"  - Tests: {', '.join(tests) if tests else 'None'}",
            f"  - Entry Points: {', '.join(applications) if applications else 'None'}",
        ]

        return {
            "root_path": str(self.root),
            "files_count": stats["files_count"],
            "symbols_count": stats["symbols_count"],
            "layers": {
                "controllers": controllers,
                "services": services,
                "repositories": repositories,
                "entities": entities,
                "tests": tests,
                "applications": applications,
            },
            "resolved_dependencies": stats["resolved_dependencies_count"],
            "unresolved_dependencies": stats["unresolved_dependencies_count"],
            "summary_text": "\n".join(summary_lines),
        }

    def find_relevant_symbols(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Find symbols matching a keyword query across class names, annotations, signatures, or files."""
        symbols = self.db.search_symbols(query, limit=limit)
        results = []
        for s in symbols:
            results.append({
                "symbol_id": s.symbol_id,
                "name": s.name,
                "kind": s.kind,
                "component_type": s.component_type,
                "file_path": s.file_path,
                "signature": s.signature,
                "annotations": s.annotations,
                "line_range": f"{s.start_line}-{s.end_line}",
            })
        return results

    def get_symbol_definition(self, symbol_name: str, include_source_snippet: bool = True) -> Dict[str, Any]:
        """Retrieve detailed definition and declaration of a class, method, or field."""
        candidates = self.db.find_symbols_by_name(symbol_name)
        if not candidates:
            candidates = self.db.search_symbols(symbol_name, limit=1)

        if not candidates:
            return {"error": f"Symbol '{symbol_name}' not found in CodeGraph index."}

        primary = candidates[0]
        snippet = ""
        if include_source_snippet:
            snippet = self._read_snippet(primary.file_path, primary.start_line, primary.end_line)

        return {
            "symbol_id": primary.symbol_id,
            "name": primary.name,
            "kind": primary.kind,
            "component_type": primary.component_type,
            "file_path": primary.file_path,
            "package": primary.package,
            "signature": primary.signature,
            "annotations": primary.annotations,
            "parameters": primary.parameters,
            "return_type": primary.return_type,
            "super_class": primary.super_class,
            "interfaces": primary.interfaces,
            "start_line": primary.start_line,
            "end_line": primary.end_line,
            "source_snippet": snippet,
        }

    def find_callers_and_callees(self, symbol_name: str) -> Dict[str, Any]:
        """Find callers (inbound) and callees (outbound) for a symbol."""
        candidates = self.db.find_symbols_by_name(symbol_name)
        if not candidates:
            candidates = self.db.search_symbols(symbol_name, limit=1)

        if not candidates:
            return {"error": f"Symbol '{symbol_name}' not found in CodeGraph index."}

        primary = candidates[0]
        outbound = self.db.get_outbound_edges(primary.symbol_id)
        inbound = self.db.get_inbound_edges(primary.name)

        return {
            "symbol": primary.name,
            "symbol_id": primary.symbol_id,
            "file_path": primary.file_path,
            "component_type": primary.component_type,
            "callees_outbound": [
                {"target": e.target_symbol_id, "relation": e.relation_kind, "resolved": e.resolved}
                for e in outbound
            ],
            "callers_inbound": [
                {"source": e.source_symbol_id, "relation": e.relation_kind}
                for e in inbound
            ],
        }

    def get_dependency_context(
        self,
        symbol_name: str,
        depth: int = 1,
        include_source_snippet: bool = True,
    ) -> Dict[str, Any]:
        """Retrieve structured inbound/outbound dependency graph, related tests, and snippet."""
        candidates = self.db.find_symbols_by_name(symbol_name)
        if not candidates:
            candidates = self.db.search_symbols(symbol_name, limit=1)

        if not candidates:
            return {"error": f"Symbol '{symbol_name}' not found in CodeGraph."}

        primary = candidates[0]
        outbound = self.db.get_outbound_edges(primary.symbol_id)
        inbound = self.db.get_inbound_edges(primary.name)
        related_tests = self.find_related_tests(primary.name)

        source_snippet = ""
        if include_source_snippet:
            source_snippet = self._read_snippet(primary.file_path, primary.start_line, primary.end_line)

        formatted_lines = [
            f"=== Symbol: {primary.name} ({primary.kind}, {primary.component_type}) ===",
            f"File: {primary.file_path}:{primary.start_line}-{primary.end_line}",
            f"Package: {primary.package}",
            f"Annotations: {', '.join(primary.annotations) if primary.annotations else 'None'}",
            f"Signature: {primary.signature}",
            f"Superclass: {primary.super_class or 'None'}",
            f"Interfaces: {', '.join(primary.interfaces) if primary.interfaces else 'None'}",
            f"\n--- Dependencies Called / Injected (Outbound: {len(outbound)}) ---",
        ]

        for edge in outbound:
            res_flag = "[Resolved]" if edge.resolved else "[External/JDK]"
            formatted_lines.append(f"  -> {edge.relation_kind} {edge.target_symbol_id} {res_flag}")

        formatted_lines.append(f"\n--- Depended On By (Inbound: {len(inbound)}) ---")
        for edge in inbound:
            formatted_lines.append(f"  <- {edge.source_symbol_id} ({edge.relation_kind})")

        if related_tests:
            formatted_lines.append(f"\n--- Exercised By Tests ({len(related_tests)}) ---")
            for t in related_tests:
                formatted_lines.append(f"  * {t}")

        if source_snippet:
            formatted_lines.append(f"\n--- Source Code Snippet ---\n```java\n{source_snippet}\n```")

        return {
            "symbol_id": primary.symbol_id,
            "name": primary.name,
            "kind": primary.kind,
            "component_type": primary.component_type,
            "file_path": primary.file_path,
            "package": primary.package,
            "signature": primary.signature,
            "annotations": primary.annotations,
            "super_class": primary.super_class,
            "interfaces": primary.interfaces,
            "outbound_edges": [
                {"target": e.target_symbol_id, "kind": e.relation_kind, "resolved": e.resolved}
                for e in outbound
            ],
            "inbound_edges": [
                {"source": e.source_symbol_id, "kind": e.relation_kind}
                for e in inbound
            ],
            "related_tests": related_tests,
            "source_snippet": source_snippet,
            "formatted_context": "\n".join(formatted_lines),
        }

    def find_related_tests(self, symbol_name: str) -> List[str]:
        """Identify test classes that reference or test the specified symbol."""
        tests = self.db.get_symbols_by_component_type("Test")
        related = []
        for test_sym in tests:
            edges = self.db.get_outbound_edges(test_sym.symbol_id)
            for edge in edges:
                if symbol_name.lower() in edge.target_symbol_id.lower():
                    related.append(f"{test_sym.name} ({test_sym.file_path})")
                    break
        return sorted(list(set(related)))

    def _read_snippet(self, file_path: str, start_line: int, end_line: int) -> str:
        """Safely read lines from a project source file."""
        try:
            abs_p = (self.root / file_path).resolve()
            # Ensure path is inside root
            abs_p.relative_to(self.root)
            if not abs_p.is_file():
                return ""
            lines = abs_p.read_text(encoding="utf-8", errors="replace").splitlines()
            start = max(0, start_line - 1)
            end = min(len(lines), end_line + 5)
            if end - start > 60:
                end = start + 60
            return "\n".join(lines[start:end])
        except Exception as e:
            return f"Error reading snippet: {e}"
