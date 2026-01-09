"""
API 키 관리자.
관계형 데이터베이스를 사용하여 API 키를 관리합니다.
"""

import hashlib
import hmac
import secrets
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update

from app.models.auth import APIKey
from app.models.db_models import APIKeyModel
from app.core.database_manager import DatabaseManager


class APIKeyManager:
    """
    API 키 관리자.
    관계형 데이터베이스만 사용하여 API 키를 영구 저장합니다.
    """

    def __init__(self, db_manager: DatabaseManager, secret_key: str = ""):
        """
        API 키 관리자를 초기화합니다.

        Args:
            db_manager: DatabaseManager 인스턴스.
            secret_key: API 키 서명을 위한 HMAC 비밀키.
        """
        self.db_manager = db_manager
        self.secret_key = secret_key

    async def connect(self) -> None:
        """데이터베이스에 연결하고 테이블을 생성합니다."""
        await self.db_manager.connect()
        await self.db_manager.create_tables()

    async def disconnect(self) -> None:
        """데이터베이스 연결을 종료합니다."""
        await self.db_manager.disconnect()

    def _hash_api_key(self, api_key: str) -> str:
        """저장을 위해 API 키를 해시합니다."""
        return hashlib.sha256(api_key.encode()).hexdigest()

    async def create_api_key(
        self,
        user_id: str,
        name: str,
        rate_limit: Optional[int] = None,
    ) -> tuple[str, APIKey]:
        """
        새 API 키를 생성하고 관계형 DB에 저장합니다.

        Args:
            user_id: 키와 연결할 사용자 ID.
            name: 키의 친숙한 이름.
            rate_limit: 선택적 속도 제한 (시간당 요청 수).

        Returns:
            (plain_key, APIKey 객체)의 튜플.
        """
        # 랜덤 토큰 생성
        random_token = secrets.token_urlsafe(32)

        # HMAC 서명 생성 (secret_key 사용)
        signature = hmac.new(
            self.secret_key.encode(), random_token.encode(), hashlib.sha256
        ).hexdigest()

        # API 키 = 토큰 + 서명
        plain_key = f"{random_token}.{signature}"

        key_hash = self._hash_api_key(plain_key)

        # 데이터베이스에 저장
        async for db_session in self.db_manager.get_session():
            api_key_model = APIKeyModel(
                key_hash=key_hash,
                user_id=user_id,
                name=name,
                created_at=datetime.now(),
                is_active=True,
                rate_limit=rate_limit,
            )

            db_session.add(api_key_model)
            await db_session.commit()
            await db_session.refresh(api_key_model)

            # APIKey 객체로 변환
            api_key = APIKey(
                key_hash=key_hash,
                user_id=user_id,
                name=name,
                created_at=api_key_model.created_at,
                is_active=api_key_model.is_active,
                rate_limit=rate_limit,
            )

            return plain_key, api_key

        raise RuntimeError("데이터베이스 세션을 가져올 수 없습니다.")

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
                self.secret_key.encode(), token.encode(), hashlib.sha256
            ).hexdigest()

            # 서명 검증 (타이밍 공격 방지)
            if not hmac.compare_digest(provided_signature, expected_signature):
                return None  # 위조된 키

            # 데이터베이스에서 조회
            key_hash = self._hash_api_key(api_key)
            
            async for db_session in self.db_manager.get_session():
                result = await db_session.execute(
                    select(APIKeyModel).where(APIKeyModel.key_hash == key_hash)
                )
                api_key_model = result.scalar_one_or_none()
                
                if not api_key_model or not api_key_model.is_active:
                    return None

                # 마지막 사용 타임스탬프 업데이트
                await db_session.execute(
                    update(APIKeyModel)
                    .where(APIKeyModel.key_hash == key_hash)
                    .values(last_used=datetime.now())
                )
                await db_session.commit()

                return api_key_model.user_id

            return None
        except ValueError:
            return None  # 잘못된 형식
        except Exception:
            return None
