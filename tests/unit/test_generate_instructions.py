"""Failing-first for auto-generate instructions."""
from verifund_control_plane.agents.routes import generate_instructions


def test_generate_instructions_mentions_name_and_bounds():
    text = generate_instructions(
        name="Acme Industrial",
        tagline="Industrial parts",
        allowlist=["commerce.quote", "commerce.negotiate"],
        max_discount_bps=1000,
        autonomy_mode="policy_bounded",
        categories=["Electronics", "Office"],
    )
    assert "Acme Industrial" in text
    assert "floor" in text.lower()
    assert len(text) <= 4096


def test_generate_instructions_empty_name_still_returns_text():
    text = generate_instructions(
        name="Seller agent",
        tagline="",
        allowlist=[],
        max_discount_bps=None,
        autonomy_mode=None,
        categories=[],
    )
    assert isinstance(text, str) and text
