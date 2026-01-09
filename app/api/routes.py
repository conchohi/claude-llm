"""
LangChain + Ollama + MCP 서버를 위한 API 라우트 정의.
"""

from typing import Dict, Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.schemas import (
    QueryRequest,
    QueryResponse,
    HealthResponse,
    MCPServersListResponse,
    MCPServerInfo,
    ErrorResponse,
    SessionResponse,
    SessionListResponse,
    ConversationMessageResponse,
    CreateAPIKeyRequest,
    APIKeyResponse,
)
from app.api.middleware import get_current_user
from app.core.query_processor import QueryProcessor
from app.core.session_manager import SessionManager


router = APIRouter()


# 전역 의존성 (main.py에서 설정됨)
_query_processor: QueryProcessor | None = None
_session_manager: SessionManager | None = None


def set_query_processor(processor: QueryProcessor):
    """전역 쿼리 프로세서 인스턴스를 설정합니다."""
    global _query_processor
    _query_processor = processor


def set_session_manager(manager: Optional[SessionManager]):
    """전역 세션 매니저 인스턴스를 설정합니다."""
    global _session_manager
    _session_manager = manager


def get_query_processor() -> QueryProcessor:
    """쿼리 프로세서를 가져오는 의존성."""
    if _query_processor is None:
        raise HTTPException(status_code=500, detail="Query processor not initialized")
    return _query_processor


def get_session_manager() -> SessionManager:
    """세션 매니저를 가져오는 의존성."""
    if _session_manager is None:
        raise HTTPException(status_code=500, detail="Session manager not initialized")
    return _session_manager


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check(
    processor: QueryProcessor = Depends(get_query_processor),
):
    """
    헬스 체크 엔드포인트.

    다음의 상태를 확인합니다:
    - Ollama 연결
    - MCP 서버

    전체 헬스 상태와 세부 정보를 반환합니다.
    """
    try:
        health_status = await processor.health_check()
        return HealthResponse(**health_status)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")


@router.post("/api/v1/query", response_model=QueryResponse, tags=["Query"])
async def query(
    request: QueryRequest,
    http_request: Request,
    processor: QueryProcessor = Depends(get_query_processor),
):
    """
    사용자 쿼리를 처리하고 AI가 생성한 응답을 반환합니다.

    이 엔드포인트는:
    1. 지정된 MCP 서버(또는 지정되지 않은 경우 모든 활성화된 서버)에서 컨텍스트 수집
    2. LangChain과 Ollama LLM을 사용하여 응답 생성
    3. MCP 컨텍스트 및 메타데이터와 함께 응답 반환
    4. 대화 기록을 세션에 저장 (인증된 경우)

    **요청 본문:**
    - `query`: 사용자 질문/쿼리 (필수)
    - `session_id`: 대화를 계속하기 위한 선택적 세션 ID
    - `use_conversation_history`: 컨텍스트에 대화 기록 포함 (기본값: true)
    - `stream`: 스트리밍 활성화 (이 엔드포인트에서는 false여야 함)

    **응답:**
    - `response`: 생성된 AI 응답
    - `model`: 사용된 모델
    - `session_id`: 세션 ID (대화 계속용)
    - `mcp_context`: MCP 서버에서 수집된 컨텍스트
    - `metadata`: 처리 메타데이터 (시간, 쿼리된 서버 등)
    """
    if request.stream:
        raise HTTPException(
            status_code=400,
            detail="Streaming not supported on this endpoint. Use /api/v1/query/stream instead."
        )

    # 요청 상태에서 user_id 가져오기 (인증 미들웨어에서 설정됨)
    user_id = getattr(http_request.state, "user_id", None)

    try:
        result = await processor.process_query(
            query=request.query,
            user_id=user_id,
            session_id=request.session_id,
            use_conversation_history=request.use_conversation_history,
        )

        return QueryResponse(**result)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query processing failed: {str(e)}")


