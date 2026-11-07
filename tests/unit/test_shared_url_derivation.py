from buyer_agent.registry_client import seller_catalog_url as buyer_catalog_url
from buyer_agent.registry_client import seller_dashboard_url as buyer_dashboard_url
from registry.api import seller_catalog_url, seller_path_base


def test_catalog_url_preserves_seller_prefix():
    card = "http://127.0.0.1:9200/northwind-audio/.well-known/agent-card.json"
    assert seller_path_base(card) == "http://127.0.0.1:9200/northwind-audio"
    assert seller_catalog_url(card) == (
        "http://127.0.0.1:9200/northwind-audio/api/catalog"
    )
    assert buyer_catalog_url(card) == (
        "http://127.0.0.1:9200/northwind-audio/api/catalog"
    )


def test_dashboard_url_preserves_seller_prefix():
    card = "http://127.0.0.1:9200/northwind-audio/.well-known/agent-card.json"
    assert buyer_dashboard_url(card) == (
        "http://127.0.0.1:9200/northwind-audio/api/console/dashboard"
    )


def test_file_mode_card_still_maps_to_root_paths():
    card = "http://127.0.0.1:9201/.well-known/agent-card.json"
    assert seller_catalog_url(card) == "http://127.0.0.1:9201/api/catalog"
    assert buyer_dashboard_url(card) == (
        "http://127.0.0.1:9201/api/console/dashboard"
    )
