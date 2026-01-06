"""
Custom exception handlers and error classes.
"""

from typing import Optional


class MCPServerError(Exception):
    """Exception raised for MCP server errors."""

    def __init__(self, server_name: str, message: str):
        self.server_name = server_name
        self.message = message
        super().__init__(f"MCP server '{server_name}': {message}")


class OllamaConnectionError(Exception):
    """Exception raised when unable to connect to Ollama."""

    def __init__(self, base_url: str, message: str):
        self.base_url = base_url
        self.message = message
        super().__init__(f"Failed to connect to Ollama at {base_url}: {message}")


class ConfigurationError(Exception):
    """Exception raised for configuration errors."""

    def __init__(self, message: str, config_file: Optional[str] = None):
        self.config_file = config_file
        self.message = message
        if config_file:
            super().__init__(f"Configuration error in {config_file}: {message}")
        else:
            super().__init__(f"Configuration error: {message}")


class QueryProcessingError(Exception):
    """Exception raised during query processing."""

    def __init__(self, message: str, query: Optional[str] = None):
        self.query = query
        self.message = message
        if query:
            super().__init__(f"Query processing error for '{query[:50]}...': {message}")
        else:
            super().__init__(f"Query processing error: {message}")