@router.post("/api/v1/query/stream", tags=["Query"])
async def query_stream(
    request: QueryRequest,
    http_request: Request,
    processor: QueryProcessor = Depends(get_query_processor),
):
    """
    사용자 쿼리를 처리하고 스트리밍 AI 생성 응답을 반환합니다.

    이 엔드포인트는 스트리밍 응답을 위한 Server-Sent Events (SSE)를 반환합니다.
    대화 기록 및 세션 관리를 지원합니다.

    **요청 본문:**
    `/api/v1/query` 엔드포인트와 동일합니다.

    **응답:**
    응답 토큰의 Server-Sent Events 스트림.
    """
    # 요청 상태에서 user_id 가져오기 (인증 미들웨어에서 설정됨)
    user_id = getattr(http_request.state, "user_id", None)

    async def generate():
        try:
            async for chunk in processor.process_streaming_query(
                query=request.query,
                user_id=user_id,
                session_id=request.session_id,
                use_conversation_history=request.use_conversation_history,
            ):
                yield f"data: {chunk}<br>"
        except Exception as e:
            yield f"data: Error: {str(e)}<br>"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/api/v1/mcp/servers", response_model=MCPServersListResponse, tags=["MCP"])
async def list_mcp_servers(
    processor: QueryProcessor = Depends(get_query_processor),
):
    """
    설정된 모든 MCP 서버와 그 상태를 나열합니다.

    다음 정보를 반환합니다:
    - 서버 이름, 설명, 유형
    - 활성화 여부, 실행 중 여부, 정상 여부
    - 오류 메시지
    """
    try:
        statuses = processor.mcp_client.get_all_statuses()
        configs = processor.mcp_client._server_configs

        servers = []
        for name, status in statuses.items():
            config = configs.get(name)
            servers.append(MCPServerInfo(
                name=name,
                description=config.description if config else "",
                type=status.type,
                enabled=status.enabled,
                running=status.running,
                healthy=status.healthy,
                error=status.error,
            ))

        return MCPServersListResponse(
            servers=servers,
            total=len(servers),
            enabled=sum(1 for s in servers if s.enabled),
            running=sum(1 for s in servers if s.running),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list MCP servers: {str(e)}")


@router.post("/api/v1/mcp/servers/{name}/test", tags=["MCP"])
async def test_mcp_server(
    name: str,
    processor: QueryProcessor = Depends(get_query_processor),
):
    """
    특정 MCP 서버에 대한 연결을 테스트합니다.

    **경로 매개변수:**
    - `name`: MCP 서버 이름

    **응답:**
    서버의 정상 여부 및 오류 정보를 반환합니다.
    """
    try:
        is_healthy = await processor.mcp_client.health_check(name)
        status = processor.mcp_client.get_server_status(name)

        if status is None:
            raise HTTPException(status_code=404, detail=f"Server '{name}' not found")

        return {
            "name": name,
            "healthy": is_healthy,
            "running": status.running,
            "enabled": status.enabled,
            "type": status.type,
            "error": status.error,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server test failed: {str(e)}")


@router.get("/api/v1/models", tags=["Models"])
async def list_models(
    processor: QueryProcessor = Depends(get_query_processor),
):
    """
    사용 가능한 LLM 모델을 나열합니다.

    LLM 서버에서 사용 가능한 모델 목록을 반환합니다.

    참고: 이것은 플레이스홀더입니다. 전체 구현은 LLM API를 쿼리해야 합니다.
    """
    # 간소화된 버전
    # 전체 구현은 Ollama의 /api/tags 엔드포인트 또는 OpenAI 모델 목록을 쿼리해야 함
    return {
        "models": [
            {"name": processor.llm_service.model},
        ],
        "total": 1,
        "note": "Currently returns configured model. Full model list requires LLM API query."
    }

@router.get("/api/v1/sessions", response_model=SessionListResponse, tags=["Sessions"])
async def list_sessions(
    limit: int = 20,
    user_id: str = Depends(get_current_user),
    session_manager: SessionManager = Depends(get_session_manager),
):
    """
    현재 사용자의 대화 세션을 나열합니다.

    **쿼리 매개변수:**
    - `limit`: 반환할 최대 세션 수 (기본값: 20)
    """
    try:
        sessions = await session_manager.get_user_sessions(user_id, limit=limit)

        session_responses = [
            SessionResponse(
                session_id=s.session_id,
                user_id=s.user_id,
                messages=[
                    ConversationMessageResponse(
                        role=msg.role,
                        content=msg.content,
                        timestamp=msg.timestamp,
                        mcp_context=msg.mcp_context,
                    )
                    for msg in s.messages
                ],
                created_at=s.created_at,
                updated_at=s.updated_at,
                message_count=len(s.messages),
            )
            for s in sessions
        ]

        return SessionListResponse(
            sessions=session_responses,
            total=len(session_responses),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list sessions: {str(e)}")

@router.post("/api/v1/session", response_model=SessionResponse, tags=["Sessions"])
async def create_session(
    user_id: str = Depends(get_current_user),
    session_manager: SessionManager = Depends(get_session_manager),
):
    """
    현재 사용자의 대화 세션을 생성합니다.
    """
    try:
        session = await session_manager.create_session(user_id)

        return SessionResponse(
            session_id=session.session_id,
            user_id=session.user_id,
            messages=[],
            created_at=session.created_at,
            updated_at=session.updated_at,
            message_count=len(session.messages),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create session: {str(e)}")          

@router.get("/api/v1/messages/{session_id}", response_model=SessionResponse, tags=["Sessions"])
async def get_messages(
    session_id: str,
    user_id: str = Depends(get_current_user),
    session_manager: SessionManager = Depends(get_session_manager),
):
    """
    특정 대화 세션을 가져옵니다.

    **경로 매개변수:**
    - `session_id`: 세션 ID
    """
    try:
        session = await session_manager.get_session_info(session_id)

        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        # 세션이 사용자에게 속하는지 확인
        if session.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        return SessionResponse(
            session_id=session.session_id,
            user_id=session.user_id,
            messages=[
                ConversationMessageResponse(
                    role=msg.role,
                    content=msg.content,
                    timestamp=msg.timestamp,
                    mcp_context=msg.mcp_context,
                    process_time_ms=msg.process_time_ms,
                )
                for msg in session.messages
            ],
            created_at=session.created_at,
            updated_at=session.updated_at,
            message_count=len(session.messages),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get session: {str(e)}")


@router.delete("/api/v1/sessions/{session_id}", tags=["Sessions"])
async def delete_session(
    session_id: str,
    user_id: str = Depends(get_current_user),
    session_manager: SessionManager = Depends(get_session_manager),
):
    """
    대화 세션을 삭제합니다.

    **경로 매개변수:**
    - `session_id`: 세션 ID
    """
    try:
        session = await session_manager.get_session_info(session_id)

        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        # 세션이 사용자에게 속하는지 확인
        if session.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        await session_manager.delete_session(session_id)

        return {"message": "Session deleted successfully", "session_id": session_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete session: {str(e)}")


@router.post("/api/v1/auth/api-keys", response_model=APIKeyResponse, tags=["Authentication"])
async def create_api_key(
    request: CreateAPIKeyRequest,
    user_id: str = Depends(get_current_user),
    session_manager: SessionManager = Depends(get_session_manager),
):
    """
    현재 사용자를 위한 새 API 키를 생성합니다.

    **요청 본문:**
    - `name`: API 키의 친숙한 이름
    - `rate_limit`: 선택적 속도 제한 (시간당 요청 수)

    **⚠️ 중요:** API 키는 한 번만 표시됩니다. 안전하게 저장하세요!
    """
    try:
        plain_key, api_key = await session_manager.create_api_key(
            user_id=user_id,
            name=request.name,
            rate_limit=request.rate_limit,
        )

        return APIKeyResponse(
            key=plain_key,
            user_id=api_key.user_id,
            name=api_key.name,
            created_at=api_key.created_at,
            rate_limit=api_key.rate_limit,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create API key: {str(e)}")
