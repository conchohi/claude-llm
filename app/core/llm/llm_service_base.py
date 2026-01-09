"""
기본 LLM 서비스 추상 클래스.
모든 LLM 제공자를 위한 공통 인터페이스를 정의합니다.
"""

from abc import ABC, abstractmethod
from typing import Dict, AsyncIterator, Optional
from pathlib import Path
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.language_models.chat_models import BaseChatModel

from app.utils.logger import get_logger

logger = get_logger(__name__)


class BaseLLMService(ABC):
    """
    LLM 서비스 구현을 위한 추상 기본 클래스.
    모든 제공자별 서비스는 이 클래스를 상속해야 합니다.
    """

    def __init__(
        self,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        prompt_path: Optional[str] = None,
    ):
        """
        기본 LLM 서비스를 초기화합니다.

        Args:
            model: LLM 모델 이름.
            temperature: 생성 온도 (0.0-2.0).
            max_tokens: 생성할 최대 토큰 수.
            prompt_path: 커스텀 프롬프트 템플릿 파일의 선택적 경로.
        """
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.llm: Optional[BaseChatModel] = None
        self.default_prompt_template = self._create_default_template(prompt_path)
        self._base_chain = None  # 성능을 위한 체인 캐싱

    @abstractmethod
    def initialize_llm(self, model: Optional[str] = None) -> BaseChatModel:
        """
        LLM을 초기화하거나 재초기화합니다.
        서브클래스에서 구현해야 합니다.

        Args:
            model: 선택적 모델 재정의.
            **kwargs: 추가 제공자별 매개변수.

        Returns:
            초기화된 LLM 인스턴스.
        """
        pass

    @abstractmethod
    async def test_connection(self) -> Dict:
        """
        LLM 제공자에 대한 연결을 테스트합니다.
        서브클래스에서 구현해야 합니다.

        Returns:
            연결 테스트 결과를 포함하는 딕셔너리.
        """
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """
        제공자 이름을 가져옵니다.
        서브클래스에서 구현해야 합니다.

        Returns:
            제공자 이름 문자열.
        """
        pass

    def _create_default_template(self, prompt_path: Optional[str]) -> ChatPromptTemplate:
        """
        MCP 컨텍스트를 포함한 쿼리를 위한 기본 프롬프트 템플릿을 생성합니다.
        prompt_path가 제공되면 파일에서 템플릿을 로드하고, 그렇지 않으면 기본값을 사용합니다.

        Returns:
            ChatPromptTemplate 인스턴스.
        """
        # 대체용 기본 템플릿
        default_template = """You are a helpful AI assistant with access to various context sources.

{context_section}

User Query: {query}

Please provide a comprehensive and accurate answer based on the available context. If the context doesn't contain relevant information, say so and provide the best answer you can based on your knowledge."""

        # 경로가 제공되면 파일에서 로드 시도
        if prompt_path:
            prompt_template_file = Path(prompt_path)
            if prompt_template_file.exists():
                try:
                    template = prompt_template_file.read_text(encoding='utf-8')
                    logger.info(f"Loaded prompt template from: {prompt_path}")
                    return ChatPromptTemplate.from_template(template)
                except Exception as e:
                    logger.error(f"Failed to load template from {prompt_path}: {e}")
                    logger.info("Using default template instead")
            else:
                logger.warning(f"Template file not found: {prompt_path}")
                logger.info("Using default template instead")

        return ChatPromptTemplate.from_template(default_template)

    def _format_mcp_context(self, mcp_context: Dict) -> str:
        """
        MCP 컨텍스트 딕셔너리를 프롬프트용 읽기 가능한 문자열로 포맷팅합니다.

        Args:
            mcp_context: MCP 서버 응답의 딕셔너리.

        Returns:
            포맷된 컨텍스트 문자열.
        """
        if not mcp_context:
            return "No additional context available."

        context_parts = []
        context_parts.append("Available Context:")

        # _agent_summary 처리 (MCPResponse 객체를 문자열로 변환)
        agent_summary_response = mcp_context.get("_agent_summary")
        if agent_summary_response and hasattr(agent_summary_response, 'data'):
            agent_summary = agent_summary_response.data.get("summary", "No agent summary available.")
            context_parts.append(agent_summary)
        else:
            context_parts.append("No agent summary available.")
        for server_name, response in mcp_context.items():
            if server_name == "_agent_summary":
                continue

            if response.success:
                if isinstance(response.data, dict):
                    tool_names = ""
                    for tool in response.data.get("tools_executed", []):
                        tool_names += f"{tool.get('tool_name', 'unknown tool')},"
                    tool_names = tool_names.rstrip(",")
                    context_parts.append(f"\n--- From {server_name} : {tool_names}")
                else:
                    context_parts.append(f"\n--- From {server_name} ---")
            elif not response.success and response.error:
                context_parts.append(f"\n--- {server_name} (unavailable) ---")
                context_parts.append(f"Error: {response.error}")

        return "\n".join(context_parts)

    def _build_chain(self):
        """
        LangChain 처리 체인을 빌드하거나 캐시된 체인을 검색합니다.
        체인은 성능을 위해 캐시되며 LLM이 변경될 때만 재빌드됩니다.

        Returns:
            쿼리 처리를 위한 LangChain LCEL 체인.
        """
        if self._base_chain is None or self.llm is None:
            if self.llm is None:
                raise RuntimeError("LLM must be initialized before building chain")

            self._base_chain = (
                {
                    "context_section": lambda x: x.get("context_section", ""),
                    "query": lambda x: x.get("query", ""),
                }
                | self.default_prompt_template
                | self.llm
                | StrOutputParser()
            )
            logger.info("Built new LangChain processing chain")

        return self._base_chain

    def _invalidate_chain_cache(self):
        """
        캐시된 체인을 무효화합니다.
        LLM이 다른 매개변수로 재초기화될 때 호출되어야 합니다.
        """
        self._base_chain = None
        logger.debug("Chain cache invalidated")

    async def generate_response(
        self,
        query: str,
        mcp_context: Optional[Dict] = None,
        model: Optional[str] = None,
        **kwargs
    ) -> Dict:
        """
        선택적 MCP 컨텍스트와 함께 사용자 쿼리에 대한 응답을 생성합니다.

        Args:
            query: 사용자 쿼리 문자열.
            mcp_context: MCP 서버 응답의 선택적 딕셔너리.
            model: 선택적 모델 재정의.
            **kwargs: 추가 생성 매개변수.

        Returns:
            응답 및 메타데이터를 포함하는 딕셔너리.
        """
        # 필요하거나 모델이 변경된 경우 LLM 초기화
        if self.llm is None or (model and model != self.model):
            self.initialize_llm(model, **kwargs)
            self._invalidate_chain_cache()  # LLM 변경 시 캐시 무효화

        # MCP 컨텍스트 포맷팅
        context_section = self._format_mcp_context(mcp_context) if mcp_context else "No additional context available."

        # 캐시된 체인 가져오기
        chain = self._build_chain()

        # 컨텍스트와 쿼리로 체인 호출
        try:
            response = await chain.ainvoke({
                "context_section": context_section,
                "query": query
            })

            logger.info(f"Successfully generated response for query")

            return {
                "response": response,
                "model": model or self.model,
                "success": True,
            }

        except Exception as e:
            logger.error(f"Failed to generate response: {e}")
            return {
                "response": "",
                "model": model or self.model,
                "success": False,
                "error": str(e),
            }

    async def generate_streaming_response(
        self,
        query: str,
        mcp_context: Optional[Dict] = None,
        model: Optional[str] = None,
        **kwargs
    ) -> AsyncIterator[str]:
        """
        사용자 쿼리에 대한 스트리밍 응답을 생성합니다.

        Args:
            query: 사용자 쿼리 문자열.
            mcp_context: MCP 서버 응답의 선택적 딕셔너리.
            model: 선택적 모델 재정의.
            **kwargs: 추가 생성 매개변수.

        Yields:
            생성되는 응답 토큰.
        """
        # 필요하거나 모델이 변경된 경우 LLM 초기화
        if self.llm is None or (model and model != self.model):
            self.initialize_llm(model, **kwargs)
            self._invalidate_chain_cache()  # LLM 변경 시 캐시 무효화

        # MCP 컨텍스트 포맷팅
        context_section = self._format_mcp_context(mcp_context) if mcp_context else "No additional context available."
        
        logger.info(f"Starting streaming response for query")
        logger.info(f"Context Section: {context_section}")
        logger.info(f"Query: {query}")
        
        # 캐시된 체인 가져오기
        chain = self._build_chain()

        # 응답 스트리밍
        try:
            async for chunk in chain.astream({
                "context_section": context_section,
                "query": query
            }):
                yield chunk
        except Exception as e:
            logger.error(f"Streaming response failed: {e}")
            yield f"Error: {str(e)}"

    def create_custom_prompt(self, template: str) -> ChatPromptTemplate:
        """
        커스텀 프롬프트 템플릿을 생성합니다.

        Args:
            template: {context_section} 및 {query} 플레이스홀더가 있는 커스텀 템플릿 문자열.

        Returns:
            ChatPromptTemplate 인스턴스.
        """
        return ChatPromptTemplate.from_template(template)
