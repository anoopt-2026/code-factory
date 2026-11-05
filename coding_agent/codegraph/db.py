"""SQLite database storage for CodeGraph symbols and dependencies."""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import DependencyEdge, SymbolNode

logger = logging.getLogger(__name__)


class CodeGraphDatabase:
    """Manages persistent or in-memory SQLite storage for repository symbols, files, and edges."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS files (
        file_path TEXT PRIMARY KEY,
        sha256 TEXT,
        last_modified REAL,
        symbol_count INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS symbols (
        symbol_id TEXT PRIMARY KEY,
        file_path TEXT NOT NULL,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        package TEXT,
        component_type TEXT,
        annotations TEXT, -- JSON array
        signature TEXT,
        return_type TEXT,
        parameters TEXT,  -- JSON array
        super_class TEXT,
        interfaces TEXT,  -- JSON array
        start_line INTEGER,
        end_line INTEGER,
        FOREIGN KEY (file_path) REFERENCES files(file_path) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS dependencies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_symbol_id TEXT NOT NULL,
        target_symbol_id TEXT NOT NULL,
        relation_kind TEXT NOT NULL,
        resolved INTEGER DEFAULT 0,
        metadata TEXT -- JSON object
    );

    CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_path);
    CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
    CREATE INDEX IF NOT EXISTS idx_symbols_type ON symbols(component_type);
    CREATE INDEX IF NOT EXISTS idx_dep_source ON dependencies(source_symbol_id);
    CREATE INDEX IF NOT EXISTS idx_dep_target ON dependencies(target_symbol_id);
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = str(db_path) if db_path else ":memory:"
        if db_path and db_path != ":memory:":
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        with self.conn:
            self.conn.executescript(self.SCHEMA)

    def close(self):
        if self.conn:
            self.conn.close()

    def upsert_file_and_symbols(
        self,
        file_path: str,
        sha256: str,
        last_modified: float,
        symbols: List[SymbolNode],
        edges: List[DependencyEdge],
    ):
        """Atomically insert or update symbols and dependencies for a file."""
        with self.conn:
            # Clear old symbols and dependencies for this file
            old_syms = self.conn.execute("SELECT symbol_id FROM symbols WHERE file_path = ?", (file_path,)).fetchall()
            for row in old_syms:
                self.conn.execute("DELETE FROM dependencies WHERE source_symbol_id = ?", (row["symbol_id"],))
            self.conn.execute("DELETE FROM symbols WHERE file_path = ?", (file_path,))

            # Upsert file record
            self.conn.execute(
                """
                INSERT INTO files (file_path, sha256, last_modified, symbol_count)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    sha256 = excluded.sha256,
                    last_modified = excluded.last_modified,
                    symbol_count = excluded.symbol_count
                """,
                (file_path, sha256, last_modified, len(symbols)),
            )

            # Insert symbols
            for sym in symbols:
                self.conn.execute(
                    """
                    INSERT INTO symbols (
                        symbol_id, file_path, name, kind, package, component_type,
                        annotations, signature, return_type, parameters, super_class,
                        interfaces, start_line, end_line
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol_id) DO UPDATE SET
                        file_path = excluded.file_path,
                        name = excluded.name,
                        kind = excluded.kind,
                        package = excluded.package,
                        component_type = excluded.component_type,
                        annotations = excluded.annotations,
                        signature = excluded.signature,
                        return_type = excluded.return_type,
                        parameters = excluded.parameters,
                        super_class = excluded.super_class,
                        interfaces = excluded.interfaces,
                        start_line = excluded.start_line,
                        end_line = excluded.end_line
                    """,
                    (
                        sym.symbol_id,
                        sym.file_path,
                        sym.name,
                        sym.kind,
                        sym.package,
                        sym.component_type,
                        json.dumps(sym.annotations),
                        sym.signature,
                        sym.return_type,
                        json.dumps(sym.parameters),
                        sym.super_class,
                        json.dumps(sym.interfaces),
                        sym.start_line,
                        sym.end_line,
                    ),
                )

            # Insert edges
            for edge in edges:
                self.conn.execute(
                    """
                    INSERT INTO dependencies (source_symbol_id, target_symbol_id, relation_kind, resolved, metadata)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        edge.source_symbol_id,
                        edge.target_symbol_id,
                        edge.relation_kind,
                        1 if edge.resolved else 0,
                        json.dumps(edge.metadata),
                    ),
                )

    def resolve_internal_edges(self):
        """Mark edges as resolved=1 if target_symbol_id matches a known symbol_id or class name in the DB."""
        with self.conn:
            self.conn.execute(
                """
                UPDATE dependencies
                SET resolved = 1
                WHERE target_symbol_id IN (SELECT symbol_id FROM symbols)
                   OR target_symbol_id IN (SELECT name FROM symbols WHERE kind IN ('class', 'interface', 'enum', 'record'))
                """
            )

    def get_symbol_by_id(self, symbol_id: str) -> Optional[SymbolNode]:
        cursor = self.conn.execute("SELECT * FROM symbols WHERE symbol_id = ?", (symbol_id,))
        row = cursor.fetchone()
        return self._row_to_symbol(row) if row else None

    def find_symbols_by_name(self, name: str) -> List[SymbolNode]:
        cursor = self.conn.execute("SELECT * FROM symbols WHERE name = ? COLLATE NOCASE", (name,))
        return [self._row_to_symbol(r) for r in cursor.fetchall()]

    def search_symbols(self, query: str, limit: int = 10) -> List[SymbolNode]:
        """Search symbols by name, annotations, signature, or package."""
        q = f"%{query}%"
        cursor = self.conn.execute(
            """
            SELECT * FROM symbols
            WHERE name LIKE ?
               OR annotations LIKE ?
               OR signature LIKE ?
               OR file_path LIKE ?
            ORDER BY
                CASE
                    WHEN name = ? THEN 1
                    WHEN name LIKE ? THEN 2
                    ELSE 3
                END,
                kind ASC
            LIMIT ?
            """,
            (q, q, q, q, query, f"{query}%", limit),
        )
        return [self._row_to_symbol(r) for r in cursor.fetchall()]

    def get_symbols_by_component_type(self, component_type: str) -> List[SymbolNode]:
        cursor = self.conn.execute(
            "SELECT * FROM symbols WHERE component_type = ? AND kind IN ('class', 'interface')",
            (component_type,),
        )
        return [self._row_to_symbol(r) for r in cursor.fetchall()]

    def get_outbound_edges(self, source_symbol_id: str) -> List[DependencyEdge]:
        cursor = self.conn.execute(
            "SELECT * FROM dependencies WHERE source_symbol_id = ? OR source_symbol_id LIKE ?",
            (source_symbol_id, f"{source_symbol_id}#%"),
        )
        return [self._row_to_edge(r) for r in cursor.fetchall()]

    def get_inbound_edges(self, target_name_or_id: str) -> List[DependencyEdge]:
        cursor = self.conn.execute(
            "SELECT * FROM dependencies WHERE target_symbol_id = ? OR target_symbol_id LIKE ? OR target_symbol_id LIKE ?",
            (target_name_or_id, f"%.{target_name_or_id}", f"{target_name_or_id}.%"),
        )
        return [self._row_to_edge(r) for r in cursor.fetchall()]

    def get_file_metadata(self, file_path: str) -> Optional[Tuple[str, float]]:
        cursor = self.conn.execute("SELECT sha256, last_modified FROM files WHERE file_path = ?", (file_path,))
        row = cursor.fetchone()
        return (row["sha256"], row["last_modified"]) if row else None

    def get_project_stats(self) -> Dict[str, Any]:
        with self.conn:
            files_count = self.conn.execute("SELECT COUNT(*) as c FROM files").fetchone()["c"]
            symbols_count = self.conn.execute("SELECT COUNT(*) as c FROM symbols").fetchone()["c"]
            deps_count = self.conn.execute("SELECT COUNT(*) as c FROM dependencies").fetchone()["c"]
            resolved_deps = self.conn.execute("SELECT COUNT(*) as c FROM dependencies WHERE resolved = 1").fetchone()["c"]
            return {
                "files_count": files_count,
                "symbols_count": symbols_count,
                "dependencies_count": deps_count,
                "resolved_dependencies_count": resolved_deps,
                "unresolved_dependencies_count": deps_count - resolved_deps,
            }

    def _row_to_symbol(self, row: sqlite3.Row) -> SymbolNode:
        return SymbolNode(
            symbol_id=row["symbol_id"],
            file_path=row["file_path"],
            name=row["name"],
            kind=row["kind"],
            package=row["package"] or "",
            component_type=row["component_type"] or "Unknown",
            annotations=json.loads(row["annotations"]) if row["annotations"] else [],
            signature=row["signature"] or "",
            return_type=row["return_type"],
            parameters=json.loads(row["parameters"]) if row["parameters"] else [],
            super_class=row["super_class"],
            interfaces=json.loads(row["interfaces"]) if row["interfaces"] else [],
            start_line=row["start_line"],
            end_line=row["end_line"],
        )

    def _row_to_edge(self, row: sqlite3.Row) -> DependencyEdge:
        return DependencyEdge(
            source_symbol_id=row["source_symbol_id"],
            target_symbol_id=row["target_symbol_id"],
            relation_kind=row["relation_kind"],
            resolved=bool(row["resolved"]),
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )
