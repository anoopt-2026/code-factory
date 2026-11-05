"""CodeGraph repository intelligence tools exposed to Gemini function calling."""

import logging
from typing import Optional

from ..services.codegraph_service import CodeGraphService

logger = logging.getLogger(__name__)


def search_symbols(query: str, limit: int = 10, issue_key: Optional[str] = None) -> dict:
    """Search for classes, interfaces, methods, or fields matching a keyword query across the codebase.

    Args:
        query: The symbol name, method name, annotation, or signature fragment to search for (e.g. 'Employee', 'create', 'email').
        limit: Maximum number of matching symbols to return (defaults to 10).
        issue_key: Optional Jira issue key for context.
    """
    try:
        service = CodeGraphService.get_instance()
        return service.search_symbols(query=query, limit=limit)
    except Exception as e:
        logger.error("Error in search_symbols tool: %s", e)
        return {"error": str(e), "fallback": "Use list_project_files to inspect directory structure."}


def get_symbol_definition(symbol_name: str, issue_key: Optional[str] = None) -> dict:
    """Retrieve the full declaration, signature, annotations, line range, and source snippet for a specific class, method, or field.

    Args:
        symbol_name: Name of the class, method, or field (e.g. 'EmployeeController', 'Employee', 'create').
        issue_key: Optional Jira issue key for context.
    """
    try:
        service = CodeGraphService.get_instance()
        return service.get_symbol_definition(symbol_name=symbol_name)
    except Exception as e:
        logger.error("Error in get_symbol_definition tool: %s", e)
        return {"error": str(e), "fallback": "Use read_project_file to read the file content directly."}


def find_callers_and_callees(symbol_name: str, issue_key: Optional[str] = None) -> dict:
    """Find callers (who invokes or injects this symbol) and callees (what this symbol invokes or injects).

    Args:
        symbol_name: Name of the class, service, repository, or method (e.g. 'EmployeeService', 'EmployeeRepository').
        issue_key: Optional Jira issue key for context.
    """
    try:
        service = CodeGraphService.get_instance()
        return service.find_callers_and_callees(symbol_name=symbol_name)
    except Exception as e:
        logger.error("Error in find_callers_and_callees tool: %s", e)
        return {"error": str(e), "fallback": "Use read_project_file to inspect callers and dependencies manually."}


def get_dependency_context(symbol_name: str, issue_key: Optional[str] = None) -> dict:
    """Retrieve comprehensive dependency context for a symbol: inbound/outbound relationships, related test classes, and bounded source snippet.

    Args:
        symbol_name: Name of the primary class or method (e.g. 'EmployeeController', 'Employee').
        issue_key: Optional Jira issue key for context.
    """
    try:
        service = CodeGraphService.get_instance()
        return service.get_dependency_context(symbol_name=symbol_name)
    except Exception as e:
        logger.error("Error in get_dependency_context tool: %s", e)
        return {"error": str(e), "fallback": "Use read_project_file to read source code."}


def get_code_graph_summary(issue_key: Optional[str] = None) -> dict:
    """Retrieve an architectural overview of the repository: detected Spring Boot layers (Controllers, Services, Repositories, Entities, Tests) and key metrics.

    Args:
        issue_key: Optional Jira issue key for context.
    """
    try:
        service = CodeGraphService.get_instance()
        return service.get_code_graph_summary()
    except Exception as e:
        logger.error("Error in get_code_graph_summary tool: %s", e)
        return {"error": str(e), "fallback": "Use list_project_files to inspect directory structure."}
