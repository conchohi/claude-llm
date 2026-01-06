"""
MCP client manager using LangChain's MCP Adapters.
Provides high-level abstraction for MCP server communication.
"""

import asyncio
import time
from typing import Dict, List, Optional

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from app.models.mcp_server import MCPServerConfig, MCPServerStatus, MCPResponse
from app.utils.logger import get_logger
from config.settings import get_settings

logger = get_logger(__name__)


class MCPClientManager:
    """
    Manages MCP server connections using LangChain's MultiServerMCPClient.
    Simplifies MCP server lifecycle and provides unified query interface.
    """

    def __init__(self, timeout: int = 30, max_retries: int = 3):
        """
        Initialize the MCP client manager.

        Args:
            timeout: Timeout for server operations in seconds.
            max_retries: Maximum number of retry attempts for failed operations.
        """
        self.timeout = timeout
        self.max_retries = max_retries

        # LangChain MCP client
        self.mcp_client: Optional[MultiServerMCPClient] = None

        # Storage for configurations and status
        self._server_configs: Dict[str, MCPServerConfig] = {}
        self._server_status: Dict[str, MCPServerStatus] = {}

    async def initialize_servers(self, configs: List[MCPServerConfig]) -> None:
        """
        Initialize MCP servers from configurations using MultiServerMCPClient.

        Args:
            configs: List of MCP server configurations to initialize.
        """
        # Store configurations
        for config in configs:
            self._server_configs[config.name] = config
            self._server_status[config.name] = MCPServerStatus(
                name=config.name,
                enabled=config.enabled,
                type=config.type,
            )

        # Build server configuration for MultiServerMCPClient
        enabled_configs = [c for c in configs if c.enabled]

        if not enabled_configs:
            logger.info("No enabled MCP servers to initialize")
            return

        # Convert to LangChain MCP format
        mcp_servers = {}

        for config in enabled_configs:
            if config.is_process_based():
                # Process-based server configuration (stdio transport)
                mcp_servers[config.name] = {
                    "command": config.command,
                    "args": config.args or [],
                    "transport": "stdio",
                }
                # Add env if provided
                if config.env:
                    mcp_servers[config.name]["env"] = config.env

            elif config.is_http_based():
                # HTTP-based server configuration
                mcp_servers[config.name] = {
                    "url": config.url,
                    "transport": "http",
                }
                # Add headers if provided
                if config.headers:
                    mcp_servers[config.name]["headers"] = config.headers

        if not mcp_servers:
            logger.info("No MCP servers to initialize")
            return

        try:
            # Initialize MultiServerMCPClient
            self.mcp_client = MultiServerMCPClient(mcp_servers)

            # Update status for all configured servers
            for server_name in mcp_servers.keys():
                try:
                    is_healthy = await self.health_check(server_name)
                    self._server_status[server_name].running = True
                    self._server_status[server_name].healthy = is_healthy
                    self._server_status[server_name].error = None if is_healthy else "Health check failed"
                except Exception as server_error:
                    self._server_status[server_name].running = False
                    self._server_status[server_name].healthy = False
                    self._server_status[server_name].error = str(server_error)

            logger.info(f"✓ Initialized {len(mcp_servers)} MCP server(s) via MultiServerMCPClient")

        except Exception as e:
            error_msg = f"Failed to initialize MultiServerMCPClient: {e}"
            logger.error(f"✗ {error_msg}")

            # Mark all servers as failed
            for server_name in mcp_servers.keys():
                self._server_status[server_name].running = False
                self._server_status[server_name].healthy = False
                self._server_status[server_name].error = str(e)

    async def start_server(self, name: str) -> None:
        """
        Start a specific MCP server.

        Note: With MultiServerMCPClient, all servers are initialized together.
        This method validates server status.

        Args:
            name: Server name.

        Raises:
            ValueError: If server not found.
        """
        if name not in self._server_configs:
            raise ValueError(f"Server '{name}' not found in configuration")

        config = self._server_configs[name]

        if not config.enabled:
            self._server_status[name].running = False
            self._server_status[name].error = "Server is disabled in configuration"
            return

        # Check if MCP client is initialized
        if not self.mcp_client:
            raise RuntimeError("MultiServerMCPClient not initialized. Call initialize_servers() first.")

        # Server should already be started if enabled
        self._server_status[name].running = True
        self._server_status[name].healthy = True

    async def stop_server(self, name: str) -> None:
        """
        Stop a specific MCP server.

        Note: With MultiServerMCPClient, servers are managed collectively.

        Args:
            name: Server name.
        """
        if name in self._server_status:
            self._server_status[name].running = False
            self._server_status[name].healthy = False

    async def query_server(self, name: str, query: str, context: Optional[Dict] = None) -> MCPResponse:
        """
        Query a specific MCP server using LangChain tools.

        Args:
            name: Server name.
            query: Query string.
            context: Optional context dictionary.

        Returns:
            MCPResponse with query results.
        """
        config = self._server_configs.get(name)
        if not config:
            return MCPResponse(
                server_name=name,
                success=False,
                error=f"Server '{name}' not found",
            )

        if not config.enabled:
            return MCPResponse(
                server_name=name,
                success=False,
                error=f"Server '{name}' is not enabled",
            )

        if not self.mcp_client:
            return MCPResponse(
                server_name=name,
                success=False,
                error="MultiServerMCPClient not initialized",
            )

        start_time = time.time()

        try:
            # Get tools from specific server using session
            async with self.mcp_client.session(name) as session:
                from langchain_mcp_adapters import load_mcp_tools

                tools = await load_mcp_tools(session)

                if not tools:
                    return MCPResponse(
                        server_name=name,
                        success=False,
                        error=f"No tools available for server '{name}'",
                        latency_ms=(time.time() - start_time) * 1000,
                    )

                # Prepare query input with optional context
                query_input = query
                if context:
                    query_input = f"{query}\nAdditional context: {context}"

                # Variables to track execution
                result = None
                tool_name = None

                # Use LangChain Agent to automatically select and invoke the best tool
                if len(tools) > 1:
                    # Multiple tools: Use agent to select the best one
                    try:
                        # Create agent prompt
                        agent_prompt = ChatPromptTemplate.from_messages([
                            ("system", "You are a helpful assistant that uses available tools to answer queries. Use the most appropriate tool for the given query."),
                            ("human", "{input}"),
                            ("placeholder", "{agent_scratchpad}"),
                        ])

                        # Create LLM for tool selection (deterministic)
                        settings = get_settings()
                        llm = ChatOllama(
                            base_url=settings.ollama.base_url,
                            model=settings.ollama.model,
                            temperature=0.0,  # Override to 0 for deterministic tool selection
                        )

                        # Create and execute agent
                        agent = create_tool_calling_agent(llm, tools, agent_prompt)
                        agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=False)

                        agent_result = await agent_executor.ainvoke({"input": query_input})
                        result = agent_result.get("output", agent_result)

                        # Extract tool name from agent steps if available
                        if "intermediate_steps" in agent_result and agent_result["intermediate_steps"]:
                            tool_name = agent_result["intermediate_steps"][0][0].tool
                        else:
                            tool_name = "agent_selected"

                    except Exception as agent_error:
                        # Fallback to first tool if agent fails
                        logger.warning(f"Agent execution failed, using first tool as fallback: {agent_error}")
                        tool = tools[0]
                        tool_input = {"query": query}
                        if context:
                            tool_input.update(context)
                        result = await tool.ainvoke(tool_input)
                        tool_name = tool.name
                else:
                    # Single tool: Use it directly
                    tool = tools[0]
                    tool_input = {"query": query}
                    if context:
                        tool_input.update(context)
                    result = await tool.ainvoke(tool_input)
                    tool_name = tool.name

                latency_ms = (time.time() - start_time) * 1000

                return MCPResponse(
                    server_name=name,
                    success=True,
                    data={
                        "tool_name": tool_name,
                        "result": result,
                        "available_tools": [t.name for t in tools],
                    },
                    latency_ms=latency_ms,
                )

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return MCPResponse(
                server_name=name,
                success=False,
                error=f"Query failed: {str(e)}",
                latency_ms=latency_ms,
            )

    async def get_context(self, server_names: List[str], query: str) -> Dict[str, MCPResponse]:
        """
        Gather context from multiple MCP servers in parallel.

        Args:
            server_names: List of server names to query.
            query: Query string.

        Returns:
            Dictionary mapping server names to their responses.
        """
        tasks = [
            self.query_server(name, query)
            for name in server_names
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        context = {}
        for name, result in zip(server_names, results):
            if isinstance(result, Exception):
                context[name] = MCPResponse(
                    server_name=name,
                    success=False,
                    error=str(result),
                )
            else:
                context[name] = result

        return context

    async def get_all_tools(self) -> List:
        """
        Get all tools from all MCP servers.

        Returns:
            List of LangChain tools from all servers.
        """
        if not self.mcp_client:
            return []

        try:
            tools = await self.mcp_client.get_tools()
            return tools
        except Exception as e:
            logger.warning(f"Failed to get tools: {e}")
            return []

    async def health_check(self, name: str) -> bool:
        """
        Check if a server is healthy.

        Args:
            name: Server name.

        Returns:
            True if server is healthy, False otherwise.
        """
        status = self._server_status.get(name)
        if not status or not status.enabled:
            return False

        if not self.mcp_client:
            return False

        try:
            # Try to get tools from the server as a health check
            async with self.mcp_client.session(name) as session:
                from langchain_mcp_adapters import load_mcp_tools
                tools = await load_mcp_tools(session)
                return tools is not None and len(tools) > 0
        except:
            logger.warning(f"Health check failed for server '{name}'")
            return False

    def get_server_status(self, name: str) -> Optional[MCPServerStatus]:
        """Get status of a specific server."""
        return self._server_status.get(name)

    def get_all_statuses(self) -> Dict[str, MCPServerStatus]:
        """Get status of all servers."""
        return self._server_status.copy()

    async def get_available_tools(self, server_name: Optional[str] = None) -> List[str]:
        """
        Get list of available tool names.

        Args:
            server_name: Optional server name to filter tools. If None, returns all tools.

        Returns:
            List of tool names.
        """
        if not self.mcp_client:
            return []

        try:
            if server_name:
                # Get tools from specific server
                async with self.mcp_client.session(server_name) as session:
                    from langchain_mcp_adapters import load_mcp_tools
                    tools = await load_mcp_tools(session)
                    return [tool.name for tool in tools] if tools else []
            else:
                # Get all tools
                tools = await self.mcp_client.get_tools()
                return [tool.name for tool in tools] if tools else []
        except:
            return []

    async def shutdown(self) -> None:
        """Shutdown all MCP servers gracefully."""
        if self.mcp_client:
            # MultiServerMCPClient will handle cleanup when garbage collected
            # No explicit close method needed
            logger.info("✓ MultiServerMCPClient shut down successfully")
            self.mcp_client = None

        # Update all server statuses
        for name in self._server_status:
            self._server_status[name].running = False
            self._server_status[name].healthy = False
