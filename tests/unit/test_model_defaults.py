"""The model the agents call by default has to exist on the public endpoint.

A default that was removed from Token Factory Serverless fails every model
call with "You do not have access to model ...". The defaults are pinned here
so that removal is caught by the suite rather than in production.
"""
from __future__ import annotations

import pytest
from buyer_agent.settings import Settings as BuyerSettings
from orchestrator_agent.settings import Settings as OrchestratorSettings
from seller_agent.settings import Settings as SellerSettings

# Removed from Token Factory Serverless on 2026-11-09; see
# https://docs.tokenfactory.nebius.com/november-2026-deprecation-notice.md
REMOVED_FROM_SERVERLESS = (
    "deepseek-ai/DeepSeek-V4-Flash-0731",
    "deepseek-ai/DeepSeek-V4-Flash",
    "deepseek-ai/DeepSeek-V4.1-Flash",
    "zai-org/GLM-5.1",
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    "nvidia/nemotron-3-super-120b-a12b",
    "Qwen/Qwen3-235B-A22B-Instruct-2507",
    "moonshotai/Kimi-K2.6",
    "moonshotai/Kimi-K2.7-Code",
)

# The region that serves the whole public text-to-text catalog.
CATALOG_REGION = "eu-north1"


@pytest.mark.parametrize(
    ("settings_cls",),
    ((BuyerSettings,), (SellerSettings,), (OrchestratorSettings,)),
)
def test_the_default_model_is_not_removed_from_serverless(settings_cls) -> None:
    model = settings_cls(_env_file=None).nebius_model

    assert model not in REMOVED_FROM_SERVERLESS, (
        f"{model} was removed from Token Factory Serverless on 2026-11-09"
    )


@pytest.mark.parametrize(
    ("settings_cls",),
    ((BuyerSettings,), (SellerSettings,), (OrchestratorSettings,)),
)
def test_the_default_endpoint_serves_the_public_catalog(settings_cls) -> None:
    base_url = settings_cls(_env_file=None).nebius_base_url

    assert CATALOG_REGION in base_url, (
        "the catalog region serves every public text-to-text model"
    )


def test_the_buyer_uses_the_shared_model_by_default() -> None:
    settings = BuyerSettings(_env_file=None)

    assert settings.buyer_model == settings.nebius_model


def test_the_local_stack_default_model_is_not_removed_from_serverless(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import config

    monkeypatch.delenv("NEBIUS_MODEL", raising=False)

    assert config.nebius_model() not in REMOVED_FROM_SERVERLESS
