from datetime import UTC, datetime, timedelta

import pytest
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.tokens import LinkSigner, SellerTokenService

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
SECRET = "s" * 40


def service(now=NOW):
    return SellerTokenService(SECRET, ttl_hours=72, clock=lambda: now)


def test_seller_token_round_trip_and_binding():
    issued = service().issue("vf_1", "northwind-audio", "a" * 64)
    claims = service().verify(issued.token, required_scope="evidence:write")
    assert claims.txn == "vf_1"
    assert claims.seller_id == "northwind-audio"
    assert claims.agreement_hash == "a" * 64
    assert claims.expires_at == NOW + timedelta(hours=72)


def test_seller_token_expires():
    issued = service().issue("vf_1", "northwind-audio", "a" * 64)
    later = SellerTokenService(SECRET, ttl_hours=72, clock=lambda: NOW + timedelta(hours=73))
    with pytest.raises(VerifundError) as raised:
        later.verify(issued.token)
    assert raised.value.code == "token_expired"


def test_seller_token_scope_is_enforced():
    issued = service().issue("vf_1", "northwind-audio", "a" * 64, scopes=["txn:read"])
    with pytest.raises(VerifundError) as raised:
        service().verify(issued.token, required_scope="evidence:write")
    assert raised.value.code == "token_scope_denied"


def test_seller_token_rejects_tampering():
    issued = service().issue("vf_1", "northwind-audio", "a" * 64)
    parts = issued.token.split(".")
    tampered = ".".join([parts[0], parts[1], parts[2][:-3] + "abc"])
    with pytest.raises(VerifundError) as raised:
        service().verify(tampered)
    assert raised.value.code == "unauthorized"


def test_link_signer_round_trip_and_kind():
    signer = LinkSigner(SECRET, checkout_ttl_minutes=30, return_ttl_hours=24, clock=lambda: NOW)
    link = signer.issue("checkout", "vf_1")
    claims = signer.verify(link.token, expected_kind="checkout")
    assert claims.transaction_id == "vf_1"
    with pytest.raises(VerifundError):
        signer.verify(link.token, expected_kind="return")
