"""
Factory for creating LLM service instances based on provider.
"""

from typing import Optional
from config.settings import Settings
from app.core.llm_service_base import BaseLLMService
from app.core.llm_service_ollama import OllamaLLMService
from app.core.llm_service_openai import OpenAILLMService
from app.utils.logger import get_logger

logger = get_logger(__name__)


def create_llm_service(settings: Settings) -> BaseLLMService:
    """
    Create an LLM service instance based on the configured provider.

    Args:
        settings: Application settings containing LLM configuration.

    Returns:
        Initialized LLM service instance (OllamaLLMService or OpenAILLMService).

    Raises:
        ValueError: If provider is not supported.
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
