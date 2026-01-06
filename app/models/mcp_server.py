"""
Data models for MCP server configurations.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Literal


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""

    name: str
    """Unique identifier for the MCP server."""

    description: str = ""
    """Human-readable description of the server's purpose."""

    enabled: bool = True
    """Whether the server is enabled and should be started."""

    # Process-based server fields
    command: Optional[str] = None
    """Command to execute for process-based servers (e.g., 'python', 'npx')."""

    args: List[str] = field(default_factory=list)
    """Command-line arguments for the server process."""

    env: Dict[str, str] = field(default_factory=dict)
    """Environment variables for the server process."""

    # HTTP-based server fields
    type: Literal["process", "http"] = "process"
    """Server type: 'process' for subprocess, 'http' for already-running HTTP server."""

    url: Optional[str] = None
    """Base URL for HTTP-based servers (e.g., 'http://localhost:3001/mcp')."""

    headers: Dict[str, str] = field(default_factory=dict)
    """HTTP headers to include in requests to HTTP-based servers."""

    def is_process_based(self) -> bool:
        """Check if this is a process-based server."""
        return self.type == "process" and self.command is not None

    def is_http_based(self) -> bool:
        """Check if this is an HTTP-based server."""
        return self.type == "http" and self.url is not None

    def validate(self) -> None:
        """Validate server configuration."""
        if not self.name:
            raise ValueError("Server name cannot be empty")

        if self.is_process_based():
            if not self.command:
                raise ValueError(f"Process-based server '{self.name}' must have a command")
        elif self.is_http_based():
            if not self.url:
                raise ValueError(f"HTTP-based server '{self.name}' must have a URL")
        else:
            raise ValueError(
                f"Server '{self.name}' must be either process-based (with command) "
                f"or HTTP-based (with type='http' and url)"
            )


@dataclass
class MCPServerStatus:
    """Runtime status of an MCP server."""

    name: str
    """Server name."""

    enabled: bool
    """Whether the server is enabled in configuration."""

    running: bool = False
    """Whether the server is currently running."""

    healthy: bool = False
    """Whether the server responded to health check."""

    error: Optional[str] = None
    """Last error message, if any."""

    type: Literal["process", "http"] = "process"
    """Server type."""


@dataclass
class MCPResponse:
    """Response from an MCP server query."""

    server_name: str
    """Name of the server that provided this response."""

    success: bool
    """Whether the query was successful."""

    data: Optional[Dict] = None
    """Response data from the server."""

    error: Optional[str] = None
    """Error message if the query failed."""

    latency_ms: float = 0.0
    """Query latency in milliseconds."""
