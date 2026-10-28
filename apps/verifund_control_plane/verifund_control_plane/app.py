from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Callable

from fastapi import FastAPI

from verifund_control_plane.api import health
from verifund_control_plane.db import configure_sqlite, create_engine
from verifund_control_plane.errors import VerifundError, verifund_error_handler
from verifund_control_plane.settings import Settings


def create_app(
    settings: Settings | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    settings = settings or Settings()
    settings.validate_for_mode()
    now = clock or (lambda: datetime.now(UTC))
    engine = create_engine(settings.database_url)
    settings.evidence_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await configure_sqlite(engine)
        if hasattr(app.state, "repo"):
            await app.state.repo.create_schema()
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="Verifund Control Plane", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.clock = now
    app.add_exception_handler(VerifundError, verifund_error_handler)
    app.include_router(health.router)
    return app
