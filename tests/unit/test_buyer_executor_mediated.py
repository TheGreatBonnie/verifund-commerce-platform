from __future__ import annotations

import pytest
from buyer_agent.executor import BuyerExecutor
from buyer_agent.graph import build_mediated_buyer_graph
from buyer_agent.settings import Settings
from langgraph.checkpoint.memory import MemorySaver
from tests.support.fake_buyer import FakeServices


@pytest.fixture
def fake_services():
    return FakeServices()


def test_executor_constructs_with_mediated_graph(fake_services):
    settings = Settings(llm_mode="scripted")
    executor = BuyerExecutor(
        services=fake_services,
        settings=settings,
        checkpointer=MemorySaver(),
        graph=build_mediated_buyer_graph(
            services=fake_services, checkpointer=MemorySaver()
        ),
    )
    assert executor.graph is not None