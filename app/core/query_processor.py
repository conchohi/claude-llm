"""
Query processor - orchestrates MCP context gathering and LangChain response generation.
"""

import time
import uuid
from typing import Dict, List, Optional, AsyncIterator

from app.core.mcp_client import MCPClientManager
from app.core.llm_service_base import BaseLLMService
from app.core.session_manager import SessionManager
from app.models.mcp_server import MCPResponse

MAX_CONVERSATION_HISTORY_MESSAGES = 10
MCP_CONTEXT_PREVIEW_LENGTH = 200

class QueryProcessor:
    """
    Main orchestrator for processing user queries.
    Coordinates MCP context gathering and LangChain response generation.
    """

    def __init__(
        self,
        mcp_client: MCPClientManager,
        llm_service: BaseLLMService,
        session_manager: Optional[SessionManager] = None,
    ):
        """
        Initialize the query processor.

        Args:
            mcp_client: MCP client manager instance.
            llm_service: LLM service instance (Ollama or OpenAI).
            session_manager: Optional session manager for conversation history.
        """
        self.mcp_client = mcp_client
        self.llm_service = llm_service
        self.session_manager = session_manager

    async def process_query(
        self,
        query: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        use_conversation_history: bool = True,
        mcp_servers: Optional[List[str]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict:
        """
        Process a user query with MCP context and generate response.

        Args:
            query: User query string.
            user_id: User ID for session management.
            session_id: Optional session ID. If None and user_id provided, creates new session.
            use_conversation_history: Whether to include conversation history in context.
            mcp_servers: Optional list of MCP server names to query. If None, uses all enabled servers.
            model: Optional Ollama model override.
            temperature: Optional temperature override.
            max_tokens: Optional max tokens override.

        Returns:
            Dictionary containing response, MCP context, session_id, and metadata.
        """
        start_time = time.time()

        # Step 0: Session and profile management
        session = None
        user_profile = None
        conversation_history = ""

        if self.session_manager and user_id:
            # Get or create session
            if session_id:
                session = await self.session_manager.get_session(session_id)
                if not session or session.user_id != user_id:
                    # Invalid session, create new one
                    session = await self.session_manager.create_session(user_id)
            else:
                # Create new session
                session = await self.session_manager.create_session(user_id)

            # Get user profile for defaults
            user_profile = await self.session_manager.get_user_profile(user_id)

            # Build conversation history if enabled
            if use_conversation_history and session and session.messages:
                history_parts = []
                for msg in session.messages[-MAX_CONVERSATION_HISTORY_MESSAGES:]:  # Last 10 messages for context
                    role_label = "User" if msg.role == "user" else "Assistant"
                    history_parts.append(f"{role_label}: {msg.content}")
                conversation_history = "\n".join(history_parts)

            # Apply user profile defaults if not explicitly provided
            if user_profile:
                if model is None:
                    model = user_profile.default_model
                if temperature is None:
                    temperature = user_profile.default_temperature
                if max_tokens is None:
                    max_tokens = user_profile.default_max_tokens
                if mcp_servers is None and user_profile.preferred_mcp_servers:
                    mcp_servers = user_profile.preferred_mcp_servers

        # Step 1: Gather MCP context with caching
        mcp_context = {}
        if mcp_servers:
            mcp_context = await self._gather_mcp_context(mcp_servers, query, use_cache=True)
        else:
            # Use all enabled servers
            enabled_servers = [
                name for name, status in self.mcp_client.get_all_statuses().items()
                if status.enabled and status.running
            ]
            if enabled_servers:
                mcp_context = await self._gather_mcp_context(enabled_servers, query, use_cache=True)

        # Step 2: Generate LLM response with context and conversation history
        llm_kwargs = {}
        if temperature is not None:
            llm_kwargs["temperature"] = temperature
        if max_tokens is not None:
            llm_kwargs["max_tokens"] = max_tokens

        # Include conversation history in the query context
        enhanced_query = query
        if conversation_history:
            enhanced_query = f"Conversation History:\n{conversation_history}\n\nCurrent Query: {query}"

        llm_response = await self.llm_service.generate_response(
            query=enhanced_query,
            mcp_context=mcp_context,
            model=model,
            **llm_kwargs
        )

        # Step 3: Save to session if enabled
        if session and self.session_manager:
            # Add user message
            session.add_message(role="user", content=query)

            # Add assistant response with MCP context
            mcp_context_summary = {
                name: {"success": resp.success, "data_preview": str(resp.data)[:200]}
                for name, resp in mcp_context.items()
            }
            session.add_message(
                role="assistant",
                content=llm_response.get("response", ""),
                mcp_context=mcp_context_summary,
            )

            # Save session to Redis
            await self.session_manager.save_session(session)

        # Step 4: Calculate metadata
        processing_time = time.time() - start_time

        result = {
            "response": llm_response.get("response", ""),
            "model": llm_response.get("model", model or self.llm_service.model),
            "mcp_context": self._format_mcp_context_for_response(mcp_context),
            "metadata": {
                "processing_time": round(processing_time, 3),
                "mcp_servers_queried": list(mcp_context.keys()) if mcp_context else [],
                "mcp_servers_successful": [
                    name for name, resp in mcp_context.items() if resp.success
                ] if mcp_context else [],
                "success": llm_response.get("success", True),
                "conversation_history_used": bool(conversation_history),
            },
            "success": llm_response.get("success", True),
            "error": llm_response.get("error") if not llm_response.get("success", True) else None,
        }

        # Include session_id in response if session exists
        if session:
            result["session_id"] = session.session_id

        return result

    async def process_streaming_query(
        self,
        query: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        use_conversation_history: bool = True,
        mcp_servers: Optional[List[str]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """
        Process a user query with streaming response.

        Args:
            query: User query string.
            user_id: User ID for session management.
            session_id: Optional session ID.
            use_conversation_history: Whether to include conversation history.
            mcp_servers: Optional list of MCP server names to query.
            model: Optional Ollama model override.
            temperature: Optional temperature override.
            max_tokens: Optional max tokens override.

        Yields:
            Response chunks as they are generated.
        """
        # Step 0: Session and profile management
        session = None
        user_profile = None
        conversation_history = ""

        if self.session_manager and user_id:
            # Get or create session
            if session_id:
                session = await self.session_manager.get_session(session_id)
                if not session or session.user_id != user_id:
                    session = await self.session_manager.create_session(user_id)
            else:
                session = await self.session_manager.create_session(user_id)

            # Get user profile for defaults
            user_profile = await self.session_manager.get_user_profile(user_id)

            # Build conversation history
            if use_conversation_history and session and session.messages:
                history_parts = []
                for msg in session.messages[-10:]:
                    role_label = "User" if msg.role == "user" else "Assistant"
                    history_parts.append(f"{role_label}: {msg.content}")
                conversation_history = "\n".join(history_parts)

            # Apply user profile defaults
            if user_profile:
                if model is None:
                    model = user_profile.default_model
                if temperature is None:
                    temperature = user_profile.default_temperature
                if max_tokens is None:
                    max_tokens = user_profile.default_max_tokens
                if mcp_servers is None and user_profile.preferred_mcp_servers:
                    mcp_servers = user_profile.preferred_mcp_servers

        # Step 1: Gather MCP context with caching
        mcp_context = {}
        if mcp_servers:
            mcp_context = await self._gather_mcp_context(mcp_servers, query, use_cache=True)
        else:
            # Use all enabled servers
            enabled_servers = [
                name for name, status in self.mcp_client.get_all_statuses().items()
                if status.enabled and status.running
            ]
            if enabled_servers:
                mcp_context = await self._gather_mcp_context(enabled_servers, query, use_cache=True)

        # Step 2: Stream LLM response with context and history
        llm_kwargs = {}
        if temperature is not None:
            llm_kwargs["temperature"] = temperature
        if max_tokens is not None:
            llm_kwargs["max_tokens"] = max_tokens

        # Include conversation history in the query context
        enhanced_query = query
        if conversation_history:
            enhanced_query = f"Conversation History:\n{conversation_history}\n\nCurrent Query: {query}"

        # Collect full response for session storage
        full_response = ""

        async for chunk in self.llm_service.generate_streaming_response(
            query=enhanced_query,
            mcp_context=mcp_context,
            model=model,
            **llm_kwargs
        ):
            full_response += chunk
            yield chunk

        # Step 3: Save to session after streaming completes
        if session and self.session_manager:
            session.add_message(role="user", content=query)

            mcp_context_summary = {
                name: {"success": resp.success, "data_preview": str(resp.data)[:MCP_CONTEXT_PREVIEW_LENGTH]}
                for name, resp in mcp_context.items()
            }
            session.add_message(
                role="assistant",
                content=full_response,
                mcp_context=mcp_context_summary,
            )

            await self.session_manager.save_session(session)

    async def _gather_mcp_context(
        self,
        server_names: List[str],
        query: str,
        use_cache: bool = False,
    ) -> Dict[str, MCPResponse]:
        """
        Gather context from specified MCP servers with optional caching.

        Args:
            server_names: List of MCP server names to query.
            query: Query string.
            use_cache: Whether to use MCP cache (if session manager available).

        Returns:
            Dictionary mapping server names to their responses.
        """
        if not use_cache or not self.session_manager:
            # No caching, query MCP servers directly
            return await self.mcp_client.get_context(server_names, query)

        # With caching enabled
        results = {}

        for server_name in server_names:
            # Generate cache key
            cache_key = self.session_manager.generate_mcp_cache_key(server_name, query)

            # Try to get from cache
            cached_data = await self.session_manager.get_mcp_cache(cache_key)

            if cached_data is not None:
                # Cache hit - reconstruct MCPResponse
                results[server_name] = MCPResponse(
                    success=cached_data.get("success", True),
                    data=cached_data.get("data"),
                    error=cached_data.get("error"),
                    latency_ms=0.0,  # Cache hit has no latency
                )
            else:
                # Cache miss - query MCP server
                server_results = await self.mcp_client.get_context([server_name], query)
                if server_name in server_results:
                    response = server_results[server_name]
                    results[server_name] = response

                    # Store in cache for successful responses
                    if response.success:
                        cache_data = {
                            "success": response.success,
                            "data": response.data,
                            "error": response.error,
                        }
                        await self.session_manager.set_mcp_cache(cache_key, cache_data)

        return results

    def _format_mcp_context_for_response(self, mcp_context: Dict[str, MCPResponse]) -> Dict:
        """
        Format MCP context for JSON response.

        Args:
            mcp_context: Raw MCP context dictionary.

        Returns:
            Formatted dictionary suitable for API response.
        """
        formatted = {}

        for server_name, response in mcp_context.items():
            formatted[server_name] = {
                "success": response.success,
                "data": response.data if response.success else None,
                "error": response.error if not response.success else None,
                "latency_ms": round(response.latency_ms, 2),
            }

        return formatted

    async def health_check(self) -> Dict:
        """
        Perform health check on the query processor and its dependencies.

        Returns:
            Health check status dictionary.
        """
        # Check LLM connection (Ollama or OpenAI)
        llm_status = await self.llm_service.test_connection()

        # Check MCP servers
        mcp_statuses = self.mcp_client.get_all_statuses()
        mcp_health = {
            name: {
                "enabled": status.enabled,
                "running": status.running,
                "healthy": status.healthy,
                "type": status.type,
                "error": status.error,
            }
            for name, status in mcp_statuses.items()
        }

        # Overall health
        all_healthy = (
            llm_status["success"]
            and any(status.healthy for status in mcp_statuses.values() if status.enabled)
        )

        return {
            "healthy": all_healthy,
            "llm": llm_status,
            "mcp_servers": mcp_health,
        }
