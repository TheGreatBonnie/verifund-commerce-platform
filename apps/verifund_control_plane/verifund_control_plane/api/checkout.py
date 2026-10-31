from __future__ import annotations

import html

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from verifund_contracts import CancelReason, CancelRequest, TransactionState

from verifund_control_plane.errors import VerifundError

router = APIRouter()


def _service(request: Request):
    return request.app.state.service


def _claims(
    request: Request, token: str, *, expected_kind: str = "checkout"
):
    return request.app.state.link_signer.verify(
        token, expected_kind=expected_kind
    )


def _redirect(request: Request, run_id: str, status: str) -> RedirectResponse:
    base = request.app.state.settings.console_base_url.rstrip("/")
    return RedirectResponse(
        url=f"{base}/runs/{run_id}?funding={status}", status_code=303
    )


@router.get("/checkout/fake/{token}", response_class=HTMLResponse)
async def checkout_page(token: str, request: Request) -> str:
    claims = _claims(request, token)
    record = await request.app.state.repo.get_transaction(claims.transaction_id)
    if record.state != TransactionState.FUNDING_PENDING:
        return (
            "<html><body><h1>Payment is not pending</h1>"
            f"<p>State: {html.escape(record.state.value)}</p></body></html>"
        )
    amount = f"{record.amount_cents / 100:.2f}"
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Verifund fake checkout</title></head>
<body>
  <main>
    <h1>Verifund fake checkout</h1>
    <p>Seller: <strong>{html.escape(record.seller_id)}</strong></p>
    <p>Amount: <strong>USD {amount}</strong></p>
    <p>This page is a local fake. It collects no credentials.</p>
    <form method="post">
      <button type="submit" name="action" value="approve">Approve payment</button>
      <button type="submit" name="action" value="cancel">Cancel</button>
    </form>
  </main>
</body>
</html>"""


@router.post("/checkout/fake/{token}")
async def checkout_action(
    token: str, request: Request, action: str = Form(...)
) -> RedirectResponse:
    claims = _claims(request, token)
    service = _service(request)
    record = await request.app.state.repo.get_transaction(claims.transaction_id)
    if record.state != TransactionState.FUNDING_PENDING:
        return _redirect(request, record.run_id, record.state.value.lower())
    if action == "approve":
        order_id = (record.funding or {}).get("provider_order_id")
        if not order_id:
            raise VerifundError(
                "provider_unavailable", "funding order is not ready", status_code=503
            )
        capture = await request.app.state.payments.capture_order(
            str(order_id), idempotency_key=f"capture:{record.transaction_id}:v1"
        )
        await service.apply_capture(
            record.transaction_id, capture, actor="fake-checkout"
        )
        await request.app.state.repo.consume_checkout_link(
            claims.jti, request.app.state.clock()
        )
        current = await request.app.state.repo.get_transaction(
            record.transaction_id
        )
        status = "complete" if current.state == TransactionState.FUNDED else "failed"
        return _redirect(request, record.run_id, status)
    if action == "cancel":
        await service.cancel(
            record.transaction_id,
            CancelRequest(
                reason_code=CancelReason.BUYER_CANCELLED,
                note="fake checkout canceled",
            ),
            actor="fake-checkout",
            idempotency_key=f"cancel:{record.transaction_id}:checkout",
        )
        return _redirect(request, record.run_id, "canceled")
    raise VerifundError("invalid_request", "unknown checkout action", status_code=400)


@router.get("/return/{token}")
async def paypal_return(token: str, request: Request) -> RedirectResponse:
    claims = _claims(request, token, expected_kind="return")
    await request.app.state.repo.consume_checkout_link(
        claims.jti, request.app.state.clock()
    )
    try:
        await _service(request).refresh_funding(
            claims.transaction_id, actor="paypal-return"
        )
    except VerifundError:
        pass
    record = await request.app.state.repo.get_transaction(
        claims.transaction_id
    )
    funded_states = {
        TransactionState.FUNDED,
        TransactionState.FULFILLMENT_PENDING,
        TransactionState.VERIFICATION_PENDING,
        TransactionState.RELEASE_PERMITTED,
        TransactionState.PAYOUT_PENDING,
        TransactionState.RELEASED,
    }
    status = "complete" if record.state in funded_states else "pending"
    return _redirect(request, record.run_id, status)


@router.get("/cancel/{token}")
async def paypal_cancel(token: str, request: Request) -> RedirectResponse:
    claims = _claims(request, token, expected_kind="cancel")
    await request.app.state.repo.consume_checkout_link(
        claims.jti, request.app.state.clock()
    )
    service = _service(request)
    record = await request.app.state.repo.get_transaction(
        claims.transaction_id
    )
    if record.state == TransactionState.FUNDING_PENDING and not (
        record.funding or {}
    ).get("capture_id"):
        try:
            await service.cancel(
                claims.transaction_id,
                CancelRequest(
                    reason_code=CancelReason.BUYER_CANCELLED,
                    note="PayPal checkout canceled",
                ),
                actor="paypal-cancel",
                idempotency_key=f"cancel:{claims.transaction_id}:paypal",
            )
        except VerifundError:
            pass
    return _redirect(request, record.run_id, "canceled")