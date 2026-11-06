import pytest
from buyer_agent.executor import BuyerExecutor
from buyer_agent.graph import memory_namespace, thread_id
from verifund_control_plane.errors import VerifundError


def test_thread_id_is_tenant_prefixed():
    assert thread_id("org_1", "run_1") == "org_1:run_1"


def test_memory_namespace_is_tenant_scoped():
    assert memory_namespace("org_1", "agent_1") == (
        "tenants",
        "org_1",
        "agents",
        "agent_1",
        "memory",
    )


class FakeTrace:
    def __init__(self):
        self.runs = {"run_1": {"run_id": "run_1", "organization_id": "org_a"}}

    async def get_run(self, run_id):
        return self.runs.get(run_id)


@pytest.fixture
def executor():
    ex = BuyerExecutor.__new__(BuyerExecutor)
    ex.services = type("S", (), {"trace": FakeTrace()})()
    return ex


async def test_resume_with_wrong_org_is_rejected(executor):
    with pytest.raises(VerifundError) as exc:
        await executor.resume("run_1", organization_id="org_b")
    assert exc.value.code == "not_found"


async def test_resume_with_matching_org_returns_config(executor):
    config = await executor.resume("run_1", organization_id="org_a")
    assert config["configurable"]["thread_id"] == "org_a:run_1"
