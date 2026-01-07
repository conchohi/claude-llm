"""
쿼리 프로세서 - MCP 컨텍스트 수집 및 LangChain 응답 생성을 조율합니다.
"""

import time
import uuid
from typing import Dict, List, Optional, AsyncIterator

from app.core.mcp.mcp_client import MCPClientManager
from app.core.llm.llm_service_base import BaseLLMService
from app.core.session_manager import SessionManager
from app.models.mcp_server import MCPResponse

MAX_CONVERSATION_HISTORY_MESSAGES = 10
MCP_CONTEXT_PREVIEW_LENGTH = 200

class QueryProcessor:
    """
    사용자 쿼리 처리를 위한 주요 조율자.
    MCP 컨텍스트 수집 및 LangChain 응답 생성을 조정합니다.
    """

    def __init__(
        self,
        mcp_client: MCPClientManager,
        llm_service: BaseLLMService,
        session_manager: Optional[SessionManager] = None,
    ):
        """
        쿼리 프로세서를 초기화합니다.

        Args:
            mcp_client: MCP 클라이언트 매니저 인스턴스.
            llm_service: LLM 서비스 인스턴스 (Ollama 또는 OpenAI).
            session_manager: 대화 기록을 위한 선택적 세션 매니저.
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
        MCP 컨텍스트와 함께 사용자 쿼리를 처리하고 응답을 생성합니다.

        Args:
            query: 사용자 쿼리 문자열.
            user_id: 세션 관리를 위한 사용자 ID.
            session_id: 선택적 세션 ID. None이고 user_id가 제공되면 새 세션을 생성합니다.
            use_conversation_history: 컨텍스트에 대화 기록을 포함할지 여부.
            mcp_servers: 쿼리할 MCP 서버 이름 목록 (선택 사항). None이면 모든 활성화된 서버를 사용합니다.
            model: 선택적 모델 재정의.
            temperature: 선택적 온도 재정의.
            max_tokens: 선택적 최대 토큰 재정의.

        Returns:
            응답, MCP 컨텍스트, session_id 및 메타데이터를 포함하는 딕셔너리.
        """
        start_time = time.time()

        # 0단계: 세션 및 프로필 관리
        session = None
        user_profile = None
        conversation_history = ""

        if self.session_manager and user_id:
            # 세션 가져오기 또는 생성
            if session_id:
                session = await self.session_manager.get_session(session_id)
                if not session or session.user_id != user_id:
                    # 유효하지 않은 세션, 새로 생성
                    session = await self.session_manager.create_session(user_id)
            else:
                # 새 세션 생성
                session = await self.session_manager.create_session(user_id)

            # 기본값을 위한 사용자 프로필 가져오기
            user_profile = await self.session_manager.get_user_profile(user_id)

            # 활성화된 경우 대화 기록 구축
            if use_conversation_history and session and session.messages:
                history_parts = []
                for msg in session.messages[-MAX_CONVERSATION_HISTORY_MESSAGES:]:  # 컨텍스트를 위한 최근 10개 메시지
                    role_label = "User" if msg.role == "user" else "Assistant"
                    history_parts.append(f"{role_label}: {msg.content}")
                conversation_history = "\n".join(history_parts)

            # 명시적으로 제공되지 않은 경우 사용자 프로필 기본값 적용
            if user_profile:
                if model is None:
                    model = user_profile.default_model
                if temperature is None:
                    temperature = user_profile.default_temperature
                if max_tokens is None:
                    max_tokens = user_profile.default_max_tokens
                if mcp_servers is None and user_profile.preferred_mcp_servers:
                    mcp_servers = user_profile.preferred_mcp_servers

        # 1단계: 캐싱과 함께 MCP 컨텍스트 수집
        mcp_context = {}
        if mcp_servers:
            mcp_context = await self._gather_mcp_context(mcp_servers, query, use_cache=True)
        else:
            # 모든 활성화된 서버 사용
            enabled_servers = [
                name for name, status in self.mcp_client.get_all_statuses().items()
                if status.enabled and status.running
            ]
            if enabled_servers:
                mcp_context = await self._gather_mcp_context(enabled_servers, query, use_cache=True)

        # 2단계: 컨텍스트 및 대화 기록과 함께 LLM 응답 생성
        llm_kwargs = {}
        if temperature is not None:
            llm_kwargs["temperature"] = temperature
        if max_tokens is not None:
            llm_kwargs["max_tokens"] = max_tokens

        # 쿼리 컨텍스트에 대화 기록 포함
        enhanced_query = query
        if conversation_history:
            enhanced_query = f"Conversation History:\n{conversation_history}\n\nCurrent Query: {query}"

        llm_response = await self.llm_service.generate_response(
            query=enhanced_query,
            mcp_context=mcp_context,
            model=model,
            **llm_kwargs
        )

        # 3단계: 활성화된 경우 세션에 저장
        if session and self.session_manager:
            # 사용자 메시지 추가
            session.add_message(role="user", content=query)

            # MCP 컨텍스트와 함께 어시스턴트 응답 추가
            mcp_context_summary = {
                name: {"success": resp.success, "data_preview": str(resp.data)[:200]}
                for name, resp in mcp_context.items()
            }
            session.add_message(
                role="assistant",
                content=llm_response.get("response", ""),
                mcp_context=mcp_context_summary,
            )

            # Redis에 세션 저장
            await self.session_manager.save_session(session)

        # 4단계: 메타데이터 계산
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

        # 세션이 있으면 응답에 session_id 포함
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
        스트리밍 응답과 함께 사용자 쿼리를 처리합니다.

        Args:
            query: 사용자 쿼리 문자열.
            user_id: 세션 관리를 위한 사용자 ID.
            session_id: 선택적 세션 ID.
            use_conversation_history: 대화 기록을 포함할지 여부.
            mcp_servers: 쿼리할 MCP 서버 이름 목록 (선택 사항).
            model: 선택적 모델 재정의.
            temperature: 선택적 온도 재정의.
            max_tokens: 선택적 최대 토큰 재정의.

        Yields:
            생성되는 응답 청크.
        """
        # 0단계: 세션 및 프로필 관리
        session = None
        user_profile = None
        conversation_history = ""

        if self.session_manager and user_id:
            # 세션 가져오기 또는 생성
            if session_id:
                session = await self.session_manager.get_session(session_id)
                if not session or session.user_id != user_id:
                    session = await self.session_manager.create_session(user_id)
            else:
                session = await self.session_manager.create_session(user_id)

            # 기본값을 위한 사용자 프로필 가져오기
            user_profile = await self.session_manager.get_user_profile(user_id)

            # 대화 기록 구축
            if use_conversation_history and session and session.messages:
                history_parts = []
                for msg in session.messages[-10:]:
                    role_label = "User" if msg.role == "user" else "Assistant"
                    history_parts.append(f"{role_label}: {msg.content}")
                conversation_history = "\n".join(history_parts)

            # 사용자 프로필 기본값 적용
            if user_profile:
                if model is None:
                    model = user_profile.default_model
                if temperature is None:
                    temperature = user_profile.default_temperature
                if max_tokens is None:
                    max_tokens = user_profile.default_max_tokens
                if mcp_servers is None and user_profile.preferred_mcp_servers:
                    mcp_servers = user_profile.preferred_mcp_servers

        # 1단계: 캐싱과 함께 MCP 컨텍스트 수집
        mcp_context = {}
        if mcp_servers:
            mcp_context = await self._gather_mcp_context(mcp_servers, query, use_cache=True)
        else:
            # 모든 활성화된 서버 사용
            enabled_servers = [
                name for name, status in self.mcp_client.get_all_statuses().items()
                if status.enabled and status.running
            ]
            if enabled_servers:
                mcp_context = await self._gather_mcp_context(enabled_servers, query, use_cache=True)

        # 2단계: 컨텍스트 및 기록과 함께 LLM 응답 스트리밍
        llm_kwargs = {}
        if temperature is not None:
            llm_kwargs["temperature"] = temperature
        if max_tokens is not None:
            llm_kwargs["max_tokens"] = max_tokens

        # 쿼리 컨텍스트에 대화 기록 포함
        enhanced_query = query
        if conversation_history:
            enhanced_query = f"Conversation History:\n{conversation_history}\n\nCurrent Query: {query}"

        # 세션 저장을 위해 전체 응답 수집
        full_response = ""

        async for chunk in self.llm_service.generate_streaming_response(
            query=enhanced_query,
            mcp_context=mcp_context,
            model=model,
            **llm_kwargs
        ):
            full_response += chunk
            yield chunk

        # 3단계: 스트리밍 완료 후 세션에 저장
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
        선택적 캐싱과 함께 지정된 MCP 서버에서 컨텍스트를 수집합니다.

        Args:
            server_names: 쿼리할 MCP 서버 이름 목록.
            query: 쿼리 문자열.
            use_cache: MCP 캐시를 사용할지 여부 (세션 매니저가 사용 가능한 경우).

        Returns:
            서버 이름을 응답에 매핑하는 딕셔너리.
        """
        if not use_cache or not self.session_manager:
            # 캐싱 없음, MCP 서버를 직접 쿼리
            return await self.mcp_client.get_context(server_names, query)

        # 캐싱 활성화
        results = {}

        for server_name in server_names:
            # 캐시 키 생성
            cache_key = self.session_manager.generate_mcp_cache_key(server_name, query)

            # 캐시에서 가져오기 시도
            cached_data = await self.session_manager.get_mcp_cache(cache_key)

            if cached_data is not None:
                # 캐시 히트 - MCPResponse 재구성
                results[server_name] = MCPResponse(
                    success=cached_data.get("success", True),
                    data=cached_data.get("data"),
                    error=cached_data.get("error"),
                    latency_ms=0.0,  # 캐시 히트는 레이턴시 없음
                )
            else:
                # 캐시 미스 - MCP 서버 쿼리
                server_results = await self.mcp_client.get_context([server_name], query)
                if server_name in server_results:
                    response = server_results[server_name]
                    results[server_name] = response

                    # 성공적인 응답을 캐시에 저장
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
        JSON 응답을 위해 MCP 컨텍스트를 포맷팅합니다.

        Args:
            mcp_context: 원시 MCP 컨텍스트 딕셔너리.

        Returns:
            API 응답에 적합한 포맷된 딕셔너리.
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
        쿼리 프로세서 및 그 의존성에 대한 헬스 체크를 수행합니다.

        Returns:
            헬스 체크 상태 딕셔너리.
        """
        # LLM 연결 확인 (Ollama 또는 OpenAI)
        llm_status = await self.llm_service.test_connection()

        # MCP 서버 확인
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

        # 전체 헬스
        all_healthy = (
            llm_status["success"]
            and all(status.healthy for status in mcp_statuses.values() if status.enabled)
        )

        return {
            "healthy": all_healthy,
            "llm": llm_status,
            "mcp_servers": mcp_health,
        }
