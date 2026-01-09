"""
인증 및 세션 데이터 모델.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any

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
    
    process_time_ms: Optional[int] = None
    """메시지 처리에 소요된 시간 (밀리초)."""


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

    def add_message(self, role: str, content: str) -> ConversationMessage:
        """대화에 새 메시지를 추가합니다."""
        message = ConversationMessage(
            role=role,
            content=content,
            timestamp=datetime.now()
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
