"""
인증 및 세션 데이터 모델.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any


@dataclass
class UserProfile:
    """사용자 프로필 및 선호 설정."""

    user_id: str
    """고유한 사용자 식별자 (API 키 해시 또는 사용자 ID)."""

    default_model: str = ""
    """이 사용자의 기본 Ollama 모델."""

    default_temperature: float = 0.7
    """기본 생성 온도."""

    default_max_tokens: int = 2048
    """기본 최대 토큰 수."""

    preferred_mcp_servers: List[str] = field(default_factory=list)
    """선호하는 MCP 서버 목록."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """추가 사용자 메타데이터."""

    created_at: Optional[datetime] = None
    """프로필 생성 타임스탬프."""

    updated_at: Optional[datetime] = None
    """프로필 마지막 업데이트 타임스탬프."""


@dataclass
class ConversationMessage:
    """대화의 단일 메시지."""

    role: str
    """메시지 역할: 'user' 또는 'assistant'."""

    content: str
    """메시지 내용."""

    timestamp: datetime
    """메시지 타임스탬프."""

    mcp_context: Optional[Dict[str, Any]] = None
    """이 메시지에 사용된 MCP 컨텍스트 (어시스턴트 메시지용)."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """추가 메시지 메타데이터."""


@dataclass
class ConversationSession:
    """전체 대화 세션."""

    session_id: str
    """고유한 세션 식별자."""

    user_id: str
    """사용자 식별자."""

    messages: List[ConversationMessage] = field(default_factory=list)
    """이 대화의 메시지 목록."""

    created_at: datetime = field(default_factory=datetime.now)
    """세션 생성 타임스탬프."""

    updated_at: datetime = field(default_factory=datetime.now)
    """세션 마지막 업데이트 타임스탬프."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """추가 세션 메타데이터."""

    def add_message(self, role: str, content: str, mcp_context: Optional[Dict] = None) -> ConversationMessage:
        """대화에 새 메시지를 추가합니다."""
        message = ConversationMessage(
            role=role,
            content=content,
            timestamp=datetime.now(),
            mcp_context=mcp_context,
        )
        self.messages.append(message)
        self.updated_at = datetime.now()
        return message

    def get_conversation_history(self, limit: Optional[int] = None) -> List[Dict[str, str]]:
        """
        LangChain 형식의 대화 기록을 가져옵니다.

        Args:
            limit: 최근 메시지 수에 대한 선택적 제한.

        Returns:
            {role, content} 형식의 메시지 목록.
        """
        messages = self.messages[-limit:] if limit else self.messages
        return [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]


@dataclass
class APIKey:
    """API 키 정보."""

    key_hash: str
    """해시된 API 키."""

    user_id: str
    """연결된 사용자 ID."""

    name: str
    """이 API 키의 친근한 이름."""

    created_at: datetime
    """키 생성 타임스탬프."""

    last_used: Optional[datetime] = None
    """이 키를 마지막으로 사용한 시간."""

    is_active: bool = True
    """키가 활성 상태인지 여부."""

    rate_limit: Optional[int] = None
    """선택적 속도 제한 (시간당 요청 수)."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """추가 키 메타데이터."""
