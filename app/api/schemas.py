"""
API 요청 및 응답 검증을 위한 Pydantic 모델.
"""

from datetime import datetime
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """쿼리 엔드포인트를 위한 요청 모델."""

    query: str = Field(..., min_length=1, description="사용자 쿼리 문자열")
    session_id: Optional[str] = Field(None, description="대화 연속성을 위한 선택적 세션 ID")
    model: Optional[str] = Field(None, description="사용할 Ollama 모델 (사용자 프로필 기본값)")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="생성 온도 (사용자 프로필 기본값)")
    max_tokens: Optional[int] = Field(None, gt=0, description="생성할 최대 토큰 수 (사용자 프로필 기본값)")
    mcp_servers: Optional[List[str]] = Field(None, description="컨텍스트를 위해 쿼리할 MCP 서버 (사용자 프로필 기본값)")
    stream: bool = Field(default=False, description="스트리밍 응답 활성화")
    use_conversation_history: bool = Field(default=True, description="컨텍스트에 대화 기록 포함")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "데이터베이스의 상위 10개 제품은 무엇인가요?",
                "model": "llama3.2",
                "temperature": 0.7,
                "max_tokens": 2048,
                "mcp_servers": ["sqlite"],
                "stream": False,
            }
        }


class MCPContextItem(BaseModel):
    """단일 서버에 대한 MCP 컨텍스트."""

    success: bool = Field(..., description="쿼리가 성공했는지 여부")
    data: Optional[Dict[str, Any]] = Field(None, description="서버의 응답 데이터")
    error: Optional[str] = Field(None, description="쿼리 실패 시 오류 메시지")
    latency_ms: float = Field(..., description="쿼리 지연 시간(밀리초)")


class QueryMetadata(BaseModel):
    """쿼리 처리에 대한 메타데이터."""

    processing_time: float = Field(..., description="총 처리 시간(초)")
    mcp_servers_queried: List[str] = Field(default_factory=list, description="쿼리한 MCP 서버 목록")
    mcp_servers_successful: List[str] = Field(default_factory=list, description="성공한 MCP 쿼리 목록")
    success: bool = Field(default=True, description="쿼리가 성공했는지 여부")
    conversation_history_used: bool = Field(default=False, description="대화 기록이 포함되었는지 여부")


class QueryResponse(BaseModel):
    """쿼리 엔드포인트를 위한 응답 모델."""

    response: str = Field(..., description="LLM에서 생성된 응답")
    model: str = Field(..., description="생성에 사용된 모델")
    session_id: Optional[str] = Field(None, description="대화 연속성을 위한 세션 ID")
    mcp_context: Dict[str, MCPContextItem] = Field(default_factory=dict, description="MCP 서버의 컨텍스트")
    metadata: QueryMetadata = Field(..., description="쿼리 처리 메타데이터")
    success: bool = Field(default=True, description="쿼리가 성공했는지 여부")
    error: Optional[str] = Field(None, description="쿼리 실패 시 오류 메시지")

    class Config:
        json_schema_extra = {
            "example": {
                "response": "데이터베이스 쿼리를 기반으로 상위 10개 제품은...",
                "model": "llama3.2",
                "mcp_context": {
                    "sqlite": {
                        "success": True,
                        "data": {"tools": []},
                        "error": None,
                        "latency_ms": 45.2,
                    }
                },
                "metadata": {
                    "processing_time": 2.34,
                    "mcp_servers_queried": ["sqlite"],
                    "mcp_servers_successful": ["sqlite"],
                    "success": True,
                },
                "success": True,
                "error": None,
            }
        }


class HealthResponse(BaseModel):
    """헬스 체크 엔드포인트를 위한 응답 모델."""

    healthy: bool = Field(..., description="전체 상태")
    llm: Dict[str, Any] = Field(..., description="llm 연결 상태")
    mcp_servers: Dict[str, Dict[str, Any]] = Field(..., description="MCP 서버 상태")


class MCPServerInfo(BaseModel):
    """MCP 서버에 대한 정보."""

    name: str = Field(..., description="서버 이름")
    description: str = Field(default="", description="서버 설명")
    type: str = Field(..., description="서버 타입 (process 또는 http)")
    enabled: bool = Field(..., description="서버가 활성화되었는지 여부")
    running: bool = Field(default=False, description="서버가 실행 중인지 여부")
    healthy: bool = Field(default=False, description="서버가 정상인지 여부")
    error: Optional[str] = Field(None, description="마지막 오류 메시지")


