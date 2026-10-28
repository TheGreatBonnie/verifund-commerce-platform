from datetime import UTC, datetime

from verifund_control_plane.receipts import ReceiptSigner, build_receipt_payload

NOW = datetime(2026, 10, 27, 12, 34, 56, tzinfo=UTC)
KEYS = {"old-1": "o" * 40, "new-2": "n" * 40}


def payload():
    return build_receipt_payload(
        transaction_id="vf_1",
        agreement_hash="a" * 64,
        amount_cents=123400,
        currency="USD",
        buyer_id="demo-buyer",
        seller_id="northwind-audio",
        capture_id="CAP-1",
        payout_item_id="PAYOUT-1",
        evidence_hashes=["b" * 64],
        released_at=NOW,
    )


def test_receipt_signs_and_verifies_with_active_kid():
    signer = ReceiptSigner(KEYS, "new-2")
    signed = signer.sign(payload())
    assert signed.kid == "new-2"
    assert len(signed.payload_hash) == 64
    assert signer.verify(signed.payload, signed.payload_hash, signed.signature, signed.kid)


def test_old_key_still_verifies():
    old = ReceiptSigner(KEYS, "old-1").sign(payload())
    assert ReceiptSigner(KEYS, "new-2").verify(
        old.payload, old.payload_hash, old.signature, old.kid
    )


def test_tampered_payload_fails_verification():
    signed = ReceiptSigner(KEYS, "new-2").sign(payload())
    tampered = dict(signed.payload)
    tampered["amount_cents"] = 1
    assert not ReceiptSigner(KEYS, "new-2").verify(
        tampered, signed.payload_hash, signed.signature, signed.kid
    )
