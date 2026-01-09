"""
API 키 검증을 위한 인증 미들웨어.
"""

from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from openai import api_key
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Optional, Callable

from app.core.api_key_manager import APIKeyManager


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """
    API 키 인증을 위한 미들웨어.

    화이트리스트에 등록된 경로를 제외한 모든 요청에서 API 키를 검증합니다.
    """

    # 인증이 필요하지 않은 경로
    EXEMPT_PATHS = [
        "/",
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    ]

    def __init__(
        self,
        app,
        api_key_manager_getter: Callable[[], Optional[APIKeyManager]],
        auth_enabled: bool = True,
        api_key_header: str = "X-API-Key"
    ):
        """
        인증 미들웨어를 초기화합니다.

        Args:
            app: FastAPI 애플리케이션.
            api_key_manager_getter: APIKeyManager 인스턴스를 반환하는 Callable (지연 참조).
            auth_enabled: 인증 활성화 여부.
            api_key_header: API 키를 위한 헤더 이름.
        """
        super().__init__(app)
        self.api_key_manager_getter = api_key_manager_getter
        self.auth_enabled = auth_enabled
        self.api_key_header = api_key_header

    async def dispatch(self, request: Request, call_next):
        """
        요청을 처리하고 인증을 검증합니다.

        Args:
            request: 들어오는 요청.
            call_next: 다음 미들웨어/핸들러.

        Returns:
            핸들러의 응답 또는 인증 오류.
        """
        # 인증이 비활성화된 경우 건너뛰기
        if not self.auth_enabled:
            return await call_next(request)

        # 제외 경로에 대한 인증 건너뛰기
        if self._is_exempt_path(request.url.path):
            return await call_next(request)

        # APIKeyManager 가져오기 (지연 참조)
        api_key_manager = self.api_key_manager_getter()

        if not api_key_manager:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "error": "Service Unavailable",
                    "detail": "Authentication service is not available",
                    "status_code": 503,
                },
            )

        # API 키 검증
        api_key = request.headers.get(self.api_key_header)
       
        if not api_key:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "error": "Unauthorized",
                    "detail": f"Missing {self.api_key_header} header",
                    "status_code": 401,
                },
            )

        # API 키 유효성 검증
        user_id = await api_key_manager.validate_api_key(api_key)
        
        if not user_id:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "error": "Unauthorized",
                    "detail": "Invalid API key",
                    "status_code": 401,
                },
            )

        # 핸들러에서 사용할 수 있도록 요청 상태에 user_id 추가
        request.state.user_id = user_id
        
        # 다음 핸들러로 계속 진행
        return await call_next(request)

    def _is_exempt_path(self, path: str) -> bool:
        """
        경로가 인증에서 제외되는지 확인합니다.

        Args:
            path: 요청 경로.

        Returns:
            제외되면 True, 그렇지 않으면 False.
        """
        # 정확히 일치하는 경로
        if path in self.EXEMPT_PATHS:
            return True

        # docs에 대한 접두사 일치
        if path.startswith("/docs") or path.startswith("/redoc"):
            return True

        return False


def get_current_user(request: Request) -> str:
    """
    요청 상태에서 현재 사용자 ID를 가져오는 의존성.

    Args:
        request: FastAPI 요청.

    Returns:
        사용자 ID.

    Raises:
        HTTPException: 사용자가 인증되지 않은 경우.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user_id
