from commerce_core.negotiation.schemas import PAYLOAD_NAMES, is_known_payload


def test_known_payloads():
    for name in ["rfq", "offer", "counter_offer", "accept_offer", "purchase_order", "order", "commerce_error"]:
        assert is_known_payload(name)
    assert "rfq" in PAYLOAD_NAMES
    assert not is_known_payload("not_a_payload")
