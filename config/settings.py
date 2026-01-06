"""
Centralized configuration management using Pydantic BaseSettings.
Loads configuration from environment variables and .env file.
실행 순서:
Import 시: 모든 클래스 정의 → model_config 메타데이터로 저장
런타임: Settings() 호출 → .env 로드 → Sub-settings 순차 생성 → 필드 값 설정
"""

from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OllamaSettings(BaseSettings):
    """Ollama LLM configuration."""

    base_url: str = Field(default="http://localhost:11434", description="Ollama API base URL")
    model: str = Field(default="llama3.2", description="Default Ollama model")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Generation temperature")
    max_tokens: int = Field(default=2048, gt=0, description="Maximum tokens to generate")
    keep_alive: str = Field(default="5m", description="Keep model loaded in memory")

    model_config = SettingsConfigDict(env_prefix="OLLAMA_")


class APISettings(BaseSettings):
    """FastAPI application configuration."""

    host: str = Field(default="0.0.0.0", description="API host")
    port: int = Field(default=8000, gt=0, lt=65536, description="API port")
    reload: bool = Field(default=True, description="Auto-reload on code changes")
    workers: int = Field(default=1, gt=0, description="Number of worker processes")
    debug: bool = Field(default=True, description="Debug mode")

    model_config = SettingsConfigDict(env_prefix="API_")


class CORSSettings(BaseSettings):
    """CORS configuration."""

    origins: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:8080"],
        description="Allowed CORS origins"
    )
    allow_credentials: bool = Field(default=True, description="Allow credentials")
    allow_methods: List[str] = Field(default=["*"], description="Allowed HTTP methods")
    allow_headers: List[str] = Field(default=["*"], description="Allowed headers")

    model_config = SettingsConfigDict(env_prefix="CORS_")


class LoggingSettings(BaseSettings):
    """Logging configuration."""

    level: str = Field(default="INFO", description="Log level")
    format: str = Field(default="json", description="Log format (json or text)")
    file: str = Field(default="logs/app.log", description="Log file path")
    enable_file_logging: bool = Field(default=False, description="Enable logging to file")
    
    model_config = SettingsConfigDict(env_prefix="LOG_")


class MCPSettings(BaseSettings):
    """MCP client configuration."""

    config_path: str = Field(default="./mcp_servers.json", description="MCP servers config file path")
    timeout: int = Field(default=30, gt=0, description="MCP server timeout in seconds")
    max_retries: int = Field(default=3, ge=0, description="Maximum retry attempts")

    model_config = SettingsConfigDict(env_prefix="MCP_")


class RedisSettings(BaseSettings):
    """Redis configuration for sessions and caching."""

    host: str = Field(default="localhost", description="Redis host")
    port: int = Field(default=6379, gt=0, lt=65536, description="Redis port")
    db: int = Field(default=0, ge=0, description="Redis database number")
    password: str = Field(default="", description="Redis password (optional)")
    session_ttl: int = Field(default=3600, gt=0, description="Session TTL in seconds (1 hour)")
    cache_ttl: int = Field(default=300, gt=0, description="MCP cache TTL in seconds (5 minutes)")

    model_config = SettingsConfigDict(env_prefix="REDIS_")


class AuthSettings(BaseSettings):
    """Authentication configuration."""

    enabled: bool = Field(default=True, description="Enable API key authentication")
    api_key_header: str = Field(default="X-API-Key", description="Header name for API key")
    secret_key: str = Field(default="your-secret-key-change-in-production", description="Secret key for token generation")

    model_config = SettingsConfigDict(env_prefix="AUTH_")


class Settings(BaseSettings):
    """
        Main application settings container. 
        Python이 settings.py를 import할 때 하위 세팅 model_config 읽고 메타데이터 저장
        Settings() ← 이 시점에 실제 객체 생성, 메타데이터 기반 필드를 순회하면서 값 설정
    """
    
    # Sub-settings
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    api: APISettings = Field(default_factory=APISettings)
    cors: CORSSettings = Field(default_factory=CORSSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    mcp: MCPSettings = Field(default_factory=MCPSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)

    # Database
    database_url: str = Field(default="sqlite:///./data/app.db", description="Database URL")
    prompt_path: str = Field(default="./templates", description="Path to HTML templates")
    
    # model_config : Pydantic에서 정의한 메타데이터 변수명, 클래스 정의 시점에 이미 읽힘
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore" 
    ) 


# Singleton pattern for settings
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create settings instance (singleton)."""
    global _settings
    if _settings is None:
        try:
            _settings = Settings()
        except Exception as e:
            raise RuntimeError(f"Failed to load settings: {e}") from e
    return _settings


# Convenience function to reset settings (useful for testing)
def reset_settings() -> None:
    """Reset settings singleton (primarily for testing)."""
    global _settings
    _settings = None
