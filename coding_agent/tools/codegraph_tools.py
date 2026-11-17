"""CodeGraph repository intelligence tools exposed to Gemini function calling."""

import logging

from ..services.codegraph_service import CodeGraphService

logger = logging.getLogger(__name__)


def search_symbols(query: str, limit: int = 10) -> dict:
    """Search classes, interfaces, methods, and fields in the repository."""
    try:
        return CodeGraphService.get_instance().search_symbols(
            query=query,
            limit=limit,
        )
    except Exception as e:
        logger.exception("CodeGraph search_symbols tool failed")
        return {"error": str(e), "fallback": "Use list_project_files and read_project_file."}


def get_symbol_definition(symbol_name: str) -> dict:
    """Retrieve the definition and source snippet of a symbol."""
    try:
        return CodeGraphService.get_instance().get_symbol_definition(
            symbol_name=symbol_name,
        )
    except Exception as e:
        logger.exception("CodeGraph get_symbol_definition tool failed")
        return {"error": str(e), "fallback": "Use read_project_file."}


def find_callers_and_callees(symbol_name: str) -> dict:
    """Find callers and callees of a symbol."""
    try:
        return CodeGraphService.get_instance().find_callers_and_callees(
            symbol_name=symbol_name,
        )
    except Exception as e:
        logger.exception("CodeGraph find_callers_and_callees tool failed")
        return {"error": str(e), "fallback": "Use read_project_file."}


def get_dependency_context(symbol_name: str) -> dict:
    """Retrieve dependencies, related tests, and source context for a symbol."""
    try:
        return CodeGraphService.get_instance().get_dependency_context(
            symbol_name=symbol_name,
        )
    except Exception as e:
        logger.exception("CodeGraph get_dependency_context tool failed")
        return {"error": str(e), "fallback": "Use read_project_file."}


def get_code_graph_summary() -> dict:
    """Retrieve the repository's architectural summary and graph metrics."""
    try:
        return CodeGraphService.get_instance().get_code_graph_summary()
    except Exception as e:
        logger.exception("CodeGraph get_code_graph_summary tool failed")
        return {"error": str(e), "fallback": "Use list_project_files."}