"""
FastAPI 애플리케이션 진입점.
애플리케이션, 미들웨어 및 모든 서비스를 초기화합니다.
"""

from contextlib import asynccontextmanager
from urllib.parse import quote_plus
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config.settings import get_settings
from app.utils.logger import setup_logging, get_logger
from app.core.mcp.mcp_loader import load_mcp_config
from app.core.mcp.mcp_client import MCPClientManager
from app.core.llm.llm_service_base import BaseLLMService
from app.core.llm.llm_service_factory import create_llm_service
from app.core.query_processor import QueryProcessor
from app.core.session_manager import SessionManager
from app.core.api_key_manager import APIKeyManager
from app.core.database_manager import DatabaseManager
from app.api import routes
from app.api.middleware import AuthenticationMiddleware

# 전역 인스턴스
mcp_client: MCPClientManager | None = None
llm_service: BaseLLMService | None = None
query_processor: QueryProcessor | None = None
session_manager: SessionManager | None = None
api_key_manager: APIKeyManager | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    애플리케이션 생명주기 컨텍스트 관리자.
    시작 및 종료 이벤트를 처리합니다.
    """
    # ✅ 1단계: 설정 로드
    settings = get_settings()

    # ✅ 2단계: 로깅 초기화 (가장 먼저!)
    setup_logging(
        level=settings.logging.level,
        log_file=settings.logging.file,
        enable_file_logging=settings.logging.enable_file_logging
    )

    logger = get_logger(__name__)

    # 애플리케이션 시작
    logger.info("Starting application...")

    global mcp_client, llm_service, query_processor, session_manager, api_key_manager

    try:
        logger.info("Loaded settings from environment")

        # DatabaseManager 초기화
        logger.info(f"Connecting to {settings.database.type.upper()} database at {settings.database.host}:{settings.database.port}")
        db_manager = DatabaseManager(
            db_type=settings.database.type,
            host=settings.database.host,
            port=settings.database.port,
            user=settings.database.user,
            password=settings.database.password,
            database=settings.database.name,
            pool_size=settings.database.pool_size,
            max_overflow=settings.database.max_overflow,
            pool_recycle=settings.database.pool_recycle,
        )

        # APIKeyManager 초기화 (DB만 사용)
        logger.info("Initializing API key manager...")
        api_key_manager = APIKeyManager(
            db_manager=db_manager,
            secret_key=settings.auth.secret_key
        )

        try:
            await api_key_manager.connect()
            logger.info("✓ Successfully connected to database for API key management")
        except Exception as e:
            logger.error(f"✗ Failed to connect to database: {e}")
            if settings.auth.enabled:
                raise RuntimeError(
                "Database connection failed but authentication is enabled. "
                "Either fix the connection or set AUTH_ENABLED=false"
            )
            api_key_manager = None

        # SessionManager 초기화 (DB + Redis 하이브리드)
        redis_url = f"redis://"
        if settings.redis.password:
            redis_url += f":{quote_plus(settings.redis.password)}@"
        redis_url += f"{settings.redis.host}:{settings.redis.port}/{settings.redis.db}"

        logger.info(f"Connecting to Redis at {settings.redis.host}:{settings.redis.port}")

        session_manager = SessionManager(
            db_manager=db_manager,
            redis_url=redis_url,
            max_connections=settings.redis.max_connections,
            session_ttl=settings.redis.session_ttl,
        )

        try:
            await session_manager.connect()
            logger.info("✓ Successfully connected to database and Redis for session management")
        except Exception as e:
            logger.error(f"✗ Failed to connect to database or Redis: {e}")
            # 세션 관리는 선택사항이므로 경고만 표시
            logger.warning("Session management will not be available")
            session_manager = None

        # LLM 서비스 초기화 (팩토리 패턴 사용)
        logger.info(f"Initializing LLM service with provider: {settings.llm.provider}")
        llm_service = create_llm_service(settings)

        # LLM 연결 테스트
        logger.info(f"Testing {settings.llm.provider.upper()} connection...")
        llm_test = await llm_service.test_connection()
        if llm_test["success"]:
            logger.info(f"✓ Successfully connected to {settings.llm.provider.upper()} (model: {settings.llm.model})")
        else:
            logger.error(f"✗ Failed to connect to {settings.llm.provider.upper()}: {llm_test['message']}")
            logger.warning("Application will start but queries may fail")

        # MCP 클라이언트 초기화
        logger.info(f"Loading MCP configuration from {settings.mcp.config_path}")
        mcp_config_loader = load_mcp_config(settings.mcp.config_path)
        enabled_servers = mcp_config_loader.get_enabled_servers()

        logger.info(f"Found {len(enabled_servers)} enabled MCP servers")

        mcp_client = MCPClientManager(
            timeout=settings.mcp.timeout,
            max_retries=settings.mcp.max_retries,
        )

        # MCP 서버 초기화
        logger.info("Initializing MCP servers...")
        await mcp_client.initialize_servers(enabled_servers)

        # 서버 상태 확인
        for server in enabled_servers:
            status = mcp_client.get_server_status(server.name)
            if status and status.running:
                logger.info(f"  ✓ {server.name} ({server.type}) - running")
            else:
                error_msg = status.error if status else "Unknown error"
                logger.warning(f"  ✗ {server.name} ({server.type}) - failed: {error_msg}")

        # 쿼리 프로세서 초기화
        query_processor = QueryProcessor(
            mcp_client=mcp_client,
            llm_service=llm_service,
            session_manager=session_manager,
        )

        # 라우트에 쿼리 프로세서 및 세션 매니저 설정
        routes.set_query_processor(query_processor)
        routes.set_session_manager(session_manager)

        logger.info("✓ Application startup complete")
        logger.info(f"API running at http://{settings.api.host}:{settings.api.port}")
        logger.info(f"Documentation at http://{settings.api.host}:{settings.api.port}/docs")

    except Exception as e:
        logger.error(f"✗ Application startup failed: {e}")
        raise

    yield

    # 애플리케이션 종료
    logger.info("Shutting down application...")

    if mcp_client:
        logger.info("Stopping MCP servers...")
        await mcp_client.shutdown()

    if session_manager:
        logger.info("Disconnecting from database and Redis...")
        await session_manager.disconnect()

    logger.info("✓ Application shutdown complete")


def create_app() -> FastAPI:
    """
    FastAPI 애플리케이션을 생성하고 설정합니다.

    Returns:
        설정된 FastAPI 애플리케이션 인스턴스.
    """
    settings = get_settings()

    app = FastAPI(
        title="LangChain + Ollama + MCP Server",
        description=(
            "A Python-based LLM server integrating LangChain, Ollama, and Model Context Protocol (MCP) "
            "for enhanced AI responses with extensible context sources."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS 미들웨어
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors.origins,
        allow_credentials=settings.cors.allow_credentials,
        allow_methods=settings.cors.allow_methods,
        allow_headers=settings.cors.allow_headers,
    )

    # 인증 미들웨어 (CORS 이후에 추가해야 함)
    logger = get_logger(__name__)
    if settings.auth.enabled:
        app.add_middleware(
            AuthenticationMiddleware,
            api_key_manager_getter=lambda: api_key_manager,
            auth_enabled=settings.auth.enabled,
            api_key_header=settings.auth.api_key_header,
        )
        logger.info(f"✓ Authentication middleware enabled (header: {settings.auth.api_key_header})")
    else:
        logger.warning("⚠ Authentication is disabled")

    # 라우터 포함
    app.include_router(routes.router)

    # 예외 핸들러
    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        logger = get_logger(__name__)
        logger.error(f"Unhandled exception: {exc}", exc_info=True)

        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "detail": "An internal error occurred. Please contact support.",
                "status_code": 500,
            },
        )

    return app


# 애플리케이션 인스턴스 생성
app = create_app()


# 루트 엔드포인트
@app.get("/", tags=["Root"])
async def root():
    """루트 엔드포인트 (API 정보 제공)."""
    return {
        "name": "LangChain + Ollama + MCP Server",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
    }
