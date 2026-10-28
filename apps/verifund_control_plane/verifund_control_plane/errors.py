from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from verifund_contracts.models import ErrorDetail, ErrorEnvelope, VerifundErrorCode


class VerifundError(Exception):
    def __init__(
        self,
        code: str | VerifundErrorCode,
        message: str,
        *,
        status_code: int = 400,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.details = details or {}
        self.request_id = request_id


def error_response(
    error: VerifundError, request: Request | None = None
) -> JSONResponse:
    request_id = error.request_id or (
        request.headers.get("x-request-id") if request is not None else None
    )
    envelope = ErrorEnvelope(
        error=ErrorDetail(
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            details=error.details,
            request_id=request_id,
        )
    )
    headers = {"retry-after": "1"} if error.retryable else None
    return JSONResponse(
        status_code=error.status_code,
        content=envelope.model_dump(mode="json"),
        headers=headers,
    )


async def verifund_error_handler(request: Request, exc: VerifundError) -> JSONResponse:
    return error_response(exc, request)
