from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Callable

from fastapi import FastAPI

from verifund_control_plane.api import checkout, health, ops, seller, webhooks
from verifund_control_plane.db import configure_sqlite, create_engine
from verifund_control_plane.evidence import EvidenceStore
from verifund_control_plane.errors import VerifundError, verifund_error_handler
from verifund_control_plane.paypal.fake import FakePaymentPort
from verifund_control_plane.paypal.sandbox import PayPalSandboxPaymentPort
from verifund_control_plane.repository import Repository
from verifund_control_plane.service import VerifundService
from verifund_control_plane.settings import Settings
from verifund_control_plane.tokens import LinkSigner, SellerTokenService


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
    evidence_store = EvidenceStore(
        settings.evidence_dir, max_bytes=settings.max_evidence_bytes
    )
    tokens = SellerTokenService(
        settings.seller_token_secret,
        ttl_hours=settings.seller_token_ttl_hours,
        clock=now,
    )
    links = LinkSigner(
        settings.link_secret,
        checkout_ttl_minutes=settings.checkout_link_ttl_minutes,
        return_ttl_hours=settings.return_link_ttl_hours,
        clock=now,
    )
    if settings.is_sandbox:
        payments = PayPalSandboxPaymentPort(
            base_url=settings.paypal_api_base,
            client_id=settings.paypal_client_id,
            client_secret=settings.paypal_client_secret,
            webhook_id=settings.paypal_webhook_id,
            clock=now,
        )
    else:
        payments = FakePaymentPort(
            repo,
            scenario=settings.fake_payment_scenario,
            clock=now,
        )
    service = VerifundService(
        repo=repo,
        settings=settings,
        clock=now,
        tokens=tokens,
        evidence_store=evidence_store,
        payments=payments,
        links=links,
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
    app.state.evidence_store = evidence_store
    app.state.links = links
    app.state.link_signer = links
    app.state.payments = payments
    app.add_exception_handler(VerifundError, verifund_error_handler)
    app.include_router(health.router)
    app.include_router(ops.router)
    app.include_router(seller.router)
    app.include_router(checkout.router)
    app.include_router(webhooks.router)
    return app
