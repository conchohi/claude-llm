"""
Pydantic models for API request and response validation.
"""

from datetime import datetime
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """Request model for query endpoint."""

    query: str = Field(..., min_length=1, description="User query string")
    session_id: Optional[str] = Field(None, description="Optional session ID for conversation continuity")
    model: Optional[str] = Field(None, description="Ollama model to use (defaults to user profile)")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Generation temperature (defaults to user profile)")
    max_tokens: Optional[int] = Field(None, gt=0, description="Maximum tokens to generate (defaults to user profile)")
    mcp_servers: Optional[List[str]] = Field(None, description="MCP servers to query for context (defaults to user profile)")
    stream: bool = Field(default=False, description="Enable streaming response")
    use_conversation_history: bool = Field(default=True, description="Include conversation history in context")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "What are the top 10 products in the database?",
                "model": "llama3.2",
                "temperature": 0.7,
                "max_tokens": 2048,
                "mcp_servers": ["sqlite"],
                "stream": False,
            }
        }


class MCPContextItem(BaseModel):
    """MCP context for a single server."""

    success: bool = Field(..., description="Whether the query was successful")
    data: Optional[Dict[str, Any]] = Field(None, description="Response data from the server")
    error: Optional[str] = Field(None, description="Error message if query failed")
    latency_ms: float = Field(..., description="Query latency in milliseconds")


class QueryMetadata(BaseModel):
    """Metadata about query processing."""

    processing_time: float = Field(..., description="Total processing time in seconds")
    mcp_servers_queried: List[str] = Field(default_factory=list, description="List of MCP servers queried")
    mcp_servers_successful: List[str] = Field(default_factory=list, description="List of successful MCP queries")
    success: bool = Field(default=True, description="Whether the query was successful")
    conversation_history_used: bool = Field(default=False, description="Whether conversation history was included")


class QueryResponse(BaseModel):
    """Response model for query endpoint."""

    response: str = Field(..., description="Generated response from LLM")
    model: str = Field(..., description="Model used for generation")
    session_id: Optional[str] = Field(None, description="Session ID for conversation continuity")
    mcp_context: Dict[str, MCPContextItem] = Field(default_factory=dict, description="Context from MCP servers")
    metadata: QueryMetadata = Field(..., description="Query processing metadata")
    success: bool = Field(default=True, description="Whether the query was successful")
    error: Optional[str] = Field(None, description="Error message if query failed")

    class Config:
        json_schema_extra = {
            "example": {
                "response": "Based on the database query, here are the top 10 products...",
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
    """Response model for health check endpoint."""

    healthy: bool = Field(..., description="Overall health status")
    ollama: Dict[str, Any] = Field(..., description="Ollama connection status")
    mcp_servers: Dict[str, Dict[str, Any]] = Field(..., description="MCP servers status")

    class Config:
        json_schema_extra = {
            "example": {
                "healthy": True,
                "ollama": {
                    "success": True,
                    "message": "Successfully connected to Ollama",
                    "model": "llama3.2",
                    "base_url": "http://localhost:11434",
                },
                "mcp_servers": {
                    "sqlite": {
                        "enabled": True,
                        "running": True,
                        "healthy": True,
                        "type": "process",
                        "error": None,
                    }
                },
            }
        }


class MCPServerInfo(BaseModel):
    """Information about an MCP server."""

    name: str = Field(..., description="Server name")
    description: str = Field(default="", description="Server description")
    type: str = Field(..., description="Server type (process or http)")
    enabled: bool = Field(..., description="Whether the server is enabled")
    running: bool = Field(default=False, description="Whether the server is running")
    healthy: bool = Field(default=False, description="Whether the server is healthy")
    error: Optional[str] = Field(None, description="Last error message")


class MCPServersListResponse(BaseModel):
    """Response model for listing MCP servers."""

    servers: List[MCPServerInfo] = Field(..., description="List of MCP servers")
    total: int = Field(..., description="Total number of servers")
    enabled: int = Field(..., description="Number of enabled servers")
    running: int = Field(..., description="Number of running servers")


class ErrorResponse(BaseModel):
    """Error response model."""

    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Detailed error information")
    status_code: int = Field(..., description="HTTP status code")

    class Config:
        json_schema_extra = {
            "example": {
                "error": "Bad Request",
                "detail": "Query string cannot be empty",
                "status_code": 400,
            }
        }


class OllamaModel(BaseModel):
    """Ollama model information."""

    name: str = Field(..., description="Model name")
    size: Optional[int] = Field(None, description="Model size in bytes")
    modified_at: Optional[str] = Field(None, description="Last modified timestamp")


class ModelsListResponse(BaseModel):
    """Response model for listing available Ollama models."""

    models: List[OllamaModel] = Field(..., description="List of available models")
    total: int = Field(..., description="Total number of models")


# Session and Authentication Schemas

class UserProfileResponse(BaseModel):
    """User profile response."""

    user_id: str = Field(..., description="User ID")
    default_model: str = Field(..., description="Default Ollama model")
    default_temperature: float = Field(..., description="Default temperature")
    default_max_tokens: int = Field(..., description="Default max tokens")
    preferred_mcp_servers: List[str] = Field(default_factory=list, description="Preferred MCP servers")
    created_at: Optional[datetime] = Field(None, description="Profile creation time")
    updated_at: Optional[datetime] = Field(None, description="Last update time")


class UpdateProfileRequest(BaseModel):
    """Request to update user profile."""

    default_model: Optional[str] = Field(None, description="Default Ollama model")
    default_temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Default temperature")
    default_max_tokens: Optional[int] = Field(None, gt=0, description="Default max tokens")
    preferred_mcp_servers: Optional[List[str]] = Field(None, description="Preferred MCP servers")


class ConversationMessageResponse(BaseModel):
    """Single conversation message."""

    role: str = Field(..., description="Message role (user or assistant)")
    content: str = Field(..., description="Message content")
    timestamp: datetime = Field(..., description="Message timestamp")
    mcp_context: Optional[Dict[str, Any]] = Field(None, description="MCP context for this message")


class SessionResponse(BaseModel):
    """Conversation session response."""

    session_id: str = Field(..., description="Session ID")
    user_id: str = Field(..., description="User ID")
    messages: List[ConversationMessageResponse] = Field(default_factory=list, description="Conversation messages")
    created_at: datetime = Field(..., description="Session creation time")
    updated_at: datetime = Field(..., description="Last update time")
    message_count: int = Field(..., description="Total number of messages")


class SessionListResponse(BaseModel):
    """List of conversation sessions."""

    sessions: List[SessionResponse] = Field(..., description="List of sessions")
    total: int = Field(..., description="Total number of sessions")


class CreateAPIKeyRequest(BaseModel):
    """Request to create a new API key."""

    name: str = Field(..., min_length=1, description="Friendly name for the API key")
    rate_limit: Optional[int] = Field(None, gt=0, description="Optional rate limit (requests per hour)")


class APIKeyResponse(BaseModel):
    """API key response."""

    key: str = Field(..., description="API key (only shown once)")
    user_id: str = Field(..., description="Associated user ID")
    name: str = Field(..., description="API key name")
    created_at: datetime = Field(..., description="Creation time")
    rate_limit: Optional[int] = Field(None, description="Rate limit if set")
