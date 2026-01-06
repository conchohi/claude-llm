"""
Base LLM service abstract class.
Defines the common interface for all LLM providers.
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
    Abstract base class for LLM service implementations.
    All provider-specific services should inherit from this class.
    """

    def __init__(
        self,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        prompt_path: Optional[str] = None,
    ):
        """
        Initialize the base LLM service.

        Args:
            model: LLM model name.
            temperature: Generation temperature (0.0-2.0).
            max_tokens: Maximum tokens to generate.
            prompt_path: Optional path to custom prompt template file.
        """
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.llm: Optional[BaseChatModel] = None
        self.default_prompt_template = self._create_default_template(prompt_path)
        self._base_chain = None  # Chain caching for performance

    @abstractmethod
    def initialize_llm(self, model: Optional[str] = None, **kwargs) -> BaseChatModel:
        """
        Initialize or reinitialize the LLM.
        Must be implemented by subclasses.

        Args:
            model: Optional model override.
            **kwargs: Additional provider-specific parameters.

        Returns:
            Initialized LLM instance.
        """
        pass

    @abstractmethod
    async def test_connection(self) -> Dict:
        """
        Test connection to the LLM provider.
        Must be implemented by subclasses.

        Returns:
            Dictionary with connection test results.
        """
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """
        Get the provider name.
        Must be implemented by subclasses.

        Returns:
            Provider name string.
        """
        pass

    def _create_default_template(self, prompt_path: Optional[str]) -> ChatPromptTemplate:
        """
        Create the default prompt template for queries with MCP context.
        Loads template from file if prompt_path is provided, otherwise uses default.

        Returns:
            ChatPromptTemplate instance.
        """
        # Default template as fallback
        default_template = """You are a helpful AI assistant with access to various context sources.

{context_section}

User Query: {query}

Please provide a comprehensive and accurate answer based on the available context. If the context doesn't contain relevant information, say so and provide the best answer you can based on your knowledge."""

        # Try to load from file if path is provided
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
        Format MCP context dictionary into a readable string for the prompt.

        Args:
            mcp_context: Dictionary of MCP server responses.

        Returns:
            Formatted context string.
        """
        if not mcp_context:
            return "No additional context available."

        context_parts = []
        context_parts.append("Available Context:")

        for server_name, response in mcp_context.items():
            if response.success and response.data:
                context_parts.append(f"\n--- From {server_name} ---")
                # Format the data based on its structure
                if isinstance(response.data, dict):
                    for key, value in response.data.items():
                        context_parts.append(f"{key}: {value}")
                else:
                    context_parts.append(str(response.data))
            elif not response.success:
                context_parts.append(f"\n--- {server_name} (unavailable) ---")
                context_parts.append(f"Error: {response.error}")

        return "\n".join(context_parts)

    def _build_chain(self):
        """
        Build or retrieve cached LangChain processing chain.
        Chain is cached for performance and only rebuilt when LLM changes.

        Returns:
            LangChain LCEL chain for processing queries.
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
        Invalidate the cached chain.
        Should be called when LLM is reinitialized with different parameters.
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
        Generate a response to the user query with optional MCP context.

        Args:
            query: User query string.
            mcp_context: Optional dictionary of MCP server responses.
            model: Optional model override.
            **kwargs: Additional generation parameters.

        Returns:
            Dictionary containing response and metadata.
        """
        # Initialize LLM if needed or if model changed
        if self.llm is None or (model and model != self.model):
            self.initialize_llm(model, **kwargs)
            self._invalidate_chain_cache()  # Invalidate cache when LLM changes

        # Format MCP context
        context_section = self._format_mcp_context(mcp_context) if mcp_context else "No additional context available."

        # Get cached chain
        chain = self._build_chain()

        # Invoke the chain with context and query
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
        Generate a streaming response to the user query.

        Args:
            query: User query string.
            mcp_context: Optional dictionary of MCP server responses.
            model: Optional model override.
            **kwargs: Additional generation parameters.

        Yields:
            Response tokens as they are generated.
        """
        # Initialize LLM if needed or if model changed
        if self.llm is None or (model and model != self.model):
            self.initialize_llm(model, **kwargs)
            self._invalidate_chain_cache()  # Invalidate cache when LLM changes

        # Format MCP context
        context_section = self._format_mcp_context(mcp_context) if mcp_context else "No additional context available."

        # Get cached chain
        chain = self._build_chain()

        # Stream the response
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
        Create a custom prompt template.

        Args:
            template: Custom template string with {context_section} and {query} placeholders.

        Returns:
            ChatPromptTemplate instance.
        """
        return ChatPromptTemplate.from_template(template)
