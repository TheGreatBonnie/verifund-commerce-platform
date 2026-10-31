from verifund_control_plane.agreements.renderer import (
    RENDERER_VERSION, render_agreement,
)


def test_renderer_deterministic():
    terms = {"schema": "verifund.agreement.v1", "agreement_type": "goods",
             "terms_version": 1, "platform_terms_version": "v1",
             "parties": {"buyer": {"id": "b", "display_name": "Buyer"},
                         "seller": {"id": "s", "display_name": "Seller"}},
             "offer": {"offer_id": "o1", "request_id": "r1", "offer_round": 1,
                       "offer_hash": "a" * 64, "offer_valid_until": "2026-11-01T00:00:00Z"},
             "items": [{"sku": "S", "name": "N", "quantity": 1,
                        "unit_price_cents": 100, "warranty_addon_cents": 0,
                        "line_total_cents": 100}],
             "totals": {"currency": "USD", "subtotal_cents": 100,
                        "shipping_cents": 0, "tax_cents": 0, "fees_cents": 0,
                        "total_cents": 100},
             "delivery": {"delivery_days": 3, "starts_on": "FUNDING_CONFIRMED"},
             "warranty_months": 12, "returns_days": 30,
             "inspection": {"period_hours": 48, "starts_on": "DELIVERY_CONFIRMED"},
             "evidence_required": ["delivery_confirmation"],
             "remedies": {"non_delivery": "cancel_and_refund",
                          "late_delivery": "cancel_and_refund",
                          "damaged_goods": "refund_or_replacement"},
             "dispute_window_hours": 72}
    out1 = render_agreement(terms, "agr_1", 1, "b" * 64)
    out2 = render_agreement(terms, "agr_1", 1, "b" * 64)
    assert out1 == out2
    assert "<table" in out1
    assert "agr_1" in out1 and "b" * 8 in out1
    assert "<script" not in out1


def test_renderer_escapes():
    terms = {"schema": "verifund.agreement.v1", "agreement_type": "goods",
             "terms_version": 1, "platform_terms_version": "v1",
             "parties": {"buyer": {"id": "b", "display_name": "<x>"},
                         "seller": {"id": "s", "display_name": "Seller"}},
             "offer": {"offer_id": "o1", "request_id": "r1", "offer_round": 1,
                       "offer_hash": "a" * 64, "offer_valid_until": "2026-11-01T00:00:00Z"},
             "items": [{"sku": "S", "name": "<y>", "quantity": 1,
                        "unit_price_cents": 100, "warranty_addon_cents": 0,
                        "line_total_cents": 100}],
             "totals": {"currency": "USD", "subtotal_cents": 100,
                        "shipping_cents": 0, "tax_cents": 0, "fees_cents": 0,
                        "total_cents": 100},
             "delivery": {"delivery_days": 3, "starts_on": "FUNDING_CONFIRMED"},
             "warranty_months": 12, "returns_days": 30,
             "inspection": {"period_hours": 48, "starts_on": "DELIVERY_CONFIRMED"},
             "evidence_required": ["delivery_confirmation"],
             "remedies": {"non_delivery": "cancel_and_refund",
                          "late_delivery": "cancel_and_refund",
                          "damaged_goods": "refund_or_replacement"},
             "dispute_window_hours": 72}
    out = render_agreement(terms, "agr_1", 1, "b" * 64)
    assert "<x>" not in out and "&lt;x&gt;" in out
    assert "<y>" not in out
