import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from verifund_control_plane.evidence import EvidenceStore
from verifund_control_plane.repository import Repository
from verifund_control_plane.tenancy.repository import TenancyRepository


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ev.db'}")
    repo = Repository(engine)
    await repo.create_schema()
    s = TenancyRepository(engine)
    await s.create_schema()
    yield s
    await engine.dispose()


@pytest.fixture
def evidence_store(tmp_path):
    return EvidenceStore(tmp_path / "evidence", max_bytes=10_000_000)


async def test_new_evidence_uses_the_tenant_prefix(store, evidence_store):
    item = await evidence_store.put(
        organization_id="org_1",
        transaction_id="vf_1",
        seller_id="acme",
        kind="invoice",
        media_type="application/pdf",
        original_filename="i.pdf",
        data=b"%PDF-1.4",
        note=None,
        captured_at=None,
    )
    assert item.storage_key == f"tenants/org_1/transactions/vf_1/{item.sha256}"
    assert (evidence_store.root / item.storage_key).exists()
