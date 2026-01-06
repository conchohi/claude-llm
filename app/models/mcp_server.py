"""
MCP 서버 설정을 위한 데이터 모델.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Literal


@dataclass
class MCPServerConfig:
    """단일 MCP 서버를 위한 설정."""

    name: str
    """MCP 서버의 고유 식별자."""

    description: str = ""
    """서버 목적에 대한 사람이 읽을 수 있는 설명."""

    enabled: bool = True
    """서버가 활성화되어 시작되어야 하는지 여부."""

    # 프로세스 기반 서버 필드
    command: Optional[str] = None
    """프로세스 기반 서버를 위해 실행할 명령 (예: 'python', 'npx')."""

    args: List[str] = field(default_factory=list)
    """서버 프로세스를 위한 명령줄 인수."""

    env: Dict[str, str] = field(default_factory=dict)
    """서버 프로세스를 위한 환경 변수."""

    # HTTP 기반 서버 필드
    type: Literal["process", "http"] = "process"
    """서버 타입: 서브프로세스의 경우 'process', 이미 실행 중인 HTTP 서버의 경우 'http'."""

    url: Optional[str] = None
    """HTTP 기반 서버를 위한 기본 URL (예: 'http://localhost:3001/mcp')."""

    headers: Dict[str, str] = field(default_factory=dict)
    """HTTP 기반 서버에 대한 요청에 포함할 HTTP 헤더."""

    def is_process_based(self) -> bool:
        """프로세스 기반 서버인지 확인합니다."""
        return self.type == "process" and self.command is not None

    def is_http_based(self) -> bool:
        """HTTP 기반 서버인지 확인합니다."""
        return self.type == "http" and self.url is not None

    def validate(self) -> None:
        """서버 설정을 검증합니다."""
        if not self.name:
            raise ValueError("서버 이름은 비어 있을 수 없습니다")

        if self.is_process_based():
            if not self.command:
                raise ValueError(f"프로세스 기반 서버 '{self.name}'은(는) 명령이 있어야 합니다")
        elif self.is_http_based():
            if not self.url:
                raise ValueError(f"HTTP 기반 서버 '{self.name}'은(는) URL이 있어야 합니다")
        else:
            raise ValueError(
                f"서버 '{self.name}'은(는) 프로세스 기반 (명령 포함) 또는 "
                f"HTTP 기반 (type='http' 및 url 포함)이어야 합니다"
            )


@dataclass
class MCPServerStatus:
    """MCP 서버의 런타임 상태."""

    name: str
    """서버 이름."""

    enabled: bool
    """서버가 설정에서 활성화되었는지 여부."""

    running: bool = False
    """서버가 현재 실행 중인지 여부."""

    healthy: bool = False
    """서버가 상태 확인에 응답했는지 여부."""

    error: Optional[str] = None
    """마지막 오류 메시지 (있는 경우)."""

    type: Literal["process", "http"] = "process"
    """서버 타입."""


@dataclass
class MCPResponse:
    """MCP 서버 쿼리의 응답."""

    server_name: str
    """이 응답을 제공한 서버의 이름."""

    success: bool
    """쿼리가 성공했는지 여부."""

    data: Optional[Dict] = None
    """서버의 응답 데이터."""

    error: Optional[str] = None
    """쿼리 실패 시 오류 메시지."""

    latency_ms: float = 0.0
    """쿼리 지연 시간(밀리초)."""
