from typing import ClassVar

import pytest_asyncio
from seller_agent.shared_review_store import OrgScopedAgreementReviewStore
from seller_agent.shared_schema import configure_shared_engine, create_shared_schema
from sqlalchemy.ext.asyncio import create_async_engine


class Projection:
    agreement_id = "agr-1"
    agreement_version = 1
    agreement_hash = "ah"
    terms: ClassVar[dict] = {"total": 100}
    change_request_id = None


@pytest_asyncio.fixture
async def engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/sellers.db")
    await configure_shared_engine(engine)
    await create_shared_schema(engine)
    yield engine
    await engine.dispose()


def test_reviews_are_org_scoped(engine):
    a = OrgScopedAgreementReviewStore(engine, "org-a")
    b = OrgScopedAgreementReviewStore(engine, "org-b")
    a.record(Projection(), "oh", decision="accepted",
             now="2026-01-01T00:00:00Z", task_id="t", context_id="c")
    assert a.get("agr-1", 1)["decision"] == "accepted"
    assert b.get("agr-1", 1) is None
    assert a.list("agr-1")[0]["organization_id"] == "org-a"
    assert b.list("agr-1") == []
