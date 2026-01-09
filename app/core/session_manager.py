"""
대화 세션 관리자.
Redis (활성 컨텍스트) + 관계형 DB (영구 기록) 이중 저장 방식.
"""

import json
import secrets
from datetime import datetime
from typing import List, Optional
import redis.asyncio as aioredis
from sqlalchemy import select, update, delete
from sqlalchemy.orm import selectinload

from app.models.auth import ConversationSession, ConversationMessage
from app.models.db_models import (
    ConversationSessionModel,
    ConversationMessageModel,
)
from app.core.database_manager import DatabaseManager


class SessionManager:
    """
    대화 세션 관리자.
    Redis (활성 세션, 빠른 조회) + DB (영구 기록) 이중 저장 방식.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        redis_url: str,
        max_connections: int = 10,
        session_ttl: int = 3600,
    ):
        """
        세션 매니저를 초기화합니다.

        Args:
            db_manager: DatabaseManager 인스턴스.
            redis_url: Redis 연결 URL.
            max_connections: Redis 연결 풀 크기.
            session_ttl: Redis 세션 TTL (초) (기본값: 1시간).
        """
        self.db_manager = db_manager
        self.redis_url = redis_url
        self.max_connections = max_connections
        self.session_ttl = session_ttl
        self._redis: Optional[aioredis.Redis] = None

    async def connect(self) -> None:
        """데이터베이스와 Redis에 연결합니다."""
        # 관계형 DB 연결 및 테이블 생성
        await self.db_manager.connect()
        await self.db_manager.create_tables()

        # Redis 연결
        self._redis = await aioredis.from_url(
            self.redis_url,
            max_connections=self.max_connections,
            encoding="utf-8",
            decode_responses=True,
        )

    async def disconnect(self) -> None:
        """데이터베이스와 Redis 연결을 종료합니다."""
        await self.db_manager.disconnect()
        if self._redis:
            await self._redis.aclose()

    def _get_redis(self) -> aioredis.Redis:
        """Redis 클라이언트를 가져옵니다 (연결되지 않은 경우 예외 발생)."""
        if self._redis is None:
            raise RuntimeError("SessionManager not connected to Redis")
        return self._redis

    # 대화 세션 관리 (Redis + 관계형 DB 이중 저장)
    async def create_session(self, user_id: str) -> ConversationSession:
        """
        새 대화 세션을 생성하고 Redis와 DB 모두에 저장합니다.

        Args:
            user_id: 사용자 ID.

        Returns:
            새 ConversationSession 인스턴스.
        """
        session_id = secrets.token_urlsafe(16)

        # DB에 세션 생성
        async for db_session in self.db_manager.get_session():
            session_model = ConversationSessionModel(
                session_id=session_id,
                user_id=user_id,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

            db_session.add(session_model)
            await db_session.commit()
            await db_session.refresh(session_model)

            # ConversationSession 객체 생성
            session = ConversationSession(
                session_id=session_id,
                user_id=user_id,
                messages=[],
                created_at=session_model.created_at,
                updated_at=session_model.updated_at,
            )

            # Redis에도 저장
            await self.save_session(session)

            return session

        raise RuntimeError("데이터베이스 세션을 가져올 수 없습니다.")

    async def get_session_cache(
        self, session_id: str
    ) -> Optional[ConversationSession]:
        """Redis에서 세션을 가져옵니다."""
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
            )
            for msg in data.get("messages", [])
        ]

        return ConversationSession(
            session_id=session_id,
            user_id=data["user_id"],
            messages=messages,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )

    async def get_session_info(
        self, session_id: str
    ) -> Optional[ConversationSession]:
        """DB에서 세션을 가져옵니다."""
        async for db_session in self.db_manager.get_session():
            result = await db_session.execute(
                select(ConversationSessionModel)
                .where(ConversationSessionModel.session_id == session_id)
                .options(selectinload(ConversationSessionModel.messages))
            )
            session_model = result.scalar_one_or_none()

            if not session_model:
                return None

            # 메시지 변환
            messages = [
                ConversationMessage(
                    role=msg.role,
                    content=msg.content,
                    timestamp=msg.timestamp,
                    mcp_context=msg.mcp_context,
                    process_time_ms=msg.process_time_ms,
                )
                for msg in session_model.messages
            ]

            return ConversationSession(
                session_id=session_model.session_id,
                user_id=session_model.user_id,
                messages=messages,
                created_at=session_model.created_at,
                updated_at=session_model.updated_at,
            )

        return None

    async def save_session(self, session: ConversationSession) -> None:
        """Redis에 세션을 저장합니다."""
        redis = self._get_redis()

        session_data = {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "messages": [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat(),
                }
                for msg in session.messages
            ],
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        }

        await redis.set(
            f"session:{session.session_id}",
            json.dumps(session_data),
            ex=self.session_ttl,
        )

    async def save_conversation_message(self, session_id: str, user_id: str, message: ConversationMessage, process_time_ms: int = None) -> None:
        """DB에 메시지를 저장합니다."""
        async for db_session in self.db_manager.get_session():
            # 세션 업데이트
            await db_session.execute(
                update(ConversationSessionModel)
                .where(ConversationSessionModel.session_id == session_id)
                .values(
                    updated_at=datetime.now(),
                )
            )

            # 메시지 저장
            message_model = ConversationMessageModel(
                session_id=session_id,
                user_id=user_id,
                role=message.role,
                content=message.content,
                timestamp=message.timestamp,
                mcp_context=message.mcp_context,
                process_time_ms=process_time_ms if process_time_ms else None,
            )
            db_session.add(message_model)

            await db_session.commit()
            return

        raise RuntimeError("데이터베이스 세션을 가져올 수 없습니다.")


    async def get_user_sessions(
        self, user_id: str, limit: int = 20
    ) -> List[ConversationSession]:
        """
        사용자의 모든 세션을 DB에서 가져옵니다.

        Args:
            user_id: 사용자 ID.
            limit: 반환할 최대 세션 수.

        Returns:
            ConversationSession 인스턴스의 리스트.
        """
        async for db_session in self.db_manager.get_session():
            result = await db_session.execute(
                select(ConversationSessionModel)
                .where(ConversationSessionModel.user_id == user_id)
                .options(selectinload(ConversationSessionModel.messages))
                .order_by(ConversationSessionModel.updated_at.desc())
                .limit(limit)
            )
            session_models = result.scalars().all()

            sessions = []
            for session_model in session_models:
                messages = [
                    ConversationMessage(
                        role=msg.role,
                        content=msg.content,
                        timestamp=msg.timestamp,
                        mcp_context=msg.mcp_context,
                        process_time_ms=msg.process_time_ms,
                    )
                    for msg in session_model.messages
                ]

                sessions.append(
                    ConversationSession(
                        session_id=session_model.session_id,
                        user_id=session_model.user_id,
                        messages=messages,
                        created_at=session_model.created_at,
                        updated_at=session_model.updated_at,
                    )
                )

            return sessions

        return []

    async def delete_session(self, session_id: str) -> None:
        """DB에서 대화 세션을 삭제합니다."""
        # DB에서 삭제
        async for db_session in self.db_manager.get_session():
            await db_session.execute(
                delete(ConversationSessionModel).where(
                    ConversationSessionModel.session_id == session_id
                )
            )
            await db_session.commit()
            return

        raise RuntimeError("데이터베이스 세션을 가져올 수 없습니다.")
