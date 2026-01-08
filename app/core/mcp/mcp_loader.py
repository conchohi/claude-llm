"""
MCP 서버 설정 로더.
JSON 파일에서 MCP 서버 설정을 로드하고 파싱합니다.
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

from app.models.mcp_server import MCPServerConfig


class MCPConfigLoader:
    """JSON에서 MCP 서버 설정을 로드하고 검증합니다."""

    def __init__(self, config_path: str, dotenv_path: str | None = None):
        """
        설정 로더를 초기화합니다.

        Args:
            config_path: MCP 서버 JSON 설정 파일 경로.
            dotenv_path: .env 파일 경로. None인 경우 자동으로 찾습니다.
        """
        self.config_path = Path(config_path)
        self._config_data: Dict = {}
        self._servers: Dict[str, MCPServerConfig] = {}

        # .env 파일 로드 (환경 변수 치환을 위해)
        load_dotenv(dotenv_path=dotenv_path, override=False)

    def load_config(self) -> None:
        """
        JSON 파일에서 설정을 로드합니다.

        Raises:
            FileNotFoundError: 설정 파일이 존재하지 않는 경우.
            json.JSONDecodeError: 설정 파일이 유효한 JSON이 아닌 경우.
        """
        if not self.config_path.exists():
            raise FileNotFoundError(f"MCP 설정 파일을 찾을 수 없습니다: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            self._config_data = json.load(f)

        self._parse_servers()

    def _parse_servers(self) -> None:
        """로드된 JSON 데이터에서 서버 설정을 파싱합니다."""
        mcp_servers = self._config_data.get("mcpServers", {})

        for name, config in mcp_servers.items():
            server_config = self._parse_server_config(name, config)
            self._servers[name] = server_config

    def _parse_server_config(self, name: str, config: Dict) -> MCPServerConfig:
        """
        단일 서버 설정을 파싱합니다.

        Args:
            name: 서버 이름.
            config: 서버 설정 딕셔너리.

        Returns:
            MCPServerConfig 인스턴스.
        """
        # 서버 타입 결정
        server_type = config.get("type", "process")

        # 공통 필드
        description = config.get("description", "")
        enabled = config.get("enabled", True)

        if server_type == "http":
            # HTTP 기반 서버
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
            # 프로세스 기반 서버
            command = config.get("command", "")
            args = config.get("args", [])
            env = {
                k: self._substitute_env_vars(v)
                for k, v in config.get("env", {}).items()
            }

            # args의 환경 변수 치환
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
        ${VAR_NAME} 형식의 환경 변수를 치환합니다.

        Args:
            value: ${VAR_NAME} 플레이스홀더를 포함할 수 있는 문자열.

        Returns:
            환경 변수가 치환된 문자열.
        """
        if not isinstance(value, str):
            return value

        # 모든 ${VAR_NAME} 패턴 찾기
        pattern = r'\$\{([^}]+)\}'

        def replace_var(match):
            var_name = match.group(1)
            return os.getenv(var_name, match.group(0))  # 찾지 못한 경우 원본 유지

        return re.sub(pattern, replace_var, value)

    def get_all_servers(self) -> Dict[str, MCPServerConfig]:
        """
        모든 서버 설정을 가져옵니다.

        Returns:
            서버 이름을 설정에 매핑하는 딕셔너리.
        """
        return self._servers.copy()

    def get_enabled_servers(self) -> List[MCPServerConfig]:
        """
        활성화된 서버 설정만 가져옵니다.

        Returns:
            활성화된 MCPServerConfig 인스턴스 목록.
        """
        return [
            server for server in self._servers.values()
            if server.enabled
        ]

    def get_server(self, name: str) -> MCPServerConfig | None:
        """
        이름으로 특정 서버 설정을 가져옵니다.

        Args:
            name: 서버 이름.

        Returns:
            MCPServerConfig 인스턴스 또는 찾지 못한 경우 None.
        """
        return self._servers.get(name)

    def validate_all(self) -> List[str]:
        """
        모든 서버 설정을 검증합니다.

        Returns:
            검증 오류 메시지 목록 (모두 유효한 경우 빈 리스트).
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
    MCP 설정을 로드하는 편의 함수입니다.

    Args:
        config_path: MCP 서버 JSON 파일 경로.

    Returns:
        로드된 MCPConfigLoader 인스턴스.

    Raises:
        FileNotFoundError: 설정 파일이 존재하지 않는 경우.
        json.JSONDecodeError: 설정 파일이 유효한 JSON이 아닌 경우.
        ValueError: 서버 설정이 유효하지 않은 경우.
    """
    loader = MCPConfigLoader(config_path)
    loader.load_config()

    # 모든 설정 검증
    errors = loader.validate_all()
    if errors:
        raise ValueError(f"유효하지 않은 MCP 서버 설정:\n" + "\n".join(errors))

    return loader
