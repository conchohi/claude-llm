"""
LangChain의 MCP 어댑터를 사용하는 MCP 클라이언트 매니저.
MCP 서버 통신을 위한 고수준 추상화를 제공합니다.
"""

import asyncio
import time
from datetime import timedelta
from typing import Dict, List, Optional

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from app.models.mcp_server import MCPServerConfig, MCPServerStatus, MCPResponse
from app.utils.logger import get_logger
from config.settings import get_settings

logger = get_logger(__name__)


class MCPClientManager:
    """
    LangChain의 MultiServerMCPClient를 사용하여 MCP 서버 연결을 관리합니다.
    MCP 서버 라이프사이클을 단순화하고 통합 쿼리 인터페이스를 제공합니다.
    """

    def __init__(self, timeout: int = 30, max_retries: int = 3):
        """
        MCP 클라이언트 매니저를 초기화합니다.

        Args:
            timeout: 서버 작업 타임아웃(초).
            max_retries: 실패한 작업에 대한 최대 재시도 횟수.
        """
        self.timeout = timeout
        self.max_retries = max_retries

        # LangChain MCP 클라이언트
        self.mcp_client: Optional[MultiServerMCPClient] = None

        # 설정 및 상태 저장소
        self._server_configs: Dict[str, MCPServerConfig] = {}
        self._server_status: Dict[str, MCPServerStatus] = {}

        # LLM 인스턴스 캐시 (재사용)
        self._llm_instance = None

    async def initialize_servers(self, configs: List[MCPServerConfig]) -> None:
        """
        MultiServerMCPClient를 사용하여 설정에서 MCP 서버를 초기화합니다.

        Args:
            configs: 초기화할 MCP 서버 설정 목록.
        """
        # 설정 저장
        for config in configs:
            self._server_configs[config.name] = config
            self._server_status[config.name] = MCPServerStatus(
                name=config.name,
                enabled=config.enabled,
                type=config.type,
            )

        # MultiServerMCPClient를 위한 서버 설정 빌드
        enabled_configs = [c for c in configs if c.enabled]

        if not enabled_configs:
            logger.info("초기화할 활성화된 MCP 서버가 없습니다")
            return

        # LangChain MCP 형식으로 변환
        mcp_servers = {}

        for config in enabled_configs:
            if config.is_process_based():
                # 프로세스 기반 서버 설정 (stdio 전송)
                mcp_servers[config.name] = {
                    "command": config.command,
                    "args": config.args or [],
                    "transport": "stdio",
                    "env": config.env if config.env else None,
                }

            elif config.is_http_based():
                # HTTP 기반 서버 설정
                mcp_servers[config.name] = {
                    "url": config.url,
                    "transport": "http",
                }
                # headers가 제공된 경우 추가
                if config.headers:
                    mcp_servers[config.name]["headers"] = config.headers

        if not mcp_servers:
            logger.info("초기화할 MCP 서버가 없습니다")
            return

        try:
            # MultiServerMCPClient 초기화
            self.mcp_client = MultiServerMCPClient(mcp_servers)

            # 모든 설정된 서버의 상태 업데이트
            for server_name in mcp_servers.keys():
                try:
                    is_healthy = await self.health_check(server_name)
                    self._server_status[server_name].running = True
                    self._server_status[server_name].healthy = is_healthy
                    self._server_status[server_name].error = None if is_healthy else "상태 확인 실패"
                except Exception as server_error:
                    self._server_status[server_name].running = False
                    self._server_status[server_name].healthy = False
                    self._server_status[server_name].error = str(server_error)

            logger.info(f"✓ MultiServerMCPClient를 통해 {len(mcp_servers)}개 MCP 서버 초기화 완료")

        except Exception as e:
            error_msg = f"MultiServerMCPClient 초기화 실패: {e}"
            logger.error(f"✗ {error_msg}")

            # 모든 서버를 실패로 표시
            for server_name in mcp_servers.keys():
                self._server_status[server_name].running = False
                self._server_status[server_name].healthy = False
                self._server_status[server_name].error = str(e)

    async def start_server(self, name: str) -> None:
        """
        특정 MCP 서버를 시작합니다.

        참고: MultiServerMCPClient를 사용하면 모든 서버가 함께 초기화됩니다.
        이 메서드는 서버 상태를 검증합니다.

        Args:
            name: 서버 이름.

        Raises:
            ValueError: 서버를 찾을 수 없는 경우.
        """
        if name not in self._server_configs:
            raise ValueError(f"서버 '{name}'을(를) 설정에서 찾을 수 없습니다")

        config = self._server_configs[name]

        if not config.enabled:
            self._server_status[name].running = False
            self._server_status[name].error = "서버가 설정에서 비활성화되었습니다"
            return

        # MCP 클라이언트가 초기화되었는지 확인
        if not self.mcp_client:
            raise RuntimeError("MultiServerMCPClient가 초기화되지 않았습니다. 먼저 initialize_servers()를 호출하세요.")

        # 활성화된 경우 서버가 이미 시작되어야 함
        self._server_status[name].running = True
        self._server_status[name].healthy = True

    async def stop_server(self, name: str) -> None:
        """
        특정 MCP 서버를 중지합니다.

        참고: MultiServerMCPClient를 사용하면 서버가 집합적으로 관리됩니다.

        Args:
            name: 서버 이름.
        """
        if name in self._server_status:
            self._server_status[name].running = False
            self._server_status[name].healthy = False

    async def query_server(self, name: str, query: str, context: Optional[Dict] = None) -> MCPResponse:
        """
        LangChain 도구를 사용하여 특정 MCP 서버를 쿼리합니다.

        Args:
            name: 서버 이름.
            query: 쿼리 문자열.
            context: 선택적 컨텍스트 딕셔너리.

        Returns:
            쿼리 결과가 포함된 MCPResponse.
        """
        config = self._server_configs.get(name)
        if not config:
            return MCPResponse(
                server_name=name,
                success=False,
                error=f"서버 '{name}'을(를) 찾을 수 없습니다",
            )

        if not config.enabled:
            return MCPResponse(
                server_name=name,
                success=False,
                error=f"서버 '{name}'이(가) 활성화되지 않았습니다",
            )

        if not self.mcp_client:
            return MCPResponse(
                server_name=name,
                success=False,
                error="MultiServerMCPClient가 초기화되지 않았습니다",
            )

        start_time = time.time()

        try:
            # 세션을 사용하여 특정 서버에서 도구 가져오기
            async with self.mcp_client.session(name) as session:
                from langchain_mcp_adapters.tools import load_mcp_tools
                
                tools = await load_mcp_tools(session)
                
                if not tools:
                    return MCPResponse(
                        server_name=name,
                        success=False,
                        error=f"서버 '{name}'에 사용 가능한 도구가 없습니다",
                        latency_ms=(time.time() - start_time) * 1000,
                    )

                # 선택적 컨텍스트로 쿼리 입력 준비
                query_input = query
                if context:
                    query_input = f"{query}\n추가 컨텍스트: {context}"

                # 실행 추적 변수
                result = None
                tool_name = None

                # LangChain Agent를 항상 사용하여 도구 호출 처리
                # Agent는 각 도구의 입력 스키마를 이해하고 적절한 파라미터를 전달함
                try:
                    # LLM 인스턴스 초기화 (한 번만)
                    if self._llm_instance is None:
                        settings = get_settings()

                        if settings.llm.provider == "ollama":
                            self._llm_instance = ChatOllama(
                                base_url=settings.ollama.base_url,
                                model=settings.ollama.model,
                                max_tokens=settings.llm.max_tokens,  # 도구 선택을 위한 충분한 토큰
                                temperature=0.0,  # 결정론적 도구 선택을 위해 0으로 재정의
                            )
                        elif settings.llm.provider == "openai":
                            self._llm_instance = ChatOpenAI(
                                model=settings.llm.model,
                                temperature=0.0,  # 결정론적 도구 선택을 위해 0으로 재정의
                                max_tokens=settings.llm.max_tokens,  # 도구 선택을 위한 충분한 토큰
                                api_key=settings.openai.api_key,
                                base_url=settings.openai.base_url,
                            )

                    # 에이전트 프롬프트 생성 (매번 동일)
                    agent_prompt = ChatPromptTemplate.from_messages([
                        ("system", "당신은 사용 가능한 도구를 사용하여 쿼리에 답변하는 유용한 어시스턴트입니다. 주어진 쿼리에 가장 적합한 도구를 사용하세요."),
                        ("human", "{input}"),
                        ("placeholder", "{agent_scratchpad}"),
                    ])

                    # 에이전트 생성 (현재 세션의 tools 사용)
                    # 주의: tools는 세션마다 새로 로드되므로 매번 agent를 재생성해야 함
                    agent = create_tool_calling_agent(self._llm_instance, tools, agent_prompt)
                    agent_executor = AgentExecutor(
                        agent=agent,
                        tools=tools,
                        verbose=False,
                        return_intermediate_steps=True  # 도구 사용 정보를 반환하도록 설정
                    )

                    agent_result = await agent_executor.ainvoke({"input": query_input})
                    result = agent_result.get("output", agent_result)

                    # 도구 사용 여부 및 도구 이름 추출
                    tool_name = "no_tool_used"

                    if "intermediate_steps" in agent_result and agent_result["intermediate_steps"]:
                        # intermediate_steps가 비어있지 않으면 도구가 사용된 것
                        # # 첫 번째 도구 호출 정보 추출
                        tool_name = agent_result["intermediate_steps"][0][0].tool
                    else:
                        logger.info("도구 사용되지 않음 - LLM이 직접 응답")
                        
                        latency_ms = (time.time() - start_time) * 1000
                        return MCPResponse(
                            server_name=name,
                            success=False,
                            data={
                                "message": f"서버 '{name}' 도구는 사용되지 않음",
                            },
                            latency_ms=latency_ms,
                        )

                except Exception as agent_error:
                    logger.error(f"서버 '{name}'의 에이전트 실행 중 오류 발생: {agent_error}", exc_info=True)
                    latency_ms = (time.time() - start_time) * 1000

                    return MCPResponse(
                        server_name=name,
                        success=False,
                        error=f"서버 '{name}'의 에이전트 실행 중 오류 발생: {str(agent_error)}",
                        latency_ms=latency_ms,
                    )

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
                error=f"쿼리 실패: {str(e)}",
                latency_ms=latency_ms,
            )

    async def select_appropriate_server(self, server_names: List[str], query: str) -> Optional[str]:
        """
        LLM을 사용하여 쿼리에 가장 적합한 MCP 서버를 선택합니다.

        Args:
            server_names: 선택 가능한 서버 이름 목록.
            query: 사용자 쿼리 문자열.

        Returns:
            선택된 서버 이름 또는 적절한 서버가 없으면 None.
        """
        if not server_names:
            return None

        # 각 서버에서 사용 가능한 도구 수집
        server_tools_info = {}
        for server_name in server_names:
            try:
                tools = await self.get_available_tools_info(server_name)
                if tools:
                    server_tools_info[server_name] = tools
            except:
                pass

        if not server_tools_info:
            logger.warning("사용 가능한 도구가 있는 서버가 없습니다")
            return None

        # LLM 인스턴스 준비 (캐시된 것 사용)
        if self._llm_instance is None:
            settings = get_settings()
            if settings.llm.provider == "ollama":
                self._llm_instance = ChatOllama(
                    base_url=settings.ollama.base_url,
                    model=settings.ollama.model,
                    max_tokens=settings.llm.max_tokens,  # 서버 선택을 위한 충분한 토큰
                    temperature=0.0,
                )
            elif settings.llm.provider == "openai":
                self._llm_instance = ChatOpenAI(
                    model=settings.llm.model,
                    temperature=0.0,
                    max_tokens=settings.llm.max_tokens,  # 서버 선택을 위한 충분한 토큰
                    api_key=settings.openai.api_key,
                    base_url=settings.openai.base_url,
                )

        # 서버 정보를 문자열로 포맷팅
        server_descriptions = []
        for server_name, tools in server_tools_info.items():
            config = self._server_configs.get(server_name)
            description = config.description if config else "설명 없음"

            # 도구 정보 포맷팅
            tool_descriptions = []
            for tool in tools:
                tool_name = tool['name']
                tool_desc = tool['description']
                tool_descriptions.append(f"{tool_name} ({tool_desc})")

            tools_descriptions_text = ', '.join(tool_descriptions)
            server_descriptions.append(
                f"- {server_name}: {description}\n  사용 가능한 도구: {tools_descriptions_text}"
            )

        server_info_text = "\n".join(server_descriptions)

        # LLM에게 서버 선택 요청
        selection_prompt = ChatPromptTemplate.from_messages([
            ("system", """당신은 사용자 쿼리에 가장 적합한 MCP 서버를 선택하는 어시스턴트입니다.
                사용 가능한 서버와 각 서버가 제공하는 도구를 기반으로, 사용자 쿼리를 처리하기에 가장 적합한 서버 하나를 선택하세요.

                응답은 반드시 다음 형식 중 하나를 따라야 합니다:
                - 서버를 선택한 경우: "SERVER: <서버이름>"
                - 적절한 서버가 없는 경우: "SERVER: none"

                예시:
                - "SERVER: sqlite"
                - "SERVER: brave-search"
                - "SERVER: none"

                반드시 정확히 이 형식으로만 응답하세요."""),
                ("human", """사용자 쿼리: {query}

                사용 가능한 서버:
                {server_info}

                가장 적합한 서버를 선택하세요.""")
        ])

        try:
            chain = selection_prompt | self._llm_instance | StrOutputParser()
            response = await chain.ainvoke({
                "query": query,
                "server_info": server_info_text
            })

            # 응답에서 서버 이름 추출
            response = response.strip()
            if response.startswith("SERVER:"):
                selected_server = response.replace("SERVER:", "").strip()

                if selected_server == "none":
                    logger.info("LLM이 적절한 서버를 선택하지 않았습니다")
                    return None

                if selected_server in server_names:
                    logger.info(f"LLM이 서버 '{selected_server}'를 선택했습니다")
                    return selected_server
                else:
                    logger.warning(f"LLM이 유효하지 않은 서버 '{selected_server}'를 선택했습니다")
                    # 첫 번째 서버를 대체로 사용
                    return server_names[0]
            else:
                logger.warning(f"LLM 응답 형식이 예상과 다릅니다: {response}")
                # 첫 번째 서버를 대체로 사용
                return server_names[0]

        except Exception as e:
            logger.error(f"서버 선택 중 오류 발생: {e}", exc_info=True)
            # 오류 시 첫 번째 서버 반환
            return server_names[0] if server_names else None

    async def get_context(self, server_names: List[str], query: str) -> Dict[str, MCPResponse]:
        """
        여러 MCP 서버에서 병렬로 컨텍스트를 수집합니다.

        Args:
            server_names: 쿼리할 서버 이름 목록.
            query: 쿼리 문자열.

        Returns:
            서버 이름을 응답에 매핑하는 딕셔너리.
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
        모든 MCP 서버에서 모든 도구를 가져옵니다.

        Returns:
            모든 서버의 LangChain 도구 목록.
        """
        if not self.mcp_client:
            return []

        try:
            tools = await self.mcp_client.get_tools()
            return tools
        except Exception as e:
            logger.warning(f"도구 가져오기 실패: {e}")
            return []

    async def health_check(self, name: str) -> bool:
        """
        서버가 정상인지 확인합니다.

        Args:
            name: 서버 이름.

        Returns:
            서버가 정상이면 True, 그렇지 않으면 False.
        """
        status = self._server_status.get(name)
        if not status or not status.enabled:
            return False

        if not self.mcp_client:
            return False

        try:
            # 상태 확인으로 서버에서 도구를 가져오려고 시도
            async with self.mcp_client.session(name) as session:
                from langchain_mcp_adapters.tools import load_mcp_tools
                tools = await load_mcp_tools(session)
                return tools is not None and len(tools) > 0
        except:
            logger.error(f"서버 '{name}'의 상태 확인 중 오류 발생", exc_info=True)
            logger.warning(f"서버 '{name}'의 상태 확인 실패")
            return False

    def get_server_status(self, name: str) -> Optional[MCPServerStatus]:
        """특정 서버의 상태를 가져옵니다."""
        return self._server_status.get(name)

    def get_all_statuses(self) -> Dict[str, MCPServerStatus]:
        """모든 서버의 상태를 가져옵니다."""
        return self._server_status.copy()

    async def get_available_tools_info(self, server_name: Optional[str] = None) -> List[str]:
        """
        사용 가능한 도구 이름 목록을 가져옵니다.

        Args:
            server_name: 도구를 필터링할 선택적 서버 이름. None이면 모든 도구를 반환합니다.

        Returns:
            도구 이름 목록.
        """
        if not self.mcp_client:
            return []

        try:
            if server_name:
                # 특정 서버에서 도구 가져오기
                async with self.mcp_client.session(server_name) as session:
                    from langchain_mcp_adapters.tools import load_mcp_tools
                    tools = await load_mcp_tools(session)
                    return [
                                {
                                    "name" : tool.name,
                                    "description": tool.description
                                } 
                            for tool in tools] if tools else []
            else:
                # 모든 도구 가져오기
                tools = await self.mcp_client.get_tools()
                return [tool.name for tool in tools] if tools else []
        except:
            return []

    async def shutdown(self) -> None:
        """모든 MCP 서버를 정상적으로 종료합니다."""
        if self.mcp_client:
            # MultiServerMCPClient는 가비지 컬렉션 시 정리를 처리합니다
            # 명시적인 close 메서드가 필요하지 않습니다
            logger.info("✓ MultiServerMCPClient 종료 성공")
            self.mcp_client = None

        # 모든 서버 상태 업데이트
        for name in self._server_status:
            self._server_status[name].running = False
            self._server_status[name].healthy = False