class MCPServersListResponse(BaseModel):
    """MCP 서버 목록을 위한 응답 모델."""

    servers: List[MCPServerInfo] = Field(..., description="MCP 서버 목록")
    total: int = Field(..., description="총 서버 수")
    enabled: int = Field(..., description="활성화된 서버 수")
    running: int = Field(..., description="실행 중인 서버 수")


class ErrorResponse(BaseModel):
    """오류 응답 모델."""

    error: str = Field(..., description="오류 메시지")
    detail: Optional[str] = Field(None, description="상세 오류 정보")
    status_code: int = Field(..., description="HTTP 상태 코드")

    class Config:
        json_schema_extra = {
            "example": {
                "error": "잘못된 요청",
                "detail": "쿼리 문자열은 비어 있을 수 없습니다",
                "status_code": 400,
            }
        }


class OllamaModel(BaseModel):
    """Ollama 모델 정보."""

    name: str = Field(..., description="모델 이름")
    size: Optional[int] = Field(None, description="모델 크기(바이트)")
    modified_at: Optional[str] = Field(None, description="마지막 수정 타임스탬프")


class ModelsListResponse(BaseModel):
    """사용 가능한 Ollama 모델 목록을 위한 응답 모델."""

    models: List[OllamaModel] = Field(..., description="사용 가능한 모델 목록")
    total: int = Field(..., description="총 모델 수")


# 세션 및 인증 스키마

class UserProfileResponse(BaseModel):
    """사용자 프로필 응답."""

    user_id: str = Field(..., description="사용자 ID")
    default_model: str = Field(..., description="기본 Ollama 모델")
    default_temperature: float = Field(..., description="기본 온도")
    default_max_tokens: int = Field(..., description="기본 최대 토큰 수")
    preferred_mcp_servers: List[str] = Field(default_factory=list, description="선호하는 MCP 서버")
    created_at: Optional[datetime] = Field(None, description="프로필 생성 시간")
    updated_at: Optional[datetime] = Field(None, description="마지막 업데이트 시간")


class UpdateProfileRequest(BaseModel):
    """사용자 프로필 업데이트 요청."""

    default_model: Optional[str] = Field(None, description="기본 Ollama 모델")
    default_temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="기본 온도")
    default_max_tokens: Optional[int] = Field(None, gt=0, description="기본 최대 토큰 수")
    preferred_mcp_servers: Optional[List[str]] = Field(None, description="선호하는 MCP 서버")


class ConversationMessageResponse(BaseModel):
    """단일 대화 메시지."""

    role: str = Field(..., description="메시지 역할 (user 또는 assistant)")
    content: str = Field(..., description="메시지 내용")
    timestamp: datetime = Field(..., description="메시지 타임스탬프")
    mcp_context: Optional[Dict[str, Any]] = Field(None, description="이 메시지의 MCP 컨텍스트")


class SessionResponse(BaseModel):
    """대화 세션 응답."""

    session_id: str = Field(..., description="세션 ID")
    user_id: str = Field(..., description="사용자 ID")
    messages: List[ConversationMessageResponse] = Field(default_factory=list, description="대화 메시지")
    created_at: datetime = Field(..., description="세션 생성 시간")
    updated_at: datetime = Field(..., description="마지막 업데이트 시간")
    message_count: int = Field(..., description="총 메시지 수")


class SessionListResponse(BaseModel):
    """대화 세션 목록."""

    sessions: List[SessionResponse] = Field(..., description="세션 목록")
    total: int = Field(..., description="총 세션 수")


class CreateAPIKeyRequest(BaseModel):
    """새 API 키 생성 요청."""

    name: str = Field(..., min_length=1, description="API 키의 친근한 이름")
    rate_limit: Optional[int] = Field(None, gt=0, description="선택적 속도 제한 (시간당 요청 수)")


class APIKeyResponse(BaseModel):
    """API 키 응답."""

    key: str = Field(..., description="API 키 (한 번만 표시)")
    user_id: str = Field(..., description="연결된 사용자 ID")
    name: str = Field(..., description="API 키 이름")
    created_at: datetime = Field(..., description="생성 시간")
    rate_limit: Optional[int] = Field(None, description="설정된 경우 속도 제한")
