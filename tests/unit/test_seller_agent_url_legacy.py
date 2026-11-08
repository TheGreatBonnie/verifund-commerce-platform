"""Failing-first for SELLER_AGENT_URL legacy → SELLER_SHARED_URL."""
from verifund_control_plane.settings import Settings


def test_seller_agent_url_defaults_to_shared_9200():
    # Default must not be legacy 9201
    s = Settings()
    assert s.seller_agent_url == "http://127.0.0.1:9200"


def test_seller_agent_url_reads_shared_env(monkeypatch):
    monkeypatch.setenv("SELLER_SHARED_URL", "http://seller-shared:9200")
    s = Settings()
    assert s.seller_agent_url == "http://seller-shared:9200"
