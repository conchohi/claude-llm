"""
LangChain service for Ollama LLM integration.
Handles LLM initialization, prompt management, and response generation.
"""

from typing import Dict, AsyncIterator, Optional
from pathlib import Path
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

from app.utils.logger import get_logger

logger = get_logger(__name__)


class LangChainService:
    """
    Service for managing LangChain and Ollama integration.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        prompt_path: Optional[str] = None,
    ):
        """
        Initialize the LangChain service.

        Args:
            base_url: Ollama API base URL.
            model: Ollama model name.
            temperature: Generation temperature (0.0-2.0).
            max_tokens: Maximum tokens to generate.
            template_path: Optional path to custom prompt template file.
        """
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.llm: Optional[ChatOllama] = None
        self.default_prompt_template = self._create_default_template(prompt_path)

    def initialize_llm(self, model: Optional[str] = None, **kwargs) -> ChatOllama:
        """
        Initialize or reinitialize the Ollama LLM.

        Args:
            model: Optional model override.
            **kwargs: Additional ChatOllama parameters.

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
        )

        return self.llm

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

        # Format MCP context
        context_section = self._format_mcp_context(mcp_context) if mcp_context else "No additional context available."

        # Create the chain
        chain = (
            {
                "context_section": lambda x: context_section,
                "query": RunnablePassthrough(),
            }
            | self.default_prompt_template
            | self.llm
            | StrOutputParser()
        )

        # Invoke the chain
        try:
            response = await chain.ainvoke(query)

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

        # Format MCP context
        context_section = self._format_mcp_context(mcp_context) if mcp_context else "No additional context available."

        # Create the chain
        chain = (
            {
                "context_section": lambda x: context_section,
                "query": RunnablePassthrough(),
            }
            | self.default_prompt_template
            | self.llm
            | StrOutputParser()
        )

        # Stream the response
        try:
            async for chunk in chain.astream(query):
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

    async def test_ollama_connection(self) -> Dict:
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
                "model": self.model,
                "base_url": self.base_url,
                "test_response": str(response.content)[:100],  # First 100 chars
            }

        except Exception as e:
            logger.error(f"Ollama connection test failed: {e}")
            return {
                "success": False,
                "message": f"Failed to connect to Ollama: {str(e)}",
                "model": self.model,
                "base_url": self.base_url,
            }
