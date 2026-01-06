"""
API route definitions for the LangChain + Ollama + MCP server.
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
    UserProfileResponse,
    UpdateProfileRequest,
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


# Global dependencies (will be set in main.py)
_query_processor: QueryProcessor | None = None
_session_manager: SessionManager | None = None


def set_query_processor(processor: QueryProcessor):
    """Set the global query processor instance."""
    global _query_processor
    _query_processor = processor


def set_session_manager(manager: Optional[SessionManager]):
    """Set the global session manager instance."""
    global _session_manager
    _session_manager = manager


def get_query_processor() -> QueryProcessor:
    """Dependency to get query processor."""
    if _query_processor is None:
        raise HTTPException(status_code=500, detail="Query processor not initialized")
    return _query_processor


def get_session_manager() -> SessionManager:
    """Dependency to get session manager."""
    if _session_manager is None:
        raise HTTPException(status_code=500, detail="Session manager not initialized")
    return _session_manager


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check(
    processor: QueryProcessor = Depends(get_query_processor),
):
    """
    Health check endpoint.

    Checks the status of:
    - Ollama connection
    - MCP servers

    Returns overall health status and details.
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
    Process a user query and return AI-generated response.

    This endpoint:
    1. Gathers context from specified MCP servers (or all enabled servers if none specified)
    2. Generates a response using the Ollama LLM with LangChain
    3. Returns the response along with MCP context and metadata
    4. Saves conversation history to session (if authenticated)

    **Request Body:**
    - `query`: User question/query (required)
    - `session_id`: Optional session ID to continue conversation
    - `use_conversation_history`: Include conversation history in context (default: true)
    - `model`: Ollama model to use (default: from user profile or llama3.2)
    - `temperature`: Generation randomness 0.0-2.0 (default: from user profile or 0.7)
    - `max_tokens`: Maximum response length (default: from user profile or 2048)
    - `mcp_servers`: List of MCP server names to query (default: from user profile or all enabled)
    - `stream`: Enable streaming (must be false for this endpoint)

    **Response:**
    - `response`: Generated AI response
    - `model`: Model used
    - `session_id`: Session ID (for continuing conversation)
    - `mcp_context`: Context gathered from MCP servers
    - `metadata`: Processing metadata (time, servers queried, etc.)
    """
    if request.stream:
        raise HTTPException(
            status_code=400,
            detail="Streaming not supported on this endpoint. Use /api/v1/query/stream instead."
        )

    # Get user_id from request state (set by authentication middleware)
    user_id = getattr(http_request.state, "user_id", None)

    try:
        result = await processor.process_query(
            query=request.query,
            user_id=user_id,
            session_id=request.session_id,
            use_conversation_history=request.use_conversation_history,
            mcp_servers=request.mcp_servers if request.mcp_servers else None,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
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
    Process a user query and return streaming AI-generated response.

    This endpoint returns Server-Sent Events (SSE) for streaming responses.
    Supports conversation history and session management.

    **Request Body:**
    Same as `/api/v1/query` endpoint.

    **Response:**
    Server-Sent Events stream of response tokens.
    """
    # Get user_id from request state (set by authentication middleware)
    user_id = getattr(http_request.state, "user_id", None)

    async def generate():
        try:
            async for chunk in processor.process_streaming_query(
                query=request.query,
                user_id=user_id,
                session_id=request.session_id,
                use_conversation_history=request.use_conversation_history,
                mcp_servers=request.mcp_servers if request.mcp_servers else None,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            ):
                yield f"data: {chunk}\n\n"
        except Exception as e:
            yield f"data: Error: {str(e)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/api/v1/mcp/servers", response_model=MCPServersListResponse, tags=["MCP"])
async def list_mcp_servers(
    processor: QueryProcessor = Depends(get_query_processor),
):
    """
    List all configured MCP servers and their status.

    Returns information about:
    - Server name, description, type
    - Whether enabled, running, healthy
    - Any error messages
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
    Test connection to a specific MCP server.

    **Path Parameters:**
    - `name`: MCP server name

    **Response:**
    Returns whether the server is healthy and any error information.
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
    List available Ollama models.

    Returns list of models available on the Ollama server.

    Note: This is a placeholder. Full implementation would query Ollama API.
    """
    # This is a simplified version
    # Full implementation would query Ollama's /api/tags endpoint
    return {
        "models": [
            {"name": processor.langchain_service.model},
        ],
        "total": 1,
        "note": "Currently returns configured model. Full model list requires Ollama API query."
    }


# Session and Profile Management Endpoints

@router.get("/api/v1/profile", response_model=UserProfileResponse, tags=["Profile"])
async def get_profile(
    user_id: str = Depends(get_current_user),
    session_manager: SessionManager = Depends(get_session_manager),
):
    """
    Get current user's profile.

    Returns user profile including default settings and preferences.
    """
    try:
        profile = await session_manager.get_user_profile(user_id)
        return UserProfileResponse(
            user_id=profile.user_id,
            default_model=profile.default_model,
            default_temperature=profile.default_temperature,
            default_max_tokens=profile.default_max_tokens,
            preferred_mcp_servers=profile.preferred_mcp_servers,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get profile: {str(e)}")


@router.put("/api/v1/profile", response_model=UserProfileResponse, tags=["Profile"])
async def update_profile(
    request: UpdateProfileRequest,
    user_id: str = Depends(get_current_user),
    session_manager: SessionManager = Depends(get_session_manager),
):
    """
    Update current user's profile.

    Allows updating default model, temperature, max tokens, and preferred MCP servers.
    """
    try:
        profile = await session_manager.get_user_profile(user_id)

        # Update fields if provided
        if request.default_model is not None:
            profile.default_model = request.default_model
        if request.default_temperature is not None:
            profile.default_temperature = request.default_temperature
        if request.default_max_tokens is not None:
            profile.default_max_tokens = request.default_max_tokens
        if request.preferred_mcp_servers is not None:
            profile.preferred_mcp_servers = request.preferred_mcp_servers

        await session_manager.update_user_profile(profile)

        return UserProfileResponse(
            user_id=profile.user_id,
            default_model=profile.default_model,
            default_temperature=profile.default_temperature,
            default_max_tokens=profile.default_max_tokens,
            preferred_mcp_servers=profile.preferred_mcp_servers,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update profile: {str(e)}")


@router.get("/api/v1/sessions", response_model=SessionListResponse, tags=["Sessions"])
async def list_sessions(
    limit: int = 20,
    user_id: str = Depends(get_current_user),
    session_manager: SessionManager = Depends(get_session_manager),
):
    """
    List conversation sessions for current user.

    **Query Parameters:**
    - `limit`: Maximum number of sessions to return (default: 20)
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


@router.get("/api/v1/sessions/{session_id}", response_model=SessionResponse, tags=["Sessions"])
async def get_session(
    session_id: str,
    user_id: str = Depends(get_current_user),
    session_manager: SessionManager = Depends(get_session_manager),
):
    """
    Get a specific conversation session.

    **Path Parameters:**
    - `session_id`: Session ID
    """
    try:
        session = await session_manager.get_session(session_id)

        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        # Verify session belongs to user
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
    Delete a conversation session.

    **Path Parameters:**
    - `session_id`: Session ID
    """
    try:
        session = await session_manager.get_session(session_id)

        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        # Verify session belongs to user
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
    Create a new API key for the current user.

    **Request Body:**
    - `name`: Friendly name for the API key
    - `rate_limit`: Optional rate limit (requests per hour)

    **⚠️ Important:** The API key is only shown once. Save it securely!
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
