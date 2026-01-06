"""
MCP server configuration loader.
Loads and parses MCP server configurations from JSON file.
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, List

from app.models.mcp_server import MCPServerConfig


class MCPConfigLoader:
    """Loads and validates MCP server configurations from JSON."""

    def __init__(self, config_path: str):
        """
        Initialize the config loader.

        Args:
            config_path: Path to the MCP servers JSON configuration file.
        """
        self.config_path = Path(config_path)
        self._config_data: Dict = {}
        self._servers: Dict[str, MCPServerConfig] = {}

    def load_config(self) -> None:
        """
        Load configuration from JSON file.

        Raises:
            FileNotFoundError: If config file doesn't exist.
            json.JSONDecodeError: If config file is not valid JSON.
        """
        if not self.config_path.exists():
            raise FileNotFoundError(f"MCP config file not found: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            self._config_data = json.load(f)

        self._parse_servers()

    def _parse_servers(self) -> None:
        """Parse server configurations from loaded JSON data."""
        mcp_servers = self._config_data.get("mcpServers", {})

        for name, config in mcp_servers.items():
            server_config = self._parse_server_config(name, config)
            self._servers[name] = server_config

    def _parse_server_config(self, name: str, config: Dict) -> MCPServerConfig:
        """
        Parse a single server configuration.

        Args:
            name: Server name.
            config: Server configuration dictionary.

        Returns:
            MCPServerConfig instance.
        """
        # Determine server type
        server_type = config.get("type", "process")

        # Common fields
        description = config.get("description", "")
        enabled = config.get("enabled", True)

        if server_type == "http":
            # HTTP-based server
            url = self._substitute_env_vars(config.get("url", ""))
            headers = {
                k: self._substitute_env_vars(v)
                for k, v in config.get("headers", {}).items()
            }

            return MCPServerConfig(
                name=name,
                description=description,
                enabled=enabled,
                type="http",
                url=url,
                headers=headers,
            )
        else:
            # Process-based server
            command = config.get("command", "")
            args = config.get("args", [])
            env = {
                k: self._substitute_env_vars(v)
                for k, v in config.get("env", {}).items()
            }

            # Substitute environment variables in args
            args = [self._substitute_env_vars(arg) for arg in args]

            return MCPServerConfig(
                name=name,
                description=description,
                enabled=enabled,
                type="process",
                command=command,
                args=args,
                env=env,
            )

    def _substitute_env_vars(self, value: str) -> str:
        """
        Substitute environment variables in the format ${VAR_NAME}.

        Args:
            value: String that may contain ${VAR_NAME} placeholders.

        Returns:
            String with environment variables substituted.
        """
        if not isinstance(value, str):
            return value

        # Find all ${VAR_NAME} patterns
        pattern = r'\$\{([^}]+)\}'

        def replace_var(match):
            var_name = match.group(1)
            return os.getenv(var_name, match.group(0))  # Keep original if not found

        return re.sub(pattern, replace_var, value)

    def get_all_servers(self) -> Dict[str, MCPServerConfig]:
        """
        Get all server configurations.

        Returns:
            Dictionary mapping server names to configurations.
        """
        return self._servers.copy()

    def get_enabled_servers(self) -> List[MCPServerConfig]:
        """
        Get only enabled server configurations.

        Returns:
            List of enabled MCPServerConfig instances.
        """
        return [
            server for server in self._servers.values()
            if server.enabled
        ]

    def get_server(self, name: str) -> MCPServerConfig | None:
        """
        Get a specific server configuration by name.

        Args:
            name: Server name.

        Returns:
            MCPServerConfig instance or None if not found.
        """
        return self._servers.get(name)

    def validate_all(self) -> List[str]:
        """
        Validate all server configurations.

        Returns:
            List of validation error messages (empty if all valid).
        """
        errors = []

        for server in self._servers.values():
            try:
                server.validate()
            except ValueError as e:
                errors.append(str(e))

        return errors


def load_mcp_config(config_path: str) -> MCPConfigLoader:
    """
    Convenience function to load MCP configuration.

    Args:
        config_path: Path to MCP servers JSON file.

    Returns:
        Loaded MCPConfigLoader instance.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        json.JSONDecodeError: If config file is not valid JSON.
        ValueError: If any server configuration is invalid.
    """
    loader = MCPConfigLoader(config_path)
    loader.load_config()

    # Validate all configurations
    errors = loader.validate_all()
    if errors:
        raise ValueError(f"Invalid MCP server configurations:\n" + "\n".join(errors))

    return loader
