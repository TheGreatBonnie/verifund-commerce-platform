from commerce_core.negotiation.artifacts import build_negotiation_history_artifact


def test_negotiation_history_artifact_redacts_budget():
    payload = build_negotiation_history_artifact(
        [{"round": 1, "kind": "offer", "offer_id": "o1", "total_cents": 100, "source": "scripted"}],
        max_total_cents=9999,
    )
    text = str(payload)
    assert "9999" not in text
    assert "max_total_cents" not in text
    assert payload["turns"][0]["offer_id"] == "o1"
