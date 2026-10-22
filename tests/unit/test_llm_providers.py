from buyer_agent.planner import (
    NebiusBuyerPlanner,
    ScriptedBuyerPlanner,
    select_buyer_planner,
)
from seller_agent.planner import (
    NebiusSellerPlanner,
    ScriptedSellerPlanner,
    select_seller_planner,
)


def test_buyer_selects_nebius_planner_when_live_and_configured() -> None:
    planner = select_buyer_planner(
        llm_mode="live",
        api_key="v1.test-key",
        base_url="https://api.tokenfactory.us-central1.nebius.com/v1/",
        model="deepseek-ai/DeepSeek-V4-Flash-0731",
    )

    assert isinstance(planner, NebiusBuyerPlanner)


def test_buyer_selects_scripted_planner_without_key() -> None:
    planner = select_buyer_planner(
        llm_mode="live",
        api_key=None,
        base_url="https://api.tokenfactory.us-central1.nebius.com/v1/",
        model="deepseek-ai/DeepSeek-V4-Flash-0731",
    )

    assert isinstance(planner, ScriptedBuyerPlanner)


def test_seller_selects_nebius_planner_when_live_and_configured() -> None:
    planner = select_seller_planner(
        llm_mode="live",
        api_key="v1.test-key",
        base_url="https://api.tokenfactory.us-central1.nebius.com/v1/",
        model="deepseek-ai/DeepSeek-V4-Flash-0731",
    )

    assert isinstance(planner, NebiusSellerPlanner)


def test_seller_selects_scripted_planner_without_key() -> None:
    planner = select_seller_planner(
        llm_mode="live",
        api_key=None,
        base_url="https://api.tokenfactory.us-central1.nebius.com/v1/",
        model="deepseek-ai/DeepSeek-V4-Flash-0731",
    )

    assert isinstance(planner, ScriptedSellerPlanner)
