"""Failing-first for card_url public base (legacy agents.verifund.com)."""
from verifund_control_plane.settings import Settings


def test_agents_public_base_defaults_to_local_shared(monkeypatch):
    monkeypatch.delenv("AGENTS_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("SELLER_SHARED_URL", raising=False)
    monkeypatch.delenv("SELLER_AGENT_URL", raising=False)
    s = Settings()
    assert s.agents_public_base_url == "http://127.0.0.1:9200"
