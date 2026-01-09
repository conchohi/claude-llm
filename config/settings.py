"""
Pydantic BaseSettings를 사용한 중앙 집중식 설정 관리.
환경 변수와 .env 파일에서 설정을 로드합니다.
실행 순서:
Import 시: 모든 클래스 정의 → model_config 메타데이터로 저장
런타임: Settings() 호출 → .env 로드 → Sub-settings 순차 생성 → 필드 값 설정
"""

from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    """LLM 제공자 설정."""

    provider: str = Field(default="ollama", description="LLM 제공자: 'ollama' 또는 'openai'")
    model: str = Field(default="llama3.2", description="기본 LLM 모델")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="생성 온도")
    max_tokens: int = Field(default=2048, gt=0, description="생성할 최대 토큰 수")

    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


class OllamaSettings(BaseSettings):
    """Ollama 전용 설정."""

    base_url: str = Field(default="http://localhost:11434", description="Ollama API 기본 URL")
    keep_alive: str = Field(default="5m", description="메모리에 모델을 로드된 상태로 유지")

    model_config = SettingsConfigDict(
        env_prefix="OLLAMA_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


class OpenAISettings(BaseSettings):
    """OpenAI 전용 설정."""

    api_key: str = Field(default="", description="OpenAI API 키 (Bearer 토큰)")
    base_url: str = Field(default="https://api.openai.com/v1", description="OpenAI API 기본 URL (호환 API용)")
    organization: str = Field(default="", description="OpenAI 조직 ID (선택사항)")
    top_p: float = Field(default=1.0, ge=0.0, le=1.0, description="핵 샘플링 확률 (0.0-1.0)")
    frequency_penalty: float = Field(default=0.0, ge=-2.0, le=2.0, description="토큰 반복 패널티 (-2.0 ~ 2.0)")

    model_config = SettingsConfigDict(
        env_prefix="OPENAI_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


class APISettings(BaseSettings):
    """FastAPI 애플리케이션 설정."""

    host: str = Field(default="0.0.0.0", description="API 호스트")
    port: int = Field(default=8000, gt=0, lt=65536, description="API 포트")
    reload: bool = Field(default=True, description="코드 변경 시 자동 리로드")
    workers: int = Field(default=1, gt=0, description="워커 프로세스 수")
    debug: bool = Field(default=True, description="디버그 모드")

    model_config = SettingsConfigDict(
        env_prefix="API_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


class CORSSettings(BaseSettings):
    """CORS 설정."""

    origins: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:8080"],
        description="허용된 CORS 출처"
    )
    allow_credentials: bool = Field(default=True, description="자격 증명 허용")
    allow_methods: List[str] = Field(default=["*"], description="허용된 HTTP 메서드")
    allow_headers: List[str] = Field(default=["*"], description="허용된 헤더")

    model_config = SettingsConfigDict(
        env_prefix="CORS_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


class LoggingSettings(BaseSettings):
    """로깅 설정."""

    level: str = Field(default="INFO", description="로그 레벨")
    file: str = Field(default="logs/app.log", description="로그 파일 경로")
    enable_file_logging: bool = Field(default=False, description="파일 로깅 활성화")

    model_config = SettingsConfigDict(
        env_prefix="LOG_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


class MCPSettings(BaseSettings):
    """MCP 클라이언트 설정."""

    config_path: str = Field(default="./mcp_servers.json", description="MCP 서버 설정 파일 경로")
    timeout: int = Field(default=30, gt=0, description="MCP 서버 타임아웃(초)")
    max_retries: int = Field(default=3, ge=0, description="최대 재시도 횟수")

    model_config = SettingsConfigDict(
        env_prefix="MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


class RedisSettings(BaseSettings):
    """세션 및 캐싱을 위한 Redis 설정."""

    host: str = Field(default="localhost", description="Redis 호스트")
    port: int = Field(default=6379, gt=0, lt=65536, description="Redis 포트")
    db: int = Field(default=0, ge=0, description="Redis 데이터베이스 번호")
    password: str = Field(default="", description="Redis 비밀번호 (선택사항)")
    session_ttl: int = Field(default=3600, gt=0, description="세션 TTL(초) (1시간)")
    max_connections: int = Field(default=10, gt=0, description="최대 Redis 연결 수")

    model_config = SettingsConfigDict(
        env_prefix="REDIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


class AuthSettings(BaseSettings):
    """인증 설정."""

    enabled: bool = Field(default=True, description="API 키 인증 활성화")
    api_key_header: str = Field(default="X-API-Key", description="API 키를 위한 헤더 이름")
    secret_key: str = Field(default="your-secret-key-change-in-production", description="토큰 생성을 위한 비밀 키")

    model_config = SettingsConfigDict(
        env_prefix="AUTH_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


class DatabaseSettings(BaseSettings):
    """데이터베이스 설정."""

    type: str = Field(default="mysql", description="데이터베이스 타입: 'mysql' 또는 'postgresql'")
    host: str = Field(default="localhost", description="데이터베이스 호스트")
    port: int = Field(default=3306, gt=0, lt=65536, description="데이터베이스 포트")
    user: str = Field(default="root", description="데이터베이스 사용자")
    password: str = Field(default="", description="데이터베이스 비밀번호")
    name: str = Field(default="claude_db", description="데이터베이스 이름")
    pool_size: int = Field(default=5, gt=0, description="연결 풀 크기")
    max_overflow: int = Field(default=10, ge=0, description="최대 오버플로우 연결 수")
    pool_recycle: int = Field(default=3600, gt=0, description="연결 재활용 시간(초)")

    model_config = SettingsConfigDict(
        env_prefix="DB_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


class Settings(BaseSettings):
    """
        메인 애플리케이션 설정 컨테이너.
        Python이 settings.py를 import할 때 하위 세팅 model_config 읽고 메타데이터 저장
        Settings() ← 이 시점에 실제 객체 생성, 메타데이터 기반 필드를 순회하면서 값 설정
    """

    # 하위 설정들
    llm: LLMSettings = Field(default_factory=LLMSettings)
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    openai: OpenAISettings = Field(default_factory=OpenAISettings)
    api: APISettings = Field(default_factory=APISettings)
    cors: CORSSettings = Field(default_factory=CORSSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    mcp: MCPSettings = Field(default_factory=MCPSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)

    # 기타 설정
    prompt_path: str = Field(default="./templates", description="HTML 템플릿 경로")

    # model_config : Pydantic에서 정의한 메타데이터 변수명, 클래스 정의 시점에 이미 읽힘
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


# 설정을 위한 싱글톤 패턴
_settings: Settings | None = None


def get_settings() -> Settings:
    """설정 인스턴스 가져오기 또는 생성 (싱글톤)."""
    global _settings
    if _settings is None:
        try:
            _settings = Settings()
        except Exception as e:
            raise RuntimeError(f"설정 로드 실패: {e}") from e
    return _settings


def reset_settings() -> None:
    """설정 싱글톤 재설정 (주로 테스트용)."""
    global _settings
    _settings = None
