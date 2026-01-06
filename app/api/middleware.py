"""
Authentication middleware for API key validation.
"""

from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Optional

from app.core.session_manager import SessionManager


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """
    Middleware for API key authentication.

    Validates API keys on all requests except whitelisted paths.
    """

    # Paths that don't require authentication
    EXEMPT_PATHS = [
        "/",
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    ]

    def __init__(self, app, session_manager: SessionManager, auth_enabled: bool = True, api_key_header: str = "X-API-Key"):
        """
        Initialize authentication middleware.

        Args:
            app: FastAPI application.
            session_manager: SessionManager instance.
            auth_enabled: Whether authentication is enabled.
            api_key_header: Header name for API key.
        """
        super().__init__(app)
        self.session_manager = session_manager
        self.auth_enabled = auth_enabled
        self.api_key_header = api_key_header

    async def dispatch(self, request: Request, call_next):
        """
        Process request and validate authentication.

        Args:
            request: Incoming request.
            call_next: Next middleware/handler.

        Returns:
            Response from handler or authentication error.
        """
        # Skip authentication if disabled
        if not self.auth_enabled:
            return await call_next(request)

        # Skip authentication for exempt paths
        if self._is_exempt_path(request.url.path):
            return await call_next(request)

        # Validate API key
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

        # Validate the API key
        user_id = await self.session_manager.validate_api_key(api_key)

        if not user_id:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "error": "Unauthorized",
                    "detail": "Invalid API key",
                    "status_code": 401,
                },
            )

        # Add user_id to request state for use in handlers
        request.state.user_id = user_id

        # Continue to next handler
        return await call_next(request)

    def _is_exempt_path(self, path: str) -> bool:
        """
        Check if path is exempt from authentication.

        Args:
            path: Request path.

        Returns:
            True if exempt, False otherwise.
        """
        # Exact match
        if path in self.EXEMPT_PATHS:
            return True

        # Prefix match for docs
        if path.startswith("/docs") or path.startswith("/redoc"):
            return True

        return False


def get_current_user(request: Request) -> str:
    """
    Dependency to get current user ID from request state.

    Args:
        request: FastAPI request.

    Returns:
        User ID.

    Raises:
        HTTPException: If user not authenticated.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user_id
