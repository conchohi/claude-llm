"""
Authentication and session data models.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any


@dataclass
class UserProfile:
    """User profile and preferences."""

    user_id: str
    """Unique user identifier (API key hash or user ID)."""

    default_model: str = "llama3.2"
    """Default Ollama model for this user."""

    default_temperature: float = 0.7
    """Default generation temperature."""

    default_max_tokens: int = 2048
    """Default maximum tokens."""

    preferred_mcp_servers: List[str] = field(default_factory=list)
    """List of preferred MCP servers."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Additional user metadata."""

    created_at: Optional[datetime] = None
    """Profile creation timestamp."""

    updated_at: Optional[datetime] = None
    """Profile last update timestamp."""


@dataclass
class ConversationMessage:
    """Single message in a conversation."""

    role: str
    """Message role: 'user' or 'assistant'."""

    content: str
    """Message content."""

    timestamp: datetime
    """Message timestamp."""

    mcp_context: Optional[Dict[str, Any]] = None
    """MCP context used for this message (for assistant messages)."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Additional message metadata."""


@dataclass
class ConversationSession:
    """Complete conversation session."""

    session_id: str
    """Unique session identifier."""

    user_id: str
    """User identifier."""

    messages: List[ConversationMessage] = field(default_factory=list)
    """List of messages in this conversation."""

    created_at: datetime = field(default_factory=datetime.now)
    """Session creation timestamp."""

    updated_at: datetime = field(default_factory=datetime.now)
    """Session last update timestamp."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Additional session metadata."""

    def add_message(self, role: str, content: str, mcp_context: Optional[Dict] = None) -> ConversationMessage:
        """Add a new message to the conversation."""
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
        Get conversation history in LangChain format.

        Args:
            limit: Optional limit on number of recent messages.

        Returns:
            List of messages in {role, content} format.
        """
        messages = self.messages[-limit:] if limit else self.messages
        return [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]


@dataclass
class APIKey:
    """API key information."""

    key_hash: str
    """Hashed API key."""

    user_id: str
    """Associated user ID."""

    name: str
    """Friendly name for this API key."""

    created_at: datetime
    """Key creation timestamp."""

    last_used: Optional[datetime] = None
    """Last time this key was used."""

    is_active: bool = True
    """Whether the key is active."""

    rate_limit: Optional[int] = None
    """Optional rate limit (requests per hour)."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Additional key metadata."""
