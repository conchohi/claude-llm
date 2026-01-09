"""
Ollama 전용 LLM 서비스 구현.
"""

from typing import Dict, Optional
from langchain_ollama import ChatOllama
from langchain_core.language_models.chat_models import BaseChatModel

from app.core.llm.llm_service_base import BaseLLMService
from app.utils.logger import get_logger

logger = get_logger(__name__)


class OllamaLLMService(BaseLLMService):
    """
    Ollama 전용 LLM 서비스 구현.
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
        Ollama LLM 서비스를 초기화합니다.

        Args:
            model: Ollama 모델 이름.
            temperature: 생성 온도 (0.0-2.0).
            max_tokens: 생성할 최대 토큰 수.
            prompt_path: 커스텀 프롬프트 템플릿 파일의 선택적 경로.
            base_url: Ollama API 기본 URL.
            keep_alive: 메모리에 모델을 로드해 둘 시간.
        """
        super().__init__(model, temperature, max_tokens, prompt_path)
        self.base_url = base_url
        self.keep_alive = keep_alive

    def initialize_llm(self, model: Optional[str] = None) -> BaseChatModel:
        """
        Ollama LLM을 초기화하거나 재초기화합니다.

        Args:
            model: 선택적 모델 재정의.

        Returns:
            초기화된 ChatOllama 인스턴스.
        """
        model_name = model or self.model

        logger.info(f"Initializing Ollama LLM with model: {model_name}")

        self.llm = ChatOllama(
            base_url=self.base_url,
            model=model_name,
            temperature=self.temperature,
            num_predict=self.max_tokens,
            keep_alive=self.keep_alive,
        )

        return self.llm

    async def test_connection(self) -> Dict:
        """
        Ollama 서버에 대한 연결을 테스트합니다.

        Returns:
            연결 테스트 결과를 포함하는 딕셔너리.
        """
        try:
            if self.llm is None:
                self.initialize_llm()

            # 간단한 호출 시도
            response = await self.llm.ainvoke("Hello")

            logger.info(f"Ollama connection test successful")

            return {
                "success": True,
                "message": "Successfully connected to Ollama",
                "provider": "ollama",
                "model": self.model,
                "base_url": self.base_url,
                "test_response": str(response.content)[:100],  # 처음 100자
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
        제공자 이름을 가져옵니다.

        Returns:
            "ollama"
        """
        return "ollama"
