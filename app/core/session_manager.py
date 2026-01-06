"""
Redis-based session manager for conversation history, user profiles, and MCP caching.
"""

import json
import hashlib
import secrets
import hmac
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import redis.asyncio as aioredis

from app.models.auth import UserProfile, ConversationSession, ConversationMessage, APIKey


class SessionManager:
    """
    Manages user sessions, profiles, and caching using Redis.
    """

    def __init__(
        self,
        redis_url: str,
        max_connections: int = 10,
        session_ttl: int = 3600,
        cache_ttl: int = 300,
        secert_key: str = ""
    ):
        """
        Initialize the session manager.

        Args:
            redis_url: Redis connection URL (redis://host:port/db).
            session_ttl: Session TTL in seconds (default: 1 hour).
            cache_ttl: MCP cache TTL in seconds (default: 5 minutes).
        """
        self.redis_url = redis_url
        self.session_ttl = session_ttl
        self.cache_ttl = cache_ttl
        self._redis: Optional[aioredis.Redis] = None
        self.secret_key = secert_key

    async def connect(self) -> None:
        """Connect to Redis."""
        self._redis = await aioredis.from_url(
            self.redis_url,
            max_connections=self.max_connections,
            encoding="utf-8",
            decode_responses=True,
        )

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.aclose()

    def _get_redis(self) -> aioredis.Redis:
        """Get Redis client (raises if not connected)."""
        if self._redis is None:
            raise RuntimeError("SessionManager not connected to Redis")
        return self._redis

    # API Key Management

    def _hash_api_key(self, api_key: str) -> str:
        """Hash an API key for storage."""
        return hashlib.sha256(api_key.encode()).hexdigest()

    def generate_api_key(self) -> str:
        """Generate a new secure API key."""
        return secrets.token_urlsafe(32)

    async def create_api_key(
        self,
        user_id: str,
        name: str,
        rate_limit: Optional[int] = None,
    ) -> tuple[str, APIKey]:
        """
        Create a new API key.

        Args:
            user_id: User ID to associate with the key.
            name: Friendly name for the key.
            rate_limit: Optional rate limit (requests per hour).

        Returns:
            Tuple of (plain_key, APIKey object).
        """
        redis = self._get_redis()

        # 랜덤 토큰 생성
        random_token = secrets.token_urlsafe(32)
        
        # HMAC 서명 생성 (secret_key 사용)
        signature = hmac.new(
            self.secret_key.encode(), 
            random_token.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # API 키 = 토큰 + 서명
        plain_key = f"{random_token}.{signature}"
        
        key_hash = self._hash_api_key(plain_key)

        api_key = APIKey(
            key_hash=key_hash,
            user_id=user_id,
            name=name,
            created_at=datetime.now(),
            is_active=True,
            rate_limit=rate_limit,
        )

        # Store in Redis
        key_data = {
            "user_id": api_key.user_id,
            "name": api_key.name,
            "created_at": api_key.created_at.isoformat(),
            "is_active": str(api_key.is_active),
            "rate_limit": str(api_key.rate_limit) if api_key.rate_limit else "",
        }

        await redis.hset(f"apikey:{key_hash}", mapping=key_data)

        return plain_key, api_key

    async def validate_api_key(self, api_key: str) -> Optional[str]:
        """
        Validate an API key and return the associated user ID.

        Args:
            api_key: API key to validate.

        Returns:
            User ID if valid, None otherwise.
        """
        try:
            # API 키 분리
            token, provided_signature = api_key.split(".")
            
            # 서명 재생성
            expected_signature = hmac.new(
                self.secret_key.encode(),  # ← 여기서 사용!
                token.encode(),
                hashlib.sha256
            ).hexdigest()
            
            # 서명 검증 (타이밍 공격 방지)
            if not hmac.compare_digest(provided_signature, expected_signature):
                return None  # 위조된 키
            
            redis = self._get_redis()
            # Redis에서 조회
            key_hash = self._hash_api_key(api_key)
            key_data = await redis.hgetall(f"apikey:{key_hash}")
            
            if not key_data or key_data.get("is_active") != "True":
                return None

            # Update last used timestamp
            await redis.hset(
                f"apikey:{key_hash}",
                "last_used",
                datetime.now().isoformat(),
            )

            return key_data.get("user_id")
        except ValueError:
            return None  # 잘못된 형식
       

    # User Profile Management

    async def get_user_profile(self, user_id: str) -> UserProfile:
        """
        Get user profile (creates default if doesn't exist).

        Args:
            user_id: User ID.

        Returns:
            UserProfile instance.
        """
        redis = self._get_redis()

        profile_data = await redis.hgetall(f"profile:{user_id}")

        if not profile_data:
            # Create default profile
            profile = UserProfile(user_id=user_id)
            await self.update_user_profile(profile)
            return profile

        return UserProfile(
            user_id=user_id,
            default_model=profile_data.get("default_model", "llama3.2"),
            default_temperature=float(profile_data.get("default_temperature", "0.7")),
            default_max_tokens=int(profile_data.get("default_max_tokens", "2048")),
            preferred_mcp_servers=json.loads(profile_data.get("preferred_mcp_servers", "[]")),
            metadata=json.loads(profile_data.get("metadata", "{}")),
            created_at=datetime.fromisoformat(profile_data["created_at"]) if profile_data.get("created_at") else None,
            updated_at=datetime.fromisoformat(profile_data["updated_at"]) if profile_data.get("updated_at") else None,
        )

    async def update_user_profile(self, profile: UserProfile) -> None:
        """
        Update user profile in Redis.

        Args:
            profile: UserProfile instance.
        """
        redis = self._get_redis()

        now = datetime.now()
        if profile.created_at is None:
            profile.created_at = now
        profile.updated_at = now

        profile_data = {
            "default_model": profile.default_model,
            "default_temperature": str(profile.default_temperature),
            "default_max_tokens": str(profile.default_max_tokens),
            "preferred_mcp_servers": json.dumps(profile.preferred_mcp_servers),
            "metadata": json.dumps(profile.metadata),
            "created_at": profile.created_at.isoformat(),
            "updated_at": profile.updated_at.isoformat(),
        }

        await redis.hset(f"profile:{profile.user_id}", mapping=profile_data)

    # Conversation Session Management

    async def create_session(self, user_id: str) -> ConversationSession:
        """
        Create a new conversation session.

        Args:
            user_id: User ID.

        Returns:
            New ConversationSession instance.
        """
        session_id = secrets.token_urlsafe(16)
        session = ConversationSession(
            session_id=session_id,
            user_id=user_id,
        )

        await self.save_session(session)
        return session

    async def get_session(self, session_id: str) -> Optional[ConversationSession]:
        """
        Get a conversation session.

        Args:
            session_id: Session ID.

        Returns:
            ConversationSession if exists, None otherwise.
        """
        redis = self._get_redis()

        session_data = await redis.get(f"session:{session_id}")
        if not session_data:
            return None

        data = json.loads(session_data)

        messages = [
            ConversationMessage(
                role=msg["role"],
                content=msg["content"],
                timestamp=datetime.fromisoformat(msg["timestamp"]),
                mcp_context=msg.get("mcp_context"),
                metadata=msg.get("metadata", {}),
            )
            for msg in data.get("messages", [])
        ]

        return ConversationSession(
            session_id=session_id,
            user_id=data["user_id"],
            messages=messages,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            metadata=data.get("metadata", {}),
        )

    async def save_session(self, session: ConversationSession) -> None:
        """
        Save a conversation session to Redis.

        Args:
            session: ConversationSession instance.
        """
        redis = self._get_redis()

        session_data = {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "messages": [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat(),
                    "mcp_context": msg.mcp_context,
                    "metadata": msg.metadata,
                }
                for msg in session.messages
            ],
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "metadata": session.metadata,
        }

        await redis.set(
            f"session:{session.session_id}",
            json.dumps(session_data),
            ex=self.session_ttl,
        )

        # Also add to user's session list
        await redis.sadd(f"user_sessions:{session.user_id}", session.session_id)

    async def get_user_sessions(self, user_id: str, limit: int = 20) -> List[ConversationSession]:
        """
        Get all sessions for a user.

        Args:
            user_id: User ID.
            limit: Maximum number of sessions to return.

        Returns:
            List of ConversationSession instances.
        """
        redis = self._get_redis()

        session_ids = await redis.smembers(f"user_sessions:{user_id}")
        if not session_ids:
            return []

        # Get up to `limit` most recent sessions
        sessions = []
        for session_id in list(session_ids)[:limit]:
            session = await self.get_session(session_id)
            if session:
                sessions.append(session)

        # Sort by updated_at
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions[:limit]

    async def delete_session(self, session_id: str) -> None:
        """Delete a conversation session."""
        redis = self._get_redis()

        session = await self.get_session(session_id)
        if session:
            await redis.srem(f"user_sessions:{session.user_id}", session_id)

        await redis.delete(f"session:{session_id}")

    # MCP Context Caching

    async def get_mcp_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """
        Get cached MCP response.

        Args:
            cache_key: Cache key (typically hash of query + server name).

        Returns:
            Cached response data if exists, None otherwise.
        """
        redis = self._get_redis()

        cached = await redis.get(f"mcp_cache:{cache_key}")
        if cached:
            return json.loads(cached)
        return None

    async def set_mcp_cache(self, cache_key: str, data: Dict[str, Any]) -> None:
        """
        Cache MCP response.

        Args:
            cache_key: Cache key.
            data: Response data to cache.
        """
        redis = self._get_redis()

        await redis.set(
            f"mcp_cache:{cache_key}",
            json.dumps(data),
            ex=self.cache_ttl,
        )

    def generate_mcp_cache_key(self, server_name: str, query: str) -> str:
        """
        Generate cache key for MCP query.

        Args:
            server_name: MCP server name.
            query: Query string.

        Returns:
            Cache key hash.
        """
        content = f"{server_name}:{query}"
        return hashlib.sha256(content.encode()).hexdigest()
