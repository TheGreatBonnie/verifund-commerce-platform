"""Shared local-development configuration for MarketMesh."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _port(name: str, default: int) -> int:
    raw = _env(name, str(default))
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class SellerConfig:
    seller_id: str
    profile: str
    port_var: str
    token_var: str
    database_var: str
    default_port: int
    default_token: str
    default_database: str

    @property
    def port(self) -> int:
        return _port(self.port_var, self.default_port)

    @property
    def token(self) -> str:
        return _env(self.token_var, self.default_token)

    @property
    def database_url(self) -> str:
        return _env(self.database_var, self.default_database)

    @property
    def profile_path(self) -> Path:
        return ROOT / "apps/seller_agent/seller_agent/profiles" / self.profile

    @property
    def base_url(self) -> str:
        override = os.environ.get(
            f"{self.seller_id.upper().replace('-', '_')}_PUBLIC_BASE_URL"
        )
        if override:
            return override.rstrip("/")
        return f"http://127.0.0.1:{self.port}"

    @property
    def card_url(self) -> str:
        return f"{self.base_url}/.well-known/agent-card.json"

    @property
    def log_name(self) -> str:
        return f"seller-{self.seller_id}"


SELLERS = (
    SellerConfig(
        seller_id="northwind-audio",
        profile="northwind.yaml",
        port_var="NORTHWIND_PORT",
        token_var="SELLER_NORTHWIND_TOKEN",
        database_var="NORTHWIND_DATABASE_URL",
        default_port=9201,
        default_token="dev-northwind",
        default_database="sqlite+aiosqlite:///./data/northwind.db",
    ),
    SellerConfig(
        seller_id="circuitforge",
        profile="circuitforge.yaml",
        port_var="CIRCUITFORGE_PORT",
        token_var="SELLER_CIRCUITFORGE_TOKEN",
        database_var="CIRCUITFORGE_DATABASE_URL",
        default_port=9202,
        default_token="dev-circuitforge",
        default_database="sqlite+aiosqlite:///./data/circuitforge.db",
    ),
    SellerConfig(
        seller_id="aurora-supply",
        profile="aurora.yaml",
        port_var="AURORA_PORT",
        token_var="SELLER_AURORA_TOKEN",
        database_var="AURORA_DATABASE_URL",
        default_port=9203,
        default_token="dev-aurora",
        default_database="sqlite+aiosqlite:///./data/aurora.db",
    ),
)


def registry_url() -> str:
    return _env("REGISTRY_URL", f"http://127.0.0.1:{_port('REGISTRY_PORT', 9105)}")


def admin_token() -> str:
    return _env("REGISTRY_ADMIN_TOKEN", "dev-registry-admin")


def buyer_url() -> str:
    return _env("BUYER_API_URL", f"http://127.0.0.1:{_port('BUYER_PORT', 9100)}")


def buyer_agui_url() -> str:
    return _env("BUYER_AGUI_URL", f"{buyer_url()}/agui")


def console_port() -> int:
    return _port("CONSOLE_PORT", 3000)


def llm_mode() -> str:
    return _env("MARKETMESH_LLM_MODE", "scripted").strip().lower()


def nebius_api_key() -> str:
    return _env("NEBIUS_API_KEY", "").strip()


def nebius_base_url() -> str:
    return _env(
        "NEBIUS_BASE_URL",
        "https://api.tokenfactory.us-central1.nebius.com/v1/",
    ).rstrip("/")


def nebius_model() -> str:
    return _env(
        "NEBIUS_MODEL",
        "deepseek-ai/DeepSeek-V4-Flash-0731",
    ).strip()


def seller_tokens_json() -> str:
    configured = _env("BUYER_SELLER_TOKENS", "").strip()
    if configured:
        return configured
    import json

    return json.dumps({seller.seller_id: seller.token for seller in SELLERS})


def orchestrator_port() -> int:
    return _port("ORCHESTRATOR_PORT", 9000)


def orchestrator_url() -> str:
    return _env("ORCHESTRATOR_URL", f"http://127.0.0.1:{orchestrator_port()}")


def orchestrator_agui_url() -> str:
    return _env("ORCHESTRATOR_AGUI_URL", orchestrator_url())


def buyer_a2a_url() -> str:
    return _env("BUYER_A2A_URL", buyer_url().rstrip("/"))
