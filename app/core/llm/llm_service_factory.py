"""
제공자 기반 LLM 서비스 인스턴스를 생성하는 팩토리.
"""

from typing import Optional
from config.settings import Settings
from app.core.llm.llm_service_base import BaseLLMService
from app.core.llm.llm_service_ollama import OllamaLLMService
from app.core.llm.llm_service_openai import OpenAILLMService
from app.utils.logger import get_logger

logger = get_logger(__name__)


def create_llm_service(settings: Settings) -> BaseLLMService:
    """
    설정된 제공자를 기반으로 LLM 서비스 인스턴스를 생성합니다.

    Args:
        settings: LLM 설정을 포함하는 애플리케이션 설정.

    Returns:
        초기화된 LLM 서비스 인스턴스 (OllamaLLMService 또는 OpenAILLMService).

    Raises:
        ValueError: 제공자가 지원되지 않는 경우.
    """
    provider = settings.llm.provider.lower()

    logger.info(f"Creating LLM service for provider: {provider}")

    if provider == "ollama":
        return OllamaLLMService(
            model=settings.llm.model,
            temperature=settings.llm.temperature,
            max_tokens=settings.llm.max_tokens,
            prompt_path=settings.prompt_path,
            base_url=settings.ollama.base_url,
            keep_alive=settings.ollama.keep_alive,
        )

    elif provider == "openai":
        return OpenAILLMService(
            model=settings.llm.model,
            temperature=settings.llm.temperature,
            max_tokens=settings.llm.max_tokens,
            prompt_path=settings.prompt_path,
            api_key=settings.openai.api_key,
            base_url=settings.openai.base_url,
            organization=settings.openai.organization,
            top_p=settings.openai.top_p,
            frequency_penalty=settings.openai.frequency_penalty,
        )

    else:
        raise ValueError(
            f"Unsupported LLM provider: {provider}. "
            f"Supported providers: 'ollama', 'openai'"
        )
