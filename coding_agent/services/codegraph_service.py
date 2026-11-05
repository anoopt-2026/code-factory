"""Service layer coordinating CodeGraph database, indexer, and retriever for the agent."""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..codegraph.db import CodeGraphDatabase
from ..codegraph.indexer import CodeGraphIndexer
from ..codegraph.parser import TREE_SITTER_AVAILABLE
from ..codegraph.retriever import CodeGraphRetriever
from ..tools.repository_tools import _get_target_repo

logger = logging.getLogger(__name__)


class CodeGraphService:
    """Manages CodeGraph lifecycle, database storage, indexing, and high-level query operations."""

    _instance: Optional["CodeGraphService"] = None

    def __init__(self, target_repo: Optional[Path] = None, use_memory_db: bool = False):
        self.repo_path = (target_repo or _get_target_repo()).resolve()
        self.use_memory_db = use_memory_db
        self.db: Optional[CodeGraphDatabase] = None
        self.indexer: Optional[CodeGraphIndexer] = None
        self.retriever: Optional[CodeGraphRetriever] = None
        self._is_indexed = False
        self._init_components()

    @classmethod
    def get_instance(cls, target_repo: Optional[Path] = None, force_refresh: bool = False) -> "CodeGraphService":
        """Get or initialize singleton CodeGraphService for current repository."""
        current_target = (target_repo or _get_target_repo()).resolve()
        if cls._instance is None or force_refresh or cls._instance.repo_path != current_target:
            if cls._instance and cls._instance.db:
                cls._instance.close()
            cls._instance = cls(target_repo=current_target)
        return cls._instance

    @staticmethod
    def is_enabled() -> bool:
        """Check if CodeGraph feature is enabled via environment."""
        val = os.getenv("CODEGRAPH_ENABLED", "true").strip().lower()
        return val in ("true", "1", "yes", "on")

    @staticmethod
    def is_parser_available() -> bool:
        """Check if Tree-sitter Java parser is available."""
        return TREE_SITTER_AVAILABLE

    def _init_components(self):
        """Initialize database, indexer, and retriever."""
        if not self.is_parser_available():
            logger.warning("CodeGraph: Tree-sitter parser is unavailable. CodeGraph service running in degraded mode.")
            return

        try:
            if self.use_memory_db:
                self.db = CodeGraphDatabase()
            else:
                db_dir = self.repo_path / ".codegraph"
                db_dir.mkdir(parents=True, exist_ok=True)
                db_path = db_dir / "codegraph.db"
                self.db = CodeGraphDatabase(db_path=db_path)

            self.indexer = CodeGraphIndexer(root_dir=self.repo_path, db=self.db)
            self.retriever = CodeGraphRetriever(root_dir=self.repo_path, db=self.db)
        except Exception as e:
            logger.error("Failed to initialize CodeGraph database at %s: %s", self.repo_path, e)
            # Fallback to in-memory db on disk error
            try:
                self.db = CodeGraphDatabase()
                self.indexer = CodeGraphIndexer(root_dir=self.repo_path, db=self.db)
                self.retriever = CodeGraphRetriever(root_dir=self.repo_path, db=self.db)
            except Exception as e2:
                logger.error("Failed in-memory fallback for CodeGraph: %s", e2)
                self.db = None
                self.indexer = None
                self.retriever = None

    def close(self):
        """Close database connection."""
        if self.db:
            try:
                self.db.close()
            except Exception:
                pass
            self.db = None

    def ensure_indexed(self, force: bool = False) -> Dict[str, Any]:
        """Ensure the target repository is indexed with fresh AST symbols."""
        if not self.is_enabled():
            return {
                "status": "disabled",
                "message": "CodeGraph is disabled via CODEGRAPH_ENABLED=false.",
                "fallback": "Use list_project_files and read_project_file.",
            }

        if not self.is_parser_available() or not self.indexer:
            return {
                "status": "unavailable",
                "message": "CodeGraph Tree-sitter parser is not available.",
                "fallback": "Use list_project_files and read_project_file.",
            }

        try:
            indexed_count = self.indexer.index_repository(force=force)
            self._is_indexed = True
            return {
                "status": "success",
                "indexed_files": indexed_count,
                "repository": str(self.repo_path),
            }
        except Exception as e:
            logger.error("Error during CodeGraph indexing: %s", e)
            return {
                "status": "error",
                "error": str(e),
                "fallback": "Use list_project_files and read_project_file.",
            }

    def search_symbols(self, query: str, limit: int = 10) -> Dict[str, Any]:
        """Search classes, interfaces, methods, or fields matching query."""
        if not query or not query.strip():
            return {"error": "Query cannot be empty."}

        check = self._check_ready()
        if check:
            return check

        try:
            self.ensure_indexed()
            results = self.retriever.find_relevant_symbols(query.strip(), limit=limit)
            return {
                "query": query,
                "total_matches": len(results),
                "symbols": results,
            }
        except Exception as e:
            return {"error": f"CodeGraph search failed: {e}", "fallback": "Use list_project_files."}

    def get_symbol_definition(self, symbol_name: str, include_source_snippet: bool = True) -> Dict[str, Any]:
        """Retrieve detailed definition and declaration of a class, method, or field."""
        if not symbol_name or not symbol_name.strip():
            return {"error": "symbol_name cannot be empty."}

        check = self._check_ready()
        if check:
            return check

        try:
            self.ensure_indexed()
            res = self.retriever.get_symbol_definition(symbol_name.strip(), include_source_snippet=include_source_snippet)
            return res
        except Exception as e:
            return {"error": f"CodeGraph get_symbol_definition failed: {e}", "fallback": "Use read_project_file."}

    def find_callers_and_callees(self, symbol_name: str) -> Dict[str, Any]:
        """Find callers (inbound) and callees (outbound) for a symbol."""
        if not symbol_name or not symbol_name.strip():
            return {"error": "symbol_name cannot be empty."}

        check = self._check_ready()
        if check:
            return check

        try:
            self.ensure_indexed()
            res = self.retriever.find_callers_and_callees(symbol_name.strip())
            return res
        except Exception as e:
            return {"error": f"CodeGraph find_callers_and_callees failed: {e}", "fallback": "Use read_project_file."}

    def get_dependency_context(self, symbol_name: str, depth: int = 1, include_source_snippet: bool = True) -> Dict[str, Any]:
        """Retrieve structured inbound/outbound dependency graph, related tests, and snippet."""
        if not symbol_name or not symbol_name.strip():
            return {"error": "symbol_name cannot be empty."}

        check = self._check_ready()
        if check:
            return check

        try:
            self.ensure_indexed()
            res = self.retriever.get_dependency_context(
                symbol_name.strip(), depth=depth, include_source_snippet=include_source_snippet
            )
            return res
        except Exception as e:
            return {"error": f"CodeGraph get_dependency_context failed: {e}", "fallback": "Use read_project_file."}

    def get_code_graph_summary(self) -> Dict[str, Any]:
        """Retrieve architectural summary of repository layers and metrics."""
        check = self._check_ready()
        if check:
            return check

        try:
            self.ensure_indexed()
            res = self.retriever.get_project_summary()
            return res
        except Exception as e:
            return {"error": f"CodeGraph get_code_graph_summary failed: {e}", "fallback": "Use list_project_files."}

    def _check_ready(self) -> Optional[Dict[str, Any]]:
        """Verify service is enabled and initialized."""
        if not self.is_enabled():
            return {
                "status": "disabled",
                "message": "CodeGraph is disabled via CODEGRAPH_ENABLED=false.",
                "fallback": "Use list_project_files and read_project_file.",
            }
        if not self.is_parser_available() or not self.retriever:
            return {
                "status": "unavailable",
                "message": "CodeGraph AST parser is unavailable.",
                "fallback": "Use list_project_files and read_project_file.",
            }
        return None
