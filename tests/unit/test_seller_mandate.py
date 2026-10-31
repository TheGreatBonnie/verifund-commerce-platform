from seller_agent.mandate import load_mandate


def test_load_mandate_from_profile():
    profile = {"seller_id": "northwind", "mandate": {
        "version": 1, "auto_accept": True,
        "allowed_currencies": ["USD"], "max_total_cents": 500000,
        "min_warranty_months": 0, "max_warranty_months": 24,
        "min_returns_days": 0, "max_returns_days": 60,
        "max_inspection_period_hours": 72, "max_dispute_window_hours": 168,
    }}
    m = load_mandate(profile)
    assert m.version == 1 and m.auto_accept is True
    assert m.allows(currency="USD", total_cents=100000, warranty_months=12,
                   returns_days=30, inspection_period_hours=48,
                   dispute_window_hours=72) is True
    assert m.allows(total_cents=600000) is False
