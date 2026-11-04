from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.evidence import EvidenceStore

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> EvidenceStore:
    return EvidenceStore(tmp_path / "evidence", max_bytes=32)


async def test_put_is_content_addressed_and_idempotent(store):
    first = await store.put(
        transaction_id="vf_1",
        seller_id="northwind-audio",
        kind="shipment_manifest",
        media_type="application/json",
        original_filename="manifest.json",
        data=b'{"tracking_number":"TRK-1"}',
        note=None,
        captured_at=None,
    )
    second = await store.put(
        transaction_id="vf_1",
        seller_id="northwind-audio",
        kind="shipment_manifest",
        media_type="application/json",
        original_filename="manifest-copy.json",
        data=b'{"tracking_number":"TRK-1"}',
        note=None,
        captured_at=None,
    )
    assert first.sha256 == second.sha256
    assert first.evidence_id != second.evidence_id
    assert (store.root / first.sha256).read_bytes() == b'{"tracking_number":"TRK-1"}'
    assert store.verify(first.sha256)


async def test_put_rejects_oversized_and_unsupported(store):
    with pytest.raises(VerifundError) as raised:
        await store.put(
            transaction_id="vf_1",
            seller_id="northwind-audio",
            kind="shipment_manifest",
            media_type="application/json",
            original_filename="big.json",
            data=b"x" * 33,
            note=None,
            captured_at=None,
        )
    assert raised.value.code == "evidence_too_large"

    with pytest.raises(VerifundError) as raised:
        await store.put(
            transaction_id="vf_1",
            seller_id="northwind-audio",
            kind="shipment_manifest",
            media_type="application/zip",
            original_filename="x.zip",
            data=b"x",
            note=None,
            captured_at=None,
        )
    assert raised.value.code == "unsupported_media_type"


async def test_put_rejects_unknown_kind(store):
    with pytest.raises(VerifundError) as raised:
        await store.put(
            transaction_id="vf_1",
            seller_id="northwind-audio",
            kind="made_up",
            media_type="text/plain",
            original_filename="x.txt",
            data=b"x",
            note=None,
            captured_at=None,
        )
    assert raised.value.code == "invalid_request"