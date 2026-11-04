import secrets
from collections.abc import Iterable

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        token: str,
        public_paths: Iterable[str] = (),
    ) -> None:
        super().__init__(app)
        self.token = token
        self.public_paths = set(public_paths)

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.public_paths:
            return await call_next(request)
        authorization = request.headers.get("authorization", "")
        expected = f"Bearer {self.token}"
        if not secrets.compare_digest(authorization, expected):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)
