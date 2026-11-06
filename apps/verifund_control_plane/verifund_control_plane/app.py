from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI

from verifund_control_plane.agreements import routes as agreement_routes
from verifund_control_plane.agreements.repository import AgreementRepository
from verifund_control_plane.agreements.service import AgreementService
from verifund_control_plane.agreements.tokens import ApprovalTokenService
from verifund_control_plane.api import buyer, checkout, fulfillment, health, ops, seller, webhooks
from verifund_control_plane.db import configure_sqlite, create_engine
from verifund_control_plane.errors import VerifundError, verifund_error_handler
from verifund_control_plane.evidence import EvidenceStore
from verifund_control_plane.paypal.fake import FakePaymentPort
from verifund_control_plane.paypal.sandbox import PayPalSandboxPaymentPort
from verifund_control_plane.paypal_tracking import (
    FakePayPalTracking,
    PayPalTrackingHttpClient,
)
from verifund_control_plane.receipts import ReceiptSigner
from verifund_control_plane.reconciler import Reconciler
from verifund_control_plane.repository import Repository
from verifund_control_plane.service import VerifundService
from verifund_control_plane.tenancy import routes as tenancy_routes
from verifund_control_plane.tenancy.repository import TenancyRepository
from verifund_control_plane.settings import Settings
from verifund_control_plane.tokens import (
    BuyerTokenService,
    InvitationTokenService,
    LinkSigner,
    SellerTokenService,
)


def create_app(
    settings: Settings | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    settings = settings or Settings()
    settings.validate_for_mode()
    if getattr(settings, "_clerk_directory", None) is None:
        from verifund_control_plane.tenancy.clerk import ClerkBackendDirectory

        settings._clerk_directory = ClerkBackendDirectory(  # type: ignore[attr-defined]
            settings.clerk_secret_key
        )
    now = clock or (lambda: datetime.now(UTC))
    engine = create_engine(settings.database_url)
    repo = Repository(engine)
    tenancy = TenancyRepository(engine)
    agreement_repo = AgreementRepository(engine)
    agreement_tokens = ApprovalTokenService(
        settings.link_secret, ttl_minutes=settings.approval_token_ttl_minutes, clock=now,
    )
    settings.evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_store = EvidenceStore(
        settings.evidence_dir, max_bytes=settings.max_evidence_bytes
    )
    receipts = ReceiptSigner(
        settings.receipt_keys, settings.receipt_active_kid
    )
    tokens = SellerTokenService(
        settings.seller_token_secret,
        ttl_hours=settings.seller_token_ttl_hours,
        clock=now,
    )
    buyer_tokens = BuyerTokenService(
        settings.seller_token_secret,
        ttl_hours=24,
        clock=now,
    )
    invitation_tokens = InvitationTokenService(
        settings.seller_token_secret,
        ttl_minutes=60,
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
    if settings.is_sandbox:
        tracking = PayPalTrackingHttpClient(
            base_url=settings.paypal_api_base,
            client_id=settings.paypal_client_id,
            client_secret=settings.paypal_client_secret,
            clock=now,
        )
    else:
        tracking = FakePayPalTracking()
    async def _sync_transaction_pointer(
        conn, transaction_id: str, version: int, digest: str, at: datetime
    ) -> None:
        record = await repo.get_transaction(transaction_id, conn)
        changes = {"agreement_version": version, "agreement_hash": digest}
        if record.state.value == "AWARDED":
            await repo.transition(
                conn, transaction_id,
                expected_version=record.version,
                expected_state=__import__("verifund_control_plane.domain", fromlist=["TransactionState"]).TransactionState.AWARDED,
                new_state=__import__("verifund_control_plane.domain", fromlist=["TransactionState"]).TransactionState.AGREED,
                changes=changes,
                events=[],
                audit=None,
            )
        else:
            await repo.update_transaction(
                conn, transaction_id, expected_version=record.version,
                changes=changes,
            )

    agreement_service = AgreementService(
        repo=agreement_repo, token_service=agreement_tokens,
        settings=settings, clock=now,
        sync_transaction=_sync_transaction_pointer,
    )
    service = VerifundService(
        repo=repo,
        settings=settings,
        clock=now,
        tokens=tokens,
        buyer_tokens=buyer_tokens,
        invitation_tokens=invitation_tokens,
        evidence_store=evidence_store,
        payments=payments,
        links=links,
        receipts=receipts,
        agreement_service=agreement_service,
        tracking=tracking,
    )
    reconciler = Reconciler(
        repo=repo,
        service=service,
        settings=settings,
        clock=now,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await configure_sqlite(engine)
        if hasattr(app.state, "repo"):
            await app.state.repo.create_schema()
        if hasattr(app.state, "tenancy"):
            await app.state.tenancy.create_schema()
        if hasattr(app.state, "agreement_repo"):
            async with engine.begin() as _c:
                await app.state.agreement_repo.create_schema(_c)
        if settings.tenancy_enabled and hasattr(app.state, "tenancy"):
            from sqlalchemy import select as _select

            from verifund_control_plane.tenancy.backfill import backfill_tenancy

            async with engine.connect() as _conn:
                res = await _conn.execute(_select(app.state.tenancy.organizations))
                empty = res.first() is None
            if empty:
                await backfill_tenancy(app.state.repo, app.state.tenancy)
        if (
            hasattr(app.state, "reconciler")
            and settings.mode != "off"
            and settings.reconciler_enabled
        ):
            app.state.reconciler.start()
        try:
            yield
        finally:
            if hasattr(app.state, "reconciler"):
                await app.state.reconciler.stop()
            await engine.dispose()

    app = FastAPI(title="Verifund Control Plane", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.clock = now
    app.state.repo = repo
    app.state.tenancy = tenancy
    app.state.agreement_repo = agreement_repo
    app.state.agreement_tokens = agreement_tokens
    app.state.agreement_service = agreement_service
    app.state.tokens = tokens
    app.state.buyer_tokens = buyer_tokens
    app.state.invitation_tokens = invitation_tokens
    app.state.service = service
    app.state.evidence_store = evidence_store
    app.state.links = links
    app.state.link_signer = links
    app.state.payments = payments
    app.state.receipts = receipts
    app.state.tracking = tracking
    app.state.reconciler = reconciler
    app.add_exception_handler(VerifundError, verifund_error_handler)
    app.include_router(health.router)
    app.include_router(ops.router)
    app.include_router(ops.router, prefix="/ops")
    app.include_router(seller.router)
    app.include_router(buyer.router)
    app.include_router(fulfillment.router)
    app.include_router(checkout.router)
    app.include_router(webhooks.router)
    app.include_router(agreement_routes.router)
    app.include_router(tenancy_routes.router)
    return app
