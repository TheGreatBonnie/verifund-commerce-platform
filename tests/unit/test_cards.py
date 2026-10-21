from tests.support.cards import build_test_card

from commerce_core.cards import validate_agent_card


def test_valid_card_has_no_errors():
    assert validate_agent_card(build_test_card()) == []


def test_missing_commerce_extension_is_rejected():
    card = build_test_card()
    card.capabilities.extensions.clear()
    errors = validate_agent_card(card)
    assert any("extension" in error for error in errors)


def test_missing_bearer_scheme_is_rejected():
    card = build_test_card()
    card.security_schemes.clear()
    errors = validate_agent_card(card)
    assert any("bearer" in error for error in errors)
