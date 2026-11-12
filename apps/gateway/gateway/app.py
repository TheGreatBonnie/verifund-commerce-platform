from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from starlette.routing import get_route_path

# Public path prefix -> key in the sub_apps dict passed to build_app().
MOUNT_PREFIXES = {
    "/orchestrator": "orchestrator",
    "/buyer": "buyer",
    "/registry": "registry",
    "/sellers": "seller",
    "/control-plane": "control_plane",
    "/verifund-agent": "verifund_agent",
}


def _without_root_path(sub_app: FastAPI):
    """Serve a mounted app as if it were the root app.

    Starlette keeps the mount prefix in ``root_path``, so ``request.url.path``
    inside a sub-app still contains the prefix. Service middleware that
    matches public paths on the request URL (for example the verifund agent's
    bearer auth) would then reject prefixed health checks. Clearing
    ``root_path`` restores the service's original unprefixed view.
    """

    async def asgi(scope, receive, send):
        child_scope = dict(scope)
        child_scope["path"] = get_route_path(scope) or "/"
        child_scope["root_path"] = ""
        await sub_app(child_scope, receive, send)

    return asgi


def build_app(sub_apps: dict[str, FastAPI]) -> FastAPI:
    """Mount each service app at its prefix and compose all lifespans.

    Starlette strips the mount prefix before dispatching to the sub-app, so
    every service keeps its existing unprefixed routes.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with AsyncExitStack() as stack:
            for name in MOUNT_PREFIXES.values():
                sub_app = sub_apps[name]
                await stack.enter_async_context(
                    sub_app.router.lifespan_context(sub_app)
                )
            yield

    app = FastAPI(title="MarketMesh Gateway", lifespan=lifespan)
    for prefix, name in MOUNT_PREFIXES.items():
        app.mount(prefix, _without_root_path(sub_apps[name]))

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
