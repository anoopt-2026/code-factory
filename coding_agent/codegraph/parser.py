"""Tree-sitter AST parser for Java and Spring Boot source files."""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Attempt to load Tree-sitter Java Language
try:
    import tree_sitter
    import tree_sitter_java
    from tree_sitter import Language, Node, Parser
    JAVA_LANGUAGE = Language(tree_sitter_java.language())
    TREE_SITTER_AVAILABLE = True
except Exception as e:
    JAVA_LANGUAGE = None
    Parser = None
    Node = Any
    TREE_SITTER_AVAILABLE = False
    logger.warning("Tree-sitter Java parser is not available: %s", e)

from .models import DependencyEdge, SymbolNode


class JavaASTParser:
    """Extracts symbols, inheritance, annotations, calls, and dependencies from Java code using Tree-sitter."""

    def __init__(self):
        if not TREE_SITTER_AVAILABLE:
            self.parser = None
        else:
            self.parser = Parser(JAVA_LANGUAGE)

    def is_available(self) -> bool:
        return self.parser is not None

    def parse_file(
        self,
        relative_path: str,
        content: str,
    ) -> Tuple[List[SymbolNode], List[DependencyEdge]]:
        """Parse a single Java source file into SymbolNodes and DependencyEdges."""
        symbols: List[SymbolNode] = []
        edges: List[DependencyEdge] = []

        if not self.is_available():
            logger.warning("Tree-sitter is unavailable, skipping AST parse for %s", relative_path)
            return symbols, edges

        try:
            source_bytes = content.encode("utf-8")
            tree = self.parser.parse(source_bytes)
            root = tree.root_node

            package_name = self._extract_package(root, source_bytes)
            imports = self._extract_imports(root, source_bytes)

            self._traverse_node(
                node=root,
                source=source_bytes,
                file_path=relative_path,
                package_name=package_name,
                imports=imports,
                symbols=symbols,
                edges=edges,
                parent_symbol_id=None,
            )

        except Exception as e:
            logger.warning("Failed to parse Java file with tree-sitter %s: %s", relative_path, e)

        return symbols, edges

    def _extract_package(self, root: Node, source: bytes) -> str:
        for child in root.children:
            if child.type == "package_declaration":
                for sub in child.children:
                    if sub.type in ("scoped_identifier", "identifier"):
                        return source[sub.start_byte:sub.end_byte].decode("utf-8")
        return ""

    def _extract_imports(self, root: Node, source: bytes) -> List[str]:
        imports = []
        for child in root.children:
            if child.type == "import_declaration":
                for sub in child.children:
                    if sub.type in ("scoped_identifier", "identifier"):
                        imports.append(source[sub.start_byte:sub.end_byte].decode("utf-8"))
        return imports

    def _traverse_node(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        package_name: str,
        imports: List[str],
        symbols: List[SymbolNode],
        edges: List[DependencyEdge],
        parent_symbol_id: Optional[str],
    ) -> None:
        if node.type in ("class_declaration", "interface_declaration", "enum_declaration", "record_declaration"):
            class_symbol = self._parse_type_declaration(
                node=node,
                source=source,
                file_path=file_path,
                package_name=package_name,
                imports=imports,
                edges=edges,
            )
            symbols.append(class_symbol)
            parent_symbol_id = class_symbol.symbol_id

            # Parse children inside the class body
            for child in node.children:
                if child.type in ("class_body", "interface_body"):
                    for member in child.children:
                        self._traverse_node(
                            node=member,
                            source=source,
                            file_path=file_path,
                            package_name=package_name,
                            imports=imports,
                            symbols=symbols,
                            edges=edges,
                            parent_symbol_id=parent_symbol_id,
                        )
            return

        if node.type in ("method_declaration", "constructor_declaration"):
            method_symbol = self._parse_method_declaration(
                node=node,
                source=source,
                file_path=file_path,
                package_name=package_name,
                parent_symbol_id=parent_symbol_id,
                edges=edges,
            )
            symbols.append(method_symbol)
            return

        if node.type == "field_declaration" and parent_symbol_id:
            field_symbols = self._parse_field_declaration(
                node=node,
                source=source,
                file_path=file_path,
                package_name=package_name,
                parent_symbol_id=parent_symbol_id,
                edges=edges,
            )
            symbols.extend(field_symbols)
            return

        # Generic recursion for top-level root
        for child in node.children:
            self._traverse_node(
                node=child,
                source=source,
                file_path=file_path,
                package_name=package_name,
                imports=imports,
                symbols=symbols,
                edges=edges,
                parent_symbol_id=parent_symbol_id,
            )

    def _parse_type_declaration(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        package_name: str,
        imports: List[str],
        edges: List[DependencyEdge],
    ) -> SymbolNode:
        name = ""
        super_class = None
        interfaces: List[str] = []
        annotations: List[str] = []

        # Find modifiers / annotations
        for child in node.children:
            if child.type == "modifiers":
                for mod_child in child.children:
                    if mod_child.type in ("annotation", "marker_annotation"):
                        ann_name = self._extract_annotation_name(mod_child, source)
                        if ann_name:
                            annotations.append(ann_name)
            elif child.type == "identifier":
                name = source[child.start_byte:child.end_byte].decode("utf-8")
            elif child.type == "superclass":
                for sc in child.children:
                    if sc.type in ("type_identifier", "scoped_type_identifier", "generic_type"):
                        super_class = source[sc.start_byte:sc.end_byte].decode("utf-8")
            elif child.type in ("super_interfaces", "extends_interfaces"):
                for iface_child in child.children:
                    if iface_child.type == "type_list":
                        for tl in iface_child.children:
                            if tl.type in ("type_identifier", "scoped_type_identifier", "generic_type"):
                                interfaces.append(source[tl.start_byte:tl.end_byte].decode("utf-8"))

        kind = "class"
        if node.type == "interface_declaration":
            kind = "interface"
        elif node.type == "enum_declaration":
            kind = "enum"
        elif node.type == "record_declaration":
            kind = "record"

        symbol_id = f"{package_name}.{name}" if package_name else name
        component_type = self._classify_spring_component(annotations, name, file_path, interfaces)

        # Record inheritance edges
        if super_class:
            edges.append(
                DependencyEdge(
                    source_symbol_id=symbol_id,
                    target_symbol_id=super_class,
                    relation_kind="extends",
                    resolved=False,
                )
            )
        for iface in interfaces:
            edges.append(
                DependencyEdge(
                    source_symbol_id=symbol_id,
                    target_symbol_id=iface,
                    relation_kind="implements",
                    resolved=False,
                )
            )

        # Record import dependencies
        for imp in imports:
            edges.append(
                DependencyEdge(
                    source_symbol_id=symbol_id,
                    target_symbol_id=imp,
                    relation_kind="references",
                    resolved=False,
                )
            )

        return SymbolNode(
            symbol_id=symbol_id,
            file_path=file_path,
            name=name,
            kind=kind,
            package=package_name,
            component_type=component_type,
            annotations=annotations,
            signature=f"{kind} {name}",
            super_class=super_class,
            interfaces=interfaces,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

    def _parse_method_declaration(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        package_name: str,
        parent_symbol_id: Optional[str],
        edges: List[DependencyEdge],
    ) -> SymbolNode:
        name = ""
        return_type = "void"
        parameters: List[str] = []
        annotations: List[str] = []

        for child in node.children:
            if child.type == "modifiers":
                for mod_child in child.children:
                    if mod_child.type in ("annotation", "marker_annotation"):
                        ann_name = self._extract_annotation_name(mod_child, source)
                        if ann_name:
                            annotations.append(ann_name)
            elif child.type in ("type_identifier", "void_type", "integral_type", "floating_point_type", "boolean_type", "generic_type", "scoped_type_identifier"):
                return_type = source[child.start_byte:child.end_byte].decode("utf-8")
            elif child.type == "identifier":
                name = source[child.start_byte:child.end_byte].decode("utf-8")
            elif child.type == "formal_parameters":
                for p in child.children:
                    if p.type == "formal_parameter":
                        param_str = source[p.start_byte:p.end_byte].decode("utf-8").strip()
                        parameters.append(param_str)

        kind = "constructor" if node.type == "constructor_declaration" else "method"
        symbol_id = f"{parent_symbol_id}#{name}" if parent_symbol_id else name
        sig = f"{return_type} {name}({', '.join(parameters)})"

        # Look for method call invocations inside the method body
        for body_child in node.children:
            if body_child.type == "block":
                self._extract_method_calls(body_child, source, symbol_id, edges)

        return SymbolNode(
            symbol_id=symbol_id,
            file_path=file_path,
            name=name,
            kind=kind,
            package=package_name,
            component_type="Method",
            annotations=annotations,
            signature=sig,
            return_type=return_type,
            parameters=parameters,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

    def _parse_field_declaration(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        package_name: str,
        parent_symbol_id: str,
        edges: List[DependencyEdge],
    ) -> List[SymbolNode]:
        field_type = "Object"
        annotations: List[str] = []
        fields: List[SymbolNode] = []

        for child in node.children:
            if child.type == "modifiers":
                for mod_child in child.children:
                    if mod_child.type in ("annotation", "marker_annotation"):
                        ann_name = self._extract_annotation_name(mod_child, source)
                        if ann_name:
                            annotations.append(ann_name)
            elif child.type in ("type_identifier", "integral_type", "floating_point_type", "boolean_type", "generic_type", "scoped_type_identifier"):
                field_type = source[child.start_byte:child.end_byte].decode("utf-8")
            elif child.type == "variable_declarator":
                for id_child in child.children:
                    if id_child.type == "identifier":
                        var_name = source[id_child.start_byte:id_child.end_byte].decode("utf-8")
                        sym_id = f"{parent_symbol_id}#{var_name}"

                        # If field has @Autowired or is a repository/service injection
                        rel_kind = "injects" if any("Autowired" in a or "Inject" in a for a in annotations) else "references"
                        edges.append(
                            DependencyEdge(
                                source_symbol_id=parent_symbol_id,
                                target_symbol_id=field_type,
                                relation_kind=rel_kind,
                                resolved=False,
                            )
                        )

                        fields.append(
                            SymbolNode(
                                symbol_id=sym_id,
                                file_path=file_path,
                                name=var_name,
                                kind="field",
                                package=package_name,
                                component_type="Field",
                                annotations=annotations,
                                signature=f"{field_type} {var_name}",
                                return_type=field_type,
                                start_line=node.start_point[0] + 1,
                                end_line=node.end_point[0] + 1,
                            )
                        )
        return fields

    def _extract_method_calls(self, node: Node, source: bytes, source_symbol_id: str, edges: List[DependencyEdge]):
        """Recursively find method_invocation expressions in a method block."""
        if node.type == "method_invocation":
            target_method = ""
            receiver = ""
            for child in node.children:
                if child.type == "identifier":
                    target_method = source[child.start_byte:child.end_byte].decode("utf-8")
                elif child.type in ("field_access", "identifier") and not target_method:
                    receiver = source[child.start_byte:child.end_byte].decode("utf-8")

            if target_method:
                target_id = f"{receiver}.{target_method}" if receiver else target_method
                edges.append(
                    DependencyEdge(
                        source_symbol_id=source_symbol_id,
                        target_symbol_id=target_id,
                        relation_kind="calls",
                        resolved=False,
                    )
                )

        for child in node.children:
            self._extract_method_calls(child, source, source_symbol_id, edges)

    def _extract_annotation_name(self, node: Node, source: bytes) -> str:
        for child in node.children:
            if child.type in ("identifier", "scoped_identifier"):
                return source[child.start_byte:child.end_byte].decode("utf-8")
        raw = source[node.start_byte:node.end_byte].decode("utf-8")
        return raw.lstrip("@").split("(")[0].strip()

    def _classify_spring_component(
        self,
        annotations: List[str],
        name: str,
        file_path: str,
        interfaces: List[str],
    ) -> str:
        ann_set = set(annotations)
        posix_path = file_path.replace("\\", "/")
        if "SpringBootTest" in ann_set or "Test" in ann_set or "src/test" in posix_path:
            return "Test"
        if "RestController" in ann_set or "Controller" in ann_set or name.endswith("Controller"):
            return "Controller"
        if "Service" in ann_set or name.endswith("ServiceImpl") or name.endswith("Service"):
            return "Service"
        if "Repository" in ann_set or any("Repository" in iface for iface in interfaces) or name.endswith("Repository"):
            return "Repository"
        if "Entity" in ann_set or "Table" in ann_set:
            return "Entity"
        if "Configuration" in ann_set:
            return "Configuration"
        if "SpringBootApplication" in ann_set:
            return "Application"
        return "Component"
