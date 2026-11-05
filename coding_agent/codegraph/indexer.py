"""Repository indexer coordinating AST parsing and SQLite graph updates."""

import hashlib
import logging
import os
from pathlib import Path
from typing import List, Optional, Set

from .db import CodeGraphDatabase
from .models import DependencyEdge, SymbolNode
from .parser import JavaASTParser

logger = logging.getLogger(__name__)


class CodeGraphIndexer:
    """Scans repository Java files, extracts AST symbols via Tree-sitter, and maintains an SQLite graph."""

    EXCLUDED_DIRS: Set[str] = {
        "build",
        ".gradle",
        "target",
        "out",
        "node_modules",
        ".git",
        ".idea",
        ".vscode",
        "__pycache__",
        ".pytest_cache",
        ".codegraph",
        ".venv",
    }

    def __init__(self, root_dir: Path, db: Optional[CodeGraphDatabase] = None):
        self.root = root_dir.resolve()
        self.db = db or CodeGraphDatabase()
        self.parser = JavaASTParser()

    def index_repository(self, force: bool = False) -> int:
        """Scan workspace for Java files, parse ASTs, and populate database.

        Args:
            force: If True, re-indexes all files regardless of modification time or hash.

        Returns:
            Number of files indexed or updated.
        """
        indexed_count = 0
        java_files = self._find_java_files()
        logger.info("Found %d Java files to inspect in %s", len(java_files), self.root)

        for rel_path in java_files:
            abs_path = self.root / rel_path
            try:
                if not abs_path.is_file():
                    continue

                mtime = abs_path.stat().st_mtime
                content = abs_path.read_text(encoding="utf-8", errors="replace")
                sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()

                # Check if re-index is necessary
                if not force:
                    cached_meta = self.db.get_file_metadata(rel_path)
                    if cached_meta and cached_meta[0] == sha256:
                        continue  # File unchanged

                symbols, edges = self.parser.parse_file(rel_path, content)
                self.db.upsert_file_and_symbols(
                    file_path=rel_path,
                    sha256=sha256,
                    last_modified=mtime,
                    symbols=symbols,
                    edges=edges,
                )
                indexed_count += 1

            except Exception as e:
                logger.warning("Failed indexing %s: %s", rel_path, e)

        # Resolve inter-symbol and inter-class edges
        self.db.resolve_internal_edges()
        logger.info("CodeGraph indexing complete. Indexed %d files.", indexed_count)
        return indexed_count

    def _find_java_files(self) -> List[str]:
        """Find all Java source files respecting exclusions and sandbox limits."""
        files = []
        for root, dirs, filenames in os.walk(str(self.root)):
            dirs[:] = [d for d in dirs if d not in self.EXCLUDED_DIRS and not d.startswith(".")]
            for f in filenames:
                if f.endswith(".java") and not f.startswith("."):
                    full_p = Path(root) / f
                    try:
                        rel = str(full_p.relative_to(self.root)).replace("\\", "/")
                        files.append(rel)
                    except ValueError:
                        pass
        return sorted(files)
