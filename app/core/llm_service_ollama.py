"""
Ollama-specific LLM service implementation.
"""

from typing import Dict, Optional
from langchain_ollama import ChatOllama
from langchain_core.language_models.chat_models import BaseChatModel

from app.core.llm_service_base import BaseLLMService
from app.utils.logger import get_logger

logger = get_logger(__name__)


class OllamaLLMService(BaseLLMService):
    """
    Ollama-specific LLM service implementation.
    """

    def __init__(
        self,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        prompt_path: Optional[str] = None,
        base_url: str = "http://localhost:11434",
        keep_alive: str = "5m",
    ):
        """
        Initialize the Ollama LLM service.

        Args:
            model: Ollama model name.
            temperature: Generation temperature (0.0-2.0).
            max_tokens: Maximum tokens to generate.
            prompt_path: Optional path to custom prompt template file.
            base_url: Ollama API base URL.
            keep_alive: Keep model loaded in memory duration.
        """
        super().__init__(model, temperature, max_tokens, prompt_path)
        self.base_url = base_url
        self.keep_alive = keep_alive

    def initialize_llm(self, model: Optional[str] = None, **kwargs) -> BaseChatModel:
        """
        Initialize or reinitialize the Ollama LLM.

        Args:
            model: Optional model override.
            **kwargs: Additional parameters (temperature, max_tokens).

        Returns:
            Initialized ChatOllama instance.
        """
        model_name = model or self.model

        logger.info(f"Initializing Ollama LLM with model: {model_name}")

        self.llm = ChatOllama(
            base_url=self.base_url,
            model=model_name,
            temperature=kwargs.get("temperature", self.temperature),
            num_predict=kwargs.get("max_tokens", self.max_tokens),
            keep_alive=self.keep_alive,
        )

        return self.llm

    async def test_connection(self) -> Dict:
        """
        Test connection to Ollama server.

        Returns:
            Dictionary with connection test results.
        """
        try:
            if self.llm is None:
                self.initialize_llm()

            # Try a simple invocation
            response = await self.llm.ainvoke("Hello")

            logger.info(f"Ollama connection test successful")

            return {
                "success": True,
                "message": "Successfully connected to Ollama",
                "provider": "ollama",
                "model": self.model,
                "base_url": self.base_url,
                "test_response": str(response.content)[:100],  # First 100 chars
            }

        except Exception as e:
            logger.error(f"Ollama connection test failed: {e}")
            return {
                "success": False,
                "message": f"Failed to connect to Ollama: {str(e)}",
                "provider": "ollama",
                "model": self.model,
                "base_url": self.base_url,
            }

    def get_provider_name(self) -> str:
        """
        Get the provider name.

        Returns:
            "ollama"
        """
        return "ollama"
