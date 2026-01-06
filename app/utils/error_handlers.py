"""
커스텀 예외 핸들러 및 오류 클래스.
"""

from typing import Optional


class MCPServerError(Exception):
    """MCP 서버 오류에 대해 발생하는 예외."""

    def __init__(self, server_name: str, message: str):
        self.server_name = server_name
        self.message = message
        super().__init__(f"MCP 서버 '{server_name}': {message}")


class OllamaConnectionError(Exception):
    """Ollama에 연결할 수 없을 때 발생하는 예외."""

    def __init__(self, base_url: str, message: str):
        self.base_url = base_url
        self.message = message
        super().__init__(f"{base_url}에서 Ollama 연결 실패: {message}")


class ConfigurationError(Exception):
    """설정 오류에 대해 발생하는 예외."""

    def __init__(self, message: str, config_file: Optional[str] = None):
        self.config_file = config_file
        self.message = message
        if config_file:
            super().__init__(f"{config_file}의 설정 오류: {message}")
        else:
            super().__init__(f"설정 오류: {message}")


class QueryProcessingError(Exception):
    """쿼리 처리 중 발생하는 예외."""

    def __init__(self, message: str, query: Optional[str] = None):
        self.query = query
        self.message = message
        if query:
            super().__init__(f"'{query[:50]}...'에 대한 쿼리 처리 오류: {message}")
        else:
            super().__init__(f"쿼리 처리 오류: {message}")
