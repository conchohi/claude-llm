"""
대화 기록, 사용자 프로필 및 MCP 캐싱을 위한 Redis 기반 세션 매니저.
"""

import json
import hashlib
import secrets
import hmac
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import redis.asyncio as aioredis

from app.models.auth import UserProfile, ConversationSession, ConversationMessage, APIKey
from config.settings import get_settings

class SessionManager:
    """
    Redis를 사용하여 사용자 세션, 프로필 및 캐싱을 관리합니다.
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
        세션 매니저를 초기화합니다.

        Args:
            redis_url: Redis 연결 URL (redis://host:port/db).
            max_connections: Redis 연결 풀 크기.
            session_ttl: 세션 TTL (초) (기본값: 1시간).
            cache_ttl: MCP 캐시 TTL (초) (기본값: 5분).
            secert_key: API 키 서명을 위한 HMAC 비밀키.
        """
        self.redis_url = redis_url
        self.max_connections = max_connections
        self.session_ttl = session_ttl
        self.cache_ttl = cache_ttl
        self._redis: Optional[aioredis.Redis] = None
        self.secret_key = secert_key

    async def connect(self) -> None:
        """Redis에 연결합니다."""
        self._redis = await aioredis.from_url(
            self.redis_url,
            max_connections=self.max_connections,
            encoding="utf-8",
            decode_responses=True,
        )

    async def disconnect(self) -> None:
        """Redis 연결을 끊습니다."""
        if self._redis:
            await self._redis.aclose()

    def _get_redis(self) -> aioredis.Redis:
        """Redis 클라이언트를 가져옵니다 (연결되지 않은 경우 예외 발생)."""
        if self._redis is None:
            raise RuntimeError("SessionManager not connected to Redis")
        return self._redis

    # API 키 관리

    def _hash_api_key(self, api_key: str) -> str:
        """저장을 위해 API 키를 해시합니다."""
        return hashlib.sha256(api_key.encode()).hexdigest()

    def generate_api_key(self) -> str:
        """새로운 보안 API 키를 생성합니다."""
        return secrets.token_urlsafe(32)

    async def create_api_key(
        self,
        user_id: str,
        name: str,
        rate_limit: Optional[int] = None,
    ) -> tuple[str, APIKey]:
        """
        새 API 키를 생성합니다.

        Args:
            user_id: 키와 연결할 사용자 ID.
            name: 키의 친숙한 이름.
            rate_limit: 선택적 속도 제한 (시간당 요청 수).

        Returns:
            (plain_key, APIKey 객체)의 튜플.
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

        # Redis에 저장
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
        API 키를 검증하고 연결된 사용자 ID를 반환합니다.

        Args:
            api_key: 검증할 API 키.

        Returns:
            유효한 경우 사용자 ID, 그렇지 않으면 None.
        """
        try:
            # API 키 분리
            token, provided_signature = api_key.split(".")

            # 서명 재생성
            expected_signature = hmac.new(
                self.secret_key.encode(),
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

            # 마지막 사용 타임스탬프 업데이트
            await redis.hset(
                f"apikey:{key_hash}",
                "last_used",
                datetime.now().isoformat(),
            )

            return key_data.get("user_id")
        except ValueError:
            return None  # 잘못된 형식


    # 사용자 프로필 관리

    async def get_user_profile(self, user_id: str) -> UserProfile:
        """
        사용자 프로필을 가져옵니다 (존재하지 않으면 기본값 생성).

        Args:
            user_id: 사용자 ID.

        Returns:
            UserProfile 인스턴스.
        """
        redis = self._get_redis()

        profile_data = await redis.hgetall(f"profile:{user_id}")

        if not profile_data:
            settings = get_settings()
            
            # 기본 프로필 생성
            profile = UserProfile(user_id=user_id,
                                  default_model=settings.llm.default_model,
                                  default_temperature=settings.llm.default_temperature,
                                  default_max_tokens=settings.llm.default_max_tokens)
            await self.update_user_profile(profile)
            return profile

        return UserProfile(
            user_id=user_id,
            default_model=profile_data.get("default_model", ""),
            default_temperature=float(profile_data.get("default_temperature", "")),
            default_max_tokens=int(profile_data.get("default_max_tokens", "")),
            preferred_mcp_servers=json.loads(profile_data.get("preferred_mcp_servers", "[]")),
            metadata=json.loads(profile_data.get("metadata", "{}")),
            created_at=datetime.fromisoformat(profile_data["created_at"]) if profile_data.get("created_at") else None,
            updated_at=datetime.fromisoformat(profile_data["updated_at"]) if profile_data.get("updated_at") else None,
        )

    async def update_user_profile(self, profile: UserProfile) -> None:
        """
        Redis에서 사용자 프로필을 업데이트합니다.

        Args:
            profile: UserProfile 인스턴스.
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

    # 대화 세션 관리

    async def create_session(self, user_id: str) -> ConversationSession:
        """
        새 대화 세션을 생성합니다.

        Args:
            user_id: 사용자 ID.

        Returns:
            새 ConversationSession 인스턴스.
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
        대화 세션을 가져옵니다.

        Args:
            session_id: 세션 ID.

        Returns:
            존재하면 ConversationSession, 그렇지 않으면 None.
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
        대화 세션을 Redis에 저장합니다.

        Args:
            session: ConversationSession 인스턴스.
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

        # 사용자의 세션 목록에도 추가
        await redis.sadd(f"user_sessions:{session.user_id}", session.session_id)

    async def get_user_sessions(self, user_id: str, limit: int = 20) -> List[ConversationSession]:
        """
        사용자의 모든 세션을 가져옵니다.

        Args:
            user_id: 사용자 ID.
            limit: 반환할 최대 세션 수.

        Returns:
            ConversationSession 인스턴스의 리스트.
        """
        redis = self._get_redis()

        session_ids = await redis.smembers(f"user_sessions:{user_id}")
        if not session_ids:
            return []

        # 최대 `limit`개의 최근 세션 가져오기
        sessions = []
        for session_id in list(session_ids)[:limit]:
            session = await self.get_session(session_id)
            if session:
                sessions.append(session)

        # updated_at으로 정렬
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions[:limit]

    async def delete_session(self, session_id: str) -> None:
        """대화 세션을 삭제합니다."""
        redis = self._get_redis()

        session = await self.get_session(session_id)
        if session:
            await redis.srem(f"user_sessions:{session.user_id}", session_id)

        await redis.delete(f"session:{session_id}")

    # MCP 컨텍스트 캐싱

    async def get_mcp_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """
        캐시된 MCP 응답을 가져옵니다.

        Args:
            cache_key: 캐시 키 (일반적으로 쿼리 + 서버 이름의 해시).

        Returns:
            존재하면 캐시된 응답 데이터, 그렇지 않으면 None.
        """
        redis = self._get_redis()

        cached = await redis.get(f"mcp_cache:{cache_key}")
        if cached:
            return json.loads(cached)
        return None

    async def set_mcp_cache(self, cache_key: str, data: Dict[str, Any]) -> None:
        """
        MCP 응답을 캐시합니다.

        Args:
            cache_key: 캐시 키.
            data: 캐시할 응답 데이터.
        """
        redis = self._get_redis()

        await redis.set(
            f"mcp_cache:{cache_key}",
            json.dumps(data),
            ex=self.cache_ttl,
        )

    def generate_mcp_cache_key(self, server_name: str, query: str) -> str:
        """
        MCP 쿼리를 위한 캐시 키를 생성합니다.

        Args:
            server_name: MCP 서버 이름.
            query: 쿼리 문자열.

        Returns:
            캐시 키 해시.
        """
        content = f"{server_name}:{query}"
        return hashlib.sha256(content.encode()).hexdigest()
