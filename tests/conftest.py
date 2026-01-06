"""
Pytest configuration and fixtures.
"""

import pytest
from typing import Generator
from fastapi.testclient import TestClient

from app.main import create_app
from config.settings import reset_settings


@pytest.fixture
def test_app():
    """Create a test FastAPI application."""
    # Reset settings to ensure clean state
    reset_settings()

    # Create app without lifespan for testing
    app = create_app()

    return app


@pytest.fixture
def client(test_app) -> Generator:
    """Create a test client."""
    with TestClient(test_app) as test_client:
        yield test_client


@pytest.fixture
def mock_mcp_config(tmp_path):
    """Create a temporary MCP configuration file."""
    config_content = """{
  "mcpServers": {
    "test-server": {
      "command": "python",
      "args": ["-m", "test.server"],
      "env": {},
      "description": "Test server",
      "enabled": true
    }
  }
}"""

    config_file = tmp_path / "mcp_servers.json"
    config_file.write_text(config_content)

    return str(config_file)
