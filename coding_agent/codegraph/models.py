"""Data models and type definitions for CodeGraph repository intelligence."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SymbolNode:
    """Represents a code symbol (class, interface, method, field) within the AST graph."""
    symbol_id: str                      # Fully qualified identifier (e.g. com.demo.employee.entity.Employee#getEmail)
    file_path: str                      # Relative path within workspace (e.g. src/main/java/...)
    name: str                           # Short name (e.g. Employee, create, email)
    kind: str                           # class, interface, enum, record, method, field, constructor
    package: str = ""                   # Package name (e.g. com.demo.employee)
    component_type: str = "Unknown"     # Controller, Service, Repository, Entity, Configuration, Test, Component, Unknown
    annotations: List[str] = field(default_factory=list)      # e.g. ['RestController', 'Valid', 'Email']
    signature: str = ""                 # e.g. public ResponseEntity<Employee> create(Employee employee)
    return_type: Optional[str] = None   # e.g. ResponseEntity<Employee>
    parameters: List[str] = field(default_factory=list)       # e.g. ['Employee employee']
    super_class: Optional[str] = None   # Extended class if any
    interfaces: List[str] = field(default_factory=list)       # Implemented interfaces if any
    start_line: int = 0
    end_line: int = 0
    docstring: Optional[str] = None


@dataclass
class DependencyEdge:
    """Represents a relationship between symbols (calls, injects, inherits, references)."""
    source_symbol_id: str
    target_symbol_id: str               # Target symbol or target type name
    relation_kind: str                  # calls, injects, extends, implements, references, tests
    resolved: bool = False              # True if target symbol was resolved inside repo; False if external/unresolved
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProjectSummary:
    """High-level architectural overview of the repository."""
    root_path: str
    total_files: int
    total_symbols: int
    layers: Dict[str, List[str]]        # e.g. {'controllers': [...], 'services': [...], 'repositories': [...], 'entities': [...], 'tests': [...]}
    entry_points: List[str]             # @SpringBootApplication or main methods
    unresolved_dependencies_count: int
    summary_text: str


@dataclass
class SymbolContextPackage:
    """Bounded context package passed to Gemini for targeted code reasoning."""
    primary_symbol: SymbolNode
    source_snippet: str
    inbound_dependencies: List[DependencyEdge]    # Who calls / injects this
    outbound_dependencies: List[DependencyEdge]   # What this calls / injects
    related_tests: List[str]                      # Test files/classes exercising this
    formatted_context: str
