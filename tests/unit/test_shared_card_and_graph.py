from commerce_core.pricing import load_policy
from langgraph.checkpoint.memory import MemorySaver
from seller_agent.card import build_agent_card
from seller_agent.graph import build_graph

PROFILE = "docs/templates/northwind.yaml"


def test_card_advertises_shared_url_and_tenant():
    policy = load_policy(PROFILE)
    card = build_agent_card(
        policy, "http://127.0.0.1:9200/northwind-audio",
        tenant="agent_northwind-audio")
    interface = card.supported_interfaces[0]
    assert interface.url == "http://127.0.0.1:9200/northwind-audio/a2a"
    assert interface.tenant == "agent_northwind-audio"


def test_card_without_tenant_keeps_empty_value():
    policy = load_policy(PROFILE)
    card = build_agent_card(policy, "http://127.0.0.1:9201")
    assert card.supported_interfaces[0].tenant == ""
    assert card.supported_interfaces[0].url == "http://127.0.0.1:9201/a2a"


def test_graph_accepts_an_injected_checkpointer():
    graph = build_graph(checkpointer=MemorySaver())
    assert graph is not None
