from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Callable

from fastapi import FastAPI

from verifund_control_plane.api import health, ops
from verifund_control_plane.db import configure_sqlite, create_engine
from verifund_control_plane.errors import VerifundError, verifund_error_handler
from verifund_control_plane.repository import Repository
from verifund_control_plane.service import VerifundService
from verifund_control_plane.settings import Settings
from verifund_control_plane.tokens import SellerTokenService


def create_app(
    settings: Settings | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    settings = settings or Settings()
    settings.validate_for_mode()
    now = clock or (lambda: datetime.now(UTC))
    engine = create_engine(settings.database_url)
    repo = Repository(engine)
    settings.evidence_dir.mkdir(parents=True, exist_ok=True)
    tokens = SellerTokenService(
        settings.seller_token_secret,
        ttl_hours=settings.seller_token_ttl_hours,
        clock=now,
    )
    service = VerifundService(
        repo=repo, settings=settings, clock=now, tokens=tokens
    )

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
    app.state.repo = repo
    app.state.tokens = tokens
    app.state.service = service
    app.add_exception_handler(VerifundError, verifund_error_handler)
    app.include_router(health.router)
    app.include_router(ops.router)
    return app
