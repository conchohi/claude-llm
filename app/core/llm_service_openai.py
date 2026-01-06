"""
OpenAI-specific LLM service implementation.
"""

from typing import Dict, Optional
from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel

from app.core.llm_service_base import BaseLLMService
from app.utils.logger import get_logger

logger = get_logger(__name__)


class OpenAILLMService(BaseLLMService):
    """
    OpenAI-specific LLM service implementation.
    """

    def __init__(
        self,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        prompt_path: Optional[str] = None,
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        organization: Optional[str] = None,
        top_p: float = 1.0,
        frequency_penalty: float = 0.0,
    ):
        """
        Initialize the OpenAI LLM service.

        Args:
            model: OpenAI model name.
            temperature: Generation temperature (0.0-2.0).
            max_tokens: Maximum tokens to generate.
            prompt_path: Optional path to custom prompt template file.
            api_key: OpenAI API key (Bearer token).
            base_url: OpenAI API base URL.
            organization: OpenAI organization ID (optional).
            top_p: Nucleus sampling probability (0.0-1.0).
            frequency_penalty: Penalize token repetition (-2.0 to 2.0).
        """
        super().__init__(model, temperature, max_tokens, prompt_path)
        self.api_key = api_key
        self.base_url = base_url
        self.organization = organization
        self.top_p = top_p
        self.frequency_penalty = frequency_penalty

    def initialize_llm(self, model: Optional[str] = None, **kwargs) -> BaseChatModel:
        """
        Initialize or reinitialize the OpenAI LLM.

        Args:
            model: Optional model override.
            **kwargs: Additional parameters (temperature, max_tokens, top_p, frequency_penalty).

        Returns:
            Initialized ChatOpenAI instance.

        Raises:
            ValueError: If API key is not provided.
        """
        model_name = model or self.model

        logger.info(f"Initializing OpenAI LLM with model: {model_name}")

        if not self.api_key:
            raise ValueError("OpenAI API key is required when provider is 'openai'")

        openai_kwargs = {
            "model": model_name,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "top_p": kwargs.get("top_p", self.top_p),
            "frequency_penalty": kwargs.get("frequency_penalty", self.frequency_penalty),
            "api_key": self.api_key,
            "base_url": self.base_url,
        }

        if self.organization:
            openai_kwargs["organization"] = self.organization

        self.llm = ChatOpenAI(**openai_kwargs)

        return self.llm

    async def test_connection(self) -> Dict:
        """
        Test connection to OpenAI server.

        Returns:
            Dictionary with connection test results.
        """
        try:
            if self.llm is None:
                self.initialize_llm()

            # Try a simple invocation
            response = await self.llm.ainvoke("Hello")

            logger.info(f"OpenAI connection test successful")

            return {
                "success": True,
                "message": "Successfully connected to OpenAI",
                "provider": "openai",
                "model": self.model,
                "base_url": self.base_url,
                "test_response": str(response.content)[:100],  # First 100 chars
            }

        except Exception as e:
            logger.error(f"OpenAI connection test failed: {e}")
            return {
                "success": False,
                "message": f"Failed to connect to OpenAI: {str(e)}",
                "provider": "openai",
                "model": self.model,
                "base_url": self.base_url,
            }

    def get_provider_name(self) -> str:
        """
        Get the provider name.

        Returns:
            "openai"
        """
        return "openai"
