"""
OpenAI 전용 LLM 서비스 구현.
"""

from typing import Dict, Optional
from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel

from app.core.llm.llm_service_base import BaseLLMService
from app.utils.logger import get_logger

logger = get_logger(__name__)


class OpenAILLMService(BaseLLMService):
    """
    OpenAI 전용 LLM 서비스 구현.
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
        OpenAI LLM 서비스를 초기화합니다.

        Args:
            model: OpenAI 모델 이름.
            temperature: 생성 온도 (0.0-2.0).
            max_tokens: 생성할 최대 토큰 수.
            prompt_path: 커스텀 프롬프트 템플릿 파일의 선택적 경로.
            api_key: OpenAI API 키 (Bearer 토큰).
            base_url: OpenAI API 기본 URL.
            organization: OpenAI 조직 ID (선택 사항).
            top_p: 핵 샘플링 확률 (0.0-1.0).
            frequency_penalty: 토큰 반복에 대한 페널티 (-2.0 ~ 2.0).
        """
        super().__init__(model, temperature, max_tokens, prompt_path)
        self.api_key = api_key
        self.base_url = base_url
        self.organization = organization
        self.top_p = top_p
        self.frequency_penalty = frequency_penalty

    def initialize_llm(self, model: Optional[str] = None) -> BaseChatModel:
        """
        OpenAI LLM을 초기화하거나 재초기화합니다.

        Args:
            model: 선택적 모델 재정의.

        Returns:
            초기화된 ChatOpenAI 인스턴스.

        Raises:
            ValueError: API 키가 제공되지 않은 경우.
        """
        model_name = model or self.model

        logger.info(f"Initializing OpenAI LLM with model: {model_name}")

        if not self.api_key:
            raise ValueError("OpenAI API key is required when provider is 'openai'")

        openai_kwargs = {
            "model": model_name,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "frequency_penalty": self.frequency_penalty,
            "api_key": self.api_key,
            "base_url": self.base_url,
        }

        if self.organization:
            openai_kwargs["organization"] = self.organization

        self.llm = ChatOpenAI(**openai_kwargs)

        return self.llm

    async def test_connection(self) -> Dict:
        """
        OpenAI 서버에 대한 연결을 테스트합니다.

        Returns:
            연결 테스트 결과를 포함하는 딕셔너리.
        """
        try:
            if self.llm is None:
                self.initialize_llm()

            # 간단한 호출 시도
            response = await self.llm.ainvoke("Hello")

            logger.info(f"OpenAI connection test successful")

            return {
                "success": True,
                "message": "Successfully connected to OpenAI",
                "provider": "openai",
                "model": self.model,
                "base_url": self.base_url,
                "test_response": str(response.content)[:100],  # 처음 100자
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
        제공자 이름을 가져옵니다.

        Returns:
            "openai"
        """
        return "openai"
