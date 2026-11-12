from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI

# Public path prefix -> key in the sub_apps dict passed to build_app().
MOUNT_PREFIXES = {
    "/orchestrator": "orchestrator",
    "/buyer": "buyer",
    "/registry": "registry",
    "/sellers": "seller",
    "/control-plane": "control_plane",
    "/verifund-agent": "verifund_agent",
}


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
        app.mount(prefix, sub_apps[name])

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
