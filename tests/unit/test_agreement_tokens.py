from datetime import UTC, datetime

from verifund_control_plane.agreements.tokens import ApprovalTokenService

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def test_issue_verify_and_hash():
    svc = ApprovalTokenService(
        "secret-32-chars-minimum-xxxxxxxx", ttl_minutes=30, clock=lambda: NOW,
    )
    raw, record = svc.issue(
        "agr_1", 1, "a" * 64, "buyer-1", "buyer", "buyer-1", NOW,
    )
    claims = svc.verify(raw)
    assert claims["aud"] == "agreement-approval"
    assert claims["sub"] == "buyer-1"
    assert claims["agreement_id"] == "agr_1"
    assert claims["version"] == 1
    assert claims["agreement_hash"] == "a" * 64
    assert record.token_hash == ApprovalTokenService.token_hash(raw)


def test_token_expires_with_agreement_window():
    svc = ApprovalTokenService("secret-32-chars-minimum-xxxxxxxx", ttl_minutes=30)
    _raw, record = svc.issue(
        "agr_1", 1, "a" * 64, "buyer-1", "buyer", "buyer-1", NOW,
        agreement_expires_at=datetime(2026, 10, 30, 12, 5, tzinfo=UTC),
    )
    assert record.expires_at == datetime(2026, 10, 30, 12, 5, tzinfo=UTC)
