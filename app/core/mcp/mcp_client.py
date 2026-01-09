"""
LangChain의 MCP 어댑터를 사용하는 MCP 클라이언트 매니저.
MCP 서버 통신을 위한 고수준 추상화를 제공합니다.
"""

import asyncio
import time
from typing import Dict, List, Optional

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
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
        self._server_tool_mapping: Dict[str, str] = {}  # 도구 이름 -> 서버 이름 매핑

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
                # 도구가 로드되어 서버가 정상이면 서버 매핑 업데이트
                if tools:
                    for tool in tools:
                        self._server_tool_mapping[tool.name] = name
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
                   
            else:
                # 모든 도구 가져오기
                tools = await self.mcp_client.get_tools()
            
            return [
                    {"name": tool.name, "description": tool.description} for tool in tools] if tools else []
        except:
            return []

    async def query_with_all_tools(self, query: str) -> Dict:
        """
        모든 활성화된 MCP 서버의 도구를 로드하여 LLM이 필요한 도구를 선택하고 실행합니다.

        Args:
            query: 사용자 쿼리 문자열.

        Returns:
            LLM 응답, 사용된 도구 정보 및 메타데이터를 포함하는 딕셔너리.
        """

        start_time = time.time()

        if not self.mcp_client:
            return {
                "success": False,
                "error": "MultiServerMCPClient가 초기화되지 않았습니다",
                "response": "",
                "tools_used": [],
            }

        try:
            # 모든 활성화된 서버에서 도구 로드
            all_tools = []

            enabled_servers = [
                name for name, status in self._server_status.items()
                if status.enabled and status.running
            ]

            if not enabled_servers:
                logger.warning("활성화된 MCP 서버가 없습니다")
                return {
                    "success": True,
                    "response": "사용 가능한 MCP 도구가 없어 직접 응답합니다.",
                    "tools_used": []
                }

            # MultiServerMCPClient.get_tools()를 사용하여 모든 도구 로드
            # 이 메서드는 세션을 내부적으로 관리하므로 도구 실행 시 세션이 유지됨
            try:
                all_tools = await self.mcp_client.get_tools()
                logger.info(f"총 {len(all_tools)}개 도구 로드 완료")
            except Exception as e:
                logger.error(f"도구 로드 중 오류 발생: {e}", exc_info=True)
                all_tools = []

            if not all_tools:
                logger.warning("로드된 도구가 없습니다")
                return {
                    "success": True,
                    "response": "사용 가능한 MCP 도구가 없어 직접 응답합니다.",
                    "tools_used": []
                }

            # LLM 인스턴스 초기화 (필요한 경우)
            if self._llm_instance is None:
                settings = get_settings()
                if settings.llm.provider == "ollama":
                    # Agent는 max_tokens 파라미터를 지원하지 않거나 자동 계산함
                    # num_predict로 대체 (Ollama 전용 파라미터)
                    self._llm_instance = ChatOllama(
                        base_url=settings.ollama.base_url,
                        model=settings.llm.model,
                        num_predict=settings.llm.max_tokens,
                        temperature=settings.llm.temperature,
                    )
                elif settings.llm.provider == "openai":
                    # OpenAI API에서 max_tokens는 완료(completion) 토큰만 제한
                    # Agent 사용 시 프롬프트가 길어질 수 있으므로 적절한 값 설정
                    # 참고: 일부 OpenAI 호환 API는 max_tokens 필드가 필수임
                    self._llm_instance = ChatOpenAI(
                        model=settings.llm.model,
                        temperature=settings.llm.temperature,
                        max_tokens=settings.llm.max_tokens,
                        api_key=settings.openai.api_key,
                        base_url=settings.openai.base_url,
                    )

            # 에이전트 프롬프트 생성 (도구 실행에만 집중, 간결하게)
            agent_prompt = ChatPromptTemplate.from_messages([
                 ("system", """당신은 사용자 쿼리를 처리하기 위해 필요한 도구를 선택하고 실행하는 어시스턴트입니다.

                            주어진 쿼리를 처리하기 위해 필요한 도구를 자유롭게 선택하고 사용하세요.
                            여러 도구를 연쇄적으로 사용할 수 있으며, 한 도구의 결과를 바탕으로 다른 도구를 호출할 수 있습니다.
                            필요한 도구를 선택하고 실행하세요. 도구 실행 결과만 간략히 요약하세요.
                            도구 실행이 완료되면 수집한 정보를 요약하여 반환하세요.
                            도구를 사용하지 않았을 경우 빈 응답을 반환하세요.
                            불필요한 설명이나 장황한 내용을 피하고, 도구 실행에 집중하세요."""),
                ("human", "{input}"),
                ("placeholder", "{agent_scratchpad}"),
            ])

            # 에이전트 생성 및 실행
            agent = create_tool_calling_agent(self._llm_instance, all_tools, agent_prompt)
            agent_executor = AgentExecutor(
                agent=agent,
                tools=all_tools,
                verbose=True,
                return_intermediate_steps=True,
                max_iterations=10,
            )

            # 에이전트 실행 (도구 실행만)
            agent_result = await agent_executor.ainvoke({"input": query})

            # 사용된 도구 정보 추출
            tools_used = []
            mcp_context_for_llm = {}  # LLM Service에 전달할 MCP 컨텍스트
    
            if "intermediate_steps" in agent_result and agent_result["intermediate_steps"]:
                for step in agent_result["intermediate_steps"]:
                    tool_action, tool_result = step
                    tool_name = tool_action.tool
                    server_name = self._server_tool_mapping.get(tool_name, "unknown")

                    # 도구 사용 정보 저장
                    tools_used.append({
                        "tool_name": tool_name,
                        "server_name": server_name,
                        "input": tool_action.tool_input,
                        "result": str(tool_result)[:200],  # 결과는 200자로 제한
                        "success": True,
                    })

                    # MCP 컨텍스트 구성 (서버별로 그룹화)
                    if server_name not in mcp_context_for_llm:
                        mcp_context_for_llm[server_name] = MCPResponse(
                            server_name=server_name,
                            success=True,
                            data={
                                "tools_executed": []
                            }
                        )

                    mcp_context_for_llm[server_name].data["tools_executed"].append({
                        "tool_name": tool_name,
                        "input": tool_action.tool_input,
                        "result": str(tool_result)[:3000],  # 3000자로 제한
                    })

            latency_ms = (time.time() - start_time) * 1000

            return {
                "success": True,
                "agent_summary": agent_result.get("output", ""),  # Agent의 요약
                "tools_used": tools_used,
                "mcp_context": mcp_context_for_llm, 
                "latency_ms": latency_ms,
            }

        except Exception as e:
            logger.error(f"모든 도구를 사용한 쿼리 실행 중 오류 발생: {e}", exc_info=True)
            latency_ms = (time.time() - start_time) * 1000

            return {
                "success": False,
                "error": str(e),
                "response": f"쿼리 처리 중 오류 발생: {str(e)}",
                "tools_used": [],
                "latency_ms": latency_ms,
            }

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
