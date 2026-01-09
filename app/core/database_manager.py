"""
데이터베이스 연결 관리자.
MySQL/MariaDB와 PostgreSQL을 지원합니다.
"""

from typing import AsyncGenerator, Optional
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, AsyncEngine, async_sessionmaker
from sqlalchemy.pool import QueuePool
from app.models.db_models import Base


class DatabaseManager:
    """
    비동기 데이터베이스 연결 관리자.
    SQLAlchemy의 비동기 엔진을 사용하여 MySQL/MariaDB, PostgreSQL을 지원합니다.
    """

    def __init__(
        self,
        db_type: str,
        host: str = "localhost",
        port: int = 3306,
        user: str = "root",
        password: str = "",
        database: str = "claude_db",
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_recycle: int = 3600,
    ):
        """
        데이터베이스 관리자를 초기화합니다.

        Args:
            db_type: 데이터베이스 타입 ('mysql' 또는 'postgresql'). MariaDB는 'mysql' 사용.
            host: 데이터베이스 호스트.
            port: 데이터베이스 포트.
            user: 데이터베이스 사용자.
            password: 데이터베이스 비밀번호.
            database: 데이터베이스 이름.
            pool_size: 연결 풀 크기.
            max_overflow: 최대 오버플로우 연결 수.
            pool_recycle: 연결 재활용 시간(초).
        """
        self.db_type = db_type.lower()
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool_recycle = pool_recycle

        self._engine: Optional[AsyncEngine] = None
        self._session_maker: Optional[async_sessionmaker[AsyncSession]] = None

    def _get_database_url(self) -> str:
        """데이터베이스 타입에 따른 연결 URL을 생성합니다."""
        if self.db_type == "mysql":
            # aiomysql 드라이버 사용 (MySQL과 MariaDB 모두 지원)
            return f"mysql+aiomysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
        elif self.db_type == "postgresql":
            # asyncpg 드라이버 사용
            return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
        else:
            raise ValueError(f"지원하지 않는 데이터베이스 타입: {self.db_type}. 'mysql' 또는 'postgresql'을 사용하세요.")

    async def connect(self) -> None:
        """데이터베이스에 연결합니다."""
        if self._engine is not None:
            return

        database_url = self._get_database_url()

        self._engine = create_async_engine(
            database_url,
            echo=False,
            pool_size=self.pool_size,
            max_overflow=self.max_overflow,
            pool_recycle=self.pool_recycle,
            pool_pre_ping=True,  # 연결 상태 확인
        )

        self._session_maker = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def disconnect(self) -> None:
        """데이터베이스 연결을 종료합니다."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_maker = None

    async def create_tables(self) -> None:
        """데이터베이스 테이블을 생성합니다."""
        if not self._engine:
            raise RuntimeError("데이터베이스에 연결되지 않았습니다.")

        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def drop_tables(self) -> None:
        """데이터베이스 테이블을 삭제합니다."""
        if not self._engine:
            raise RuntimeError("데이터베이스에 연결되지 않았습니다.")

        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        데이터베이스 세션을 가져옵니다 (비동기 제너레이터).

        Yields:
            AsyncSession: SQLAlchemy 비동기 세션.
        """
        if not self._session_maker:
            raise RuntimeError("데이터베이스에 연결되지 않았습니다.")

        async with self._session_maker() as session:
            try:
                yield session
            finally:
                await session.close()

    @property
    def engine(self) -> AsyncEngine:
        """데이터베이스 엔진을 반환합니다."""
        if not self._engine:
            raise RuntimeError("데이터베이스에 연결되지 않았습니다.")
        return self._engine
