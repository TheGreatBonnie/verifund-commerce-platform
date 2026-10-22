from __future__ import annotations

# Patch mcp.types with missing classes from mcp-types before litellm imports them
import mcp.types
from typing import Any

if not hasattr(mcp.types, "CacheableResult"):
    from pydantic import BaseModel
    class CacheableResult(BaseModel):
        ttl_ms: int = 0
        cache_scope: str = "private"
    mcp.types.CacheableResult = CacheableResult

if not hasattr(mcp.types, "InputRequiredResult"):
    from pydantic import BaseModel
    class InputRequiredResult(BaseModel):
        input_requests: Any = None
        request_state: Any = None
        meta: Any = None
    mcp.types.InputRequiredResult = InputRequiredResult

# Patch version and methods submodules needed by litellm
if not hasattr(mcp.types, "version"):
    class _version:
        MODERN_PROTOCOL_VERSIONS = ("2026-07-28",)
        HANDSHAKE_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
        LATEST_HANDSHAKE_VERSION = "2025-11-25"
    mcp.types.version = _version()

if not hasattr(mcp.types, "methods"):
    class _methods:
        CLIENT_REQUESTS = frozenset()
    mcp.types.methods = _methods()

# Patch A2A JSON-RPC dispatcher to accept both PascalCase and lowercase method names
# The JavaScript SDK uses lowercase (e.g., "message/send") while Python SDK expects PascalCase (e.g., "SendMessage")
import a2a.server.routes.jsonrpc_dispatcher as _dispatcher
_original_method_to_model = _dispatcher.JsonRpcDispatcher.METHOD_TO_MODEL.copy()
_method_aliases = {
    'message/send': 'SendMessage',
    'message/stream': 'SendStreamingMessage',
    'tasks/get': 'GetTask',
    'tasks/list': 'ListTasks',
    'tasks/cancel': 'CancelTask',
    'tasks/pushNotificationConfig/set': 'CreateTaskPushNotificationConfig',
    'tasks/pushNotificationConfig/get': 'GetTaskPushNotificationConfig',
    'tasks/pushNotificationConfig/list': 'ListTaskPushNotificationConfigs',
    'tasks/pushNotificationConfig/delete': 'DeleteTaskPushNotificationConfig',
    'tasks/resubscribe': 'SubscribeToTask',
    'agent/auth/getExtendedCard': 'GetExtendedAgentCard',
}
_dispatcher.JsonRpcDispatcher.METHOD_TO_MODEL.update(
    {alias: _original_method_to_model[canonical] for alias, canonical in _method_aliases.items() if canonical in _original_method_to_model}
)

import uvicorn

from orchestrator_agent.server import create_app
from orchestrator_agent.settings import Settings


def main() -> None:
    settings = Settings()
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
