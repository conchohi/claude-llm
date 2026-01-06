"""
FastAPI application entry point.
Initializes the application, middleware, and all services.
"""

from contextlib import asynccontextmanager
from urllib.parse import quote_plus
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config.settings import get_settings
from app.utils.logger import setup_logging, get_logger
from app.core.mcp_loader import load_mcp_config
from app.core.mcp_client import MCPClientManager
from app.core.langchain_service import LangChainService
from app.core.query_processor import QueryProcessor
from app.core.session_manager import SessionManager
from app.api import routes
from app.api.middleware import AuthenticationMiddleware

# Global instances
mcp_client: MCPClientManager | None = None
langchain_service: LangChainService | None = None
query_processor: QueryProcessor | None = None
session_manager: SessionManager | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager.
    Handles startup and shutdown events.
    """
     # ✅ 1단계: 설정 로드
    settings = get_settings()

    # ✅ 2단계: 로깅 초기화 (가장 먼저!)
    setup_logging(
        level=settings.logging.level,
        format=settings.logging.format,
        log_file=settings.logging.file,
        enable_file_logging=settings.logging.enable_file_logging
    )

    logger = get_logger(__name__)

    # Startup
    logger.info("Starting application...")

    global mcp_client, langchain_service, query_processor, session_manager

    try:
        # Load settings

        logger.info("Loaded settings from environment")

        # Initialize SessionManager
        redis_url = f"redis://"
        if settings.redis.password:
            redis_url += f":{quote_plus(settings.redis.password)}@"
        redis_url += f"{settings.redis.host}:{settings.redis.port}/{settings.redis.db}"

        logger.info(f"Connecting to Redis at {settings.redis.host}:{settings.redis.port}")

        session_manager = SessionManager(
            redis_url=redis_url,
            max_connections=settings.redis.max_connections,
            session_ttl=settings.redis.session_ttl,
            cache_ttl=settings.redis.cache_ttl,
            secert_key=settings.auth.secret_key
        )

        try:
            await session_manager.connect()
            logger.info("✓ Successfully connected to Redis")
        except Exception as e:
            logger.error(f"✗ Failed to connect to Redis: {e}")
            if settings.auth.enabled:
                raise RuntimeError(
                "Redis connection failed but authentication is enabled. "
                "Either fix Redis connection or set AUTH_ENABLED=false"
            )
            session_manager = None

        # Initialize LangChain service
        logger.info(f"Initializing LangChain service with provider: {settings.llm.provider}")
        langchain_service = LangChainService(
            provider=settings.llm.provider,
            model=settings.llm.model,
            temperature=settings.llm.temperature,
            max_tokens=settings.llm.max_tokens,
            prompt_path=settings.prompt_path,
            # Ollama-specific
            ollama_base_url=settings.ollama.base_url,
            ollama_keep_alive=settings.ollama.keep_alive,
            # OpenAI-specific
            openai_api_key=settings.openai.api_key,
            openai_base_url=settings.openai.base_url,
            openai_organization=settings.openai.organization,
        )

        # Test LLM connection
        logger.info(f"Testing {settings.llm.provider.upper()} connection...")
        llm_test = await langchain_service.test_connection()
        if llm_test["success"]:
            logger.info(f"✓ Successfully connected to {settings.llm.provider.upper()} (model: {settings.llm.model})")
        else:
            logger.error(f"✗ Failed to connect to {settings.llm.provider.upper()}: {llm_test['message']}")
            logger.warning("Application will start but queries may fail")

        # Initialize MCP client
        logger.info(f"Loading MCP configuration from {settings.mcp.config_path}")
        mcp_config_loader = load_mcp_config(settings.mcp.config_path)
        enabled_servers = mcp_config_loader.get_enabled_servers()

        logger.info(f"Found {len(enabled_servers)} enabled MCP servers")

        mcp_client = MCPClientManager(
            timeout=settings.mcp.timeout,
            max_retries=settings.mcp.max_retries,
        )

        # Initialize MCP servers
        logger.info("Initializing MCP servers...")
        await mcp_client.initialize_servers(enabled_servers)

        # Check server status
        for server in enabled_servers:
            status = mcp_client.get_server_status(server.name)
            if status and status.running:
                logger.info(f"  ✓ {server.name} ({server.type}) - running")
            else:
                error_msg = status.error if status else "Unknown error"
                logger.warning(f"  ✗ {server.name} ({server.type}) - failed: {error_msg}")

        # Initialize query processor
        query_processor = QueryProcessor(
            mcp_client=mcp_client,
            langchain_service=langchain_service,
            session_manager=session_manager,
        )

        # Set query processor and session manager in routes
        routes.set_query_processor(query_processor)
        routes.set_session_manager(session_manager)

        logger.info("✓ Application startup complete")
        logger.info(f"API running at http://{settings.api.host}:{settings.api.port}")
        logger.info(f"Documentation at http://{settings.api.host}:{settings.api.port}/docs")

    except Exception as e:
        logger.error(f"✗ Application startup failed: {e}")
        raise

    yield

    # Shutdown
    logger.info("Shutting down application...")

    if mcp_client:
        logger.info("Stopping MCP servers...")
        await mcp_client.shutdown()

    if session_manager:
        logger.info("Disconnecting from Redis...")
        await session_manager.disconnect()

    logger.info("✓ Application shutdown complete")


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance.
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

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors.origins,
        allow_credentials=settings.cors.allow_credentials,
        allow_methods=settings.cors.allow_methods,
        allow_headers=settings.cors.allow_headers,
    )

    # Authentication middleware (must be added AFTER CORS)
    logger = get_logger(__name__)
    if settings.auth.enabled and session_manager:
        app.add_middleware(
            AuthenticationMiddleware,
            session_manager=session_manager,
            auth_enabled=settings.auth.enabled,
            api_key_header=settings.auth.api_key_header,
        )
        logger.info(f"✓ Authentication middleware enabled (header: {settings.auth.api_key_header})")
    else:
        logger.warning("⚠ Authentication is disabled")

    # Include routers
    app.include_router(routes.router)

    # Exception handlers
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


# Create the application instance
app = create_app()


# Root endpoint
@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with API information."""
    return {
        "name": "LangChain + Ollama + MCP Server",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
    }
