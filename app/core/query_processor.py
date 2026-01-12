"""
쿼리 프로세서 - MCP 컨텍스트 수집 및 LangChain 응답 생성을 조율합니다.
"""

import time
from datetime import datetime
from typing import Any, Dict, Optional, AsyncIterator
from app.core.mcp.mcp_client import MCPClientManager
from app.core.llm.llm_service_base import BaseLLMService
from app.core.session_manager import SessionManager
from app.models.mcp_server import MCPResponse
from app.models.auth import ConversationSession, ConversationMessage

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

    async def _save_to_session(
        self,
        session: Optional[ConversationSession],
        query: str,
        response_content: str,
    ) -> None:
        """세션에 쿼리와 응답을 저장합니다."""
        if session and self.session_manager:
            session.add_message(role="user", content=query)
            
            session.add_message(
                role="assistant",
                content=response_content,
            )

            await self.session_manager.save_session(session)
    
    async def _save_conversation_message(
        self,
        session_id: str,
        user_id: str,
        content: str,
        role: str,
        mcp_context: Dict[str, Any] = None,
        process_time_ms: int = None,
    ) -> None:
        message = ConversationMessage(
            role=role,
            content=content,
            timestamp=datetime.now(),
            mcp_context=mcp_context,
        )
        
        """세션에 메시지를 저장합니다."""
        if self.session_manager:
            await self.session_manager.save_conversation_message(
                session_id=session_id,
                user_id=user_id,
                message=message,
                process_time_ms=process_time_ms,
            )

    async def process_query(
        self,
        query: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        use_conversation_history: bool = True,
    ) -> Dict:
        """
        MCP 컨텍스트와 함께 사용자 쿼리를 처리하고 응답을 생성합니다.

        Args:
            query: 사용자 쿼리 문자열.
            user_id: 세션 관리를 위한 사용자 ID.
            session_id: 선택적 세션 ID. None이고 user_id가 제공되면 새 세션을 생성합니다.
            use_conversation_history: 컨텍스트에 대화 기록을 포함할지 여부.

        Returns:
            응답, MCP 컨텍스트, session_id 및 메타데이터를 포함하는 딕셔너리.
        """
        start_time = time.time()

        # 0단계: 쿼리 컨텍스트 준비
        session = None
        conversation_history = ""

        if self.session_manager and user_id:
            # 세션 로드
            if session_id:
                session = await self.session_manager.get_session_cache(session_id)

                # 유효하지 않은 세션이면 새로 생성
                if not session or session.user_id != user_id:
                    session = await self.session_manager.create_session(user_id)
            else:
                # 새 세션 생성
                session = await self.session_manager.create_session(user_id)

            # 활성화된 경우 대화 기록 구축
            if use_conversation_history and session and session.messages:
                history_parts = []
                for msg in session.messages[-MAX_CONVERSATION_HISTORY_MESSAGES:]:
                    role_label = "User" if msg.role == "user" else "Assistant"
                    history_parts.append(f"{role_label}: {msg.content}")
                conversation_history = "\n".join(history_parts)
        
        # 사용자 메시지 저장
        await self._save_conversation_message(
            session_id if session_id else session.session_id,
            user_id,
            query,
            "user"
        )

        # 1단계: Agent를 사용하여 필요한 도구 실행
        enhanced_query = query
        if conversation_history:
            enhanced_query = f"Current Query: {query} \n\nConversation History:\n{conversation_history}"

        # Agent가 도구를 실행하고 MCP 컨텍스트 반환
        agent_result = await self.mcp_client.query_with_all_tools(enhanced_query)

        # 2단계: LLM Service를 사용하여 최종 답변 생성
        mcp_context = agent_result.get("mcp_context", {})

        # LLM Service에 Agent 요약도 컨텍스트로 추가
        if agent_result.get("agent_summary"):
            # Agent 요약을 특별한 서버로 추가
            mcp_context["agent_summary"] = MCPResponse(
                server_name="agent_summary",
                success=True,
                data={
                    "summary": agent_result.get("agent_summary")
                }
            )

        # LLM Service로 최종 답변 생성
        llm_response = await self.llm_service.generate_response(
            query=enhanced_query,
            mcp_context=mcp_context,
        )

        # 3단계: 세션에 저장
        await self._save_to_session(session, query, llm_response.get("response", ""))

        # 4단계: 응답 구성
        processing_time = time.time() - start_time
        result = {
            "response": llm_response.get("response", ""),
            "model": llm_response.get("model", self.llm_service.model),
            "mcp_context": self._format_mcp_context_for_response(mcp_context),
            "metadata": {
                "processing_time": round(processing_time, 3),
                "conversation_history_used": bool(conversation_history),
            },
            "success": llm_response.get("success", True),
            "error": llm_response.get("error") if not llm_response.get("success", True) else None,
        }

        if session:
            result["session_id"] = session.session_id

        # 5단계: DB 저장
        await self._save_conversation_message(
            session_id if session_id else session.session_id,
            user_id,
            llm_response.get("response", ""),
            "assistant",
            self._format_mcp_context_for_response(mcp_context),
            process_time_ms= processing_time * 1000
        )
        
        return result

    async def process_streaming_query(
        self,
        query: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        use_conversation_history: bool = True,
    ) -> AsyncIterator[str]:
        """
        스트리밍 응답과 함께 사용자 쿼리를 처리합니다.

        Args:
            query: 사용자 쿼리 문자열.
            user_id: 세션 관리를 위한 사용자 ID.
            session_id: 선택적 세션 ID.
            use_conversation_history: 대화 기록을 포함할지 여부.

        Yields:
            생성되는 응답 청크.
        """
        start_time = time.time()
        
        # 0단계: 쿼리 컨텍스트 준비
        session = None
        conversation_history = ""

        if self.session_manager and user_id:
            # 세션 로드
            if session_id:
                session = await self.session_manager.get_session_cache(session_id)

                # 유효하지 않은 세션이면 새로 생성
                if not session or session.user_id != user_id:
                    session = await self.session_manager.create_session(user_id)
            else:
                # 새 세션 생성
                session = await self.session_manager.create_session(user_id)

            # 활성화된 경우 대화 기록 구축
            if use_conversation_history and session and session.messages:
                history_parts = []
                for msg in session.messages[-MAX_CONVERSATION_HISTORY_MESSAGES:]:
                    role_label = "User" if msg.role == "user" else "Assistant"
                    history_parts.append(f"{role_label}: {msg.content}")
                conversation_history = "\n".join(history_parts)
        
        # 사용자 메시지 저장
        await self._save_conversation_message(
            session_id if session_id else session.session_id,
            user_id,
            query,
            "user"
        )

        # 1단계: Agent를 사용하여 필요한 도구 실행
        enhanced_query = query
        if conversation_history:
            enhanced_query = f"Conversation History:\n{conversation_history}\n\nCurrent Query: {query}"

        # Agent가 도구를 실행하고 MCP 컨텍스트 반환
        agent_result = await self.mcp_client.query_with_all_tools(enhanced_query)

        # 2단계: LLM Service를 사용하여 최종 답변 생성
        mcp_context = agent_result.get("mcp_context", {})

        # LLM Service에 Agent 요약도 컨텍스트로 추가
        if agent_result.get("agent_summary"):
            # Agent 요약을 특별한 서버로 추가
            mcp_context["_agent_summary"] = MCPResponse(
                server_name="_agent_summary",
                success=True,
                data={
                    "summary": agent_result.get("agent_summary")
                }
            )

        # LLM Service로 최종 답변 생성 (스트리밍)
        full_response = ""
        async for chunk in self.llm_service.generate_streaming_response(
            query=enhanced_query,
            mcp_context=mcp_context,
        ):
            full_response += chunk
            yield chunk

        # 3단계: 세션에 저장
        await self._save_to_session(session, query, full_response)
        
        processing_time = time.time() - start_time
        
        # 4단계: DB 저장
        await self._save_conversation_message(
            session_id if session_id else session.session_id,
            user_id,
            full_response,
            "assistant",
            self._format_mcp_context_for_response(mcp_context),
            process_time_ms= processing_time * 1000
        )

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
