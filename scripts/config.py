"""Shared local-development configuration for MarketMesh."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path | None = None) -> None:
    """Load local .env values into the process environment.

    Kept out of module import so libraries and tests importing this module do
    not mutate ``os.environ`` as a side effect.
    """
    load_dotenv(path or ROOT / ".env")


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
    token_var: str
    default_token: str

    @property
    def token(self) -> str:
        return _env(self.token_var, self.default_token)

    @property
    def profile_path(self) -> Path:
        return ROOT / "apps/seller_agent/seller_agent/profiles" / self.profile


SELLERS = (
    SellerConfig(
        seller_id="northwind-audio",
        profile="northwind.yaml",
        token_var="SELLER_NORTHWIND_TOKEN",
        default_token="dev-northwind",
    ),
    SellerConfig(
        seller_id="circuitforge",
        profile="circuitforge.yaml",
        token_var="SELLER_CIRCUITFORGE_TOKEN",
        default_token="dev-circuitforge",
    ),
    SellerConfig(
        seller_id="aurora-supply",
        profile="aurora.yaml",
        token_var="SELLER_AURORA_TOKEN",
        default_token="dev-aurora",
    ),
    SellerConfig(
        seller_id="summit-tech",
        profile="summit-tech.yaml",
        token_var="SELLER_SUMMIT_TECH_TOKEN",
        default_token="dev-summit-tech",
    ),
)

VERIFUND_MODES = {"off", "fake", "sandbox"}

SELLER_PAYOUT_EMAILS = {
    "northwind-audio": "seller-northwind@example.com",
    "circuitforge": "seller-circuitforge@example.com",
    "aurora-supply": "seller-aurora@example.com",
    "summit-tech": "seller-summit@example.com",
}


def verifund_mode() -> str:
    mode = _env("VERIFUND_MODE", "sandbox").strip().lower()
    return mode if mode in VERIFUND_MODES else "off"


def verifund_port() -> int:
    return _port("VERIFUND_PORT", 9300)


def verifund_agent_port() -> int:
    return _port("VERIFUND_AGENT_PORT", 9301)


def verifund_agent_url() -> str:
    return _env(
        "VERIFUND_AGENT_URL",
        f"http://127.0.0.1:{verifund_agent_port()}",
    ).rstrip("/")


def verifund_agent_card_url() -> str:
    return _env(
        "VERIFUND_AGENT_CARD_URL",
        f"{verifund_agent_url()}/.well-known/agent-card.json",
    )


def verifund_agent_a2a_token() -> str:
    return _env("VERIFUND_AGENT_A2A_TOKEN", "dev-verifund-agent-a2a")


def verifund_agent_internal_token() -> str:
    return _env(
        "VERIFUND_AGENT_INTERNAL_TOKEN", "dev-verifund-agent-internal"
    )


def verifund_agent_database_url() -> str:
    return _env(
        "VERIFUND_AGENT_DATABASE_URL",
        "sqlite+aiosqlite:///./data/verifund-agent.db",
    )


def verifund_agent_checkpoint_path() -> str:
    return _env(
        "VERIFUND_AGENT_CHECKPOINT_PATH",
        "./data/verifund-agent-checkpoints.db",
    )


def verifund_url() -> str:
    return _env(
        "VERIFUND_URL",
        _env(
            "VERIFUND_CONTROL_PLANE_URL",
            f"http://127.0.0.1:{verifund_port()}",
        ),
    ).rstrip("/")


def verifund_public_base_url() -> str:
    return _env("VERIFUND_PUBLIC_BASE_URL", verifund_url()).rstrip("/")


def verifund_console_base_url() -> str:
    return _env(
        "VERIFUND_CONSOLE_BASE_URL",
        f"http://127.0.0.1:{console_port()}",
    ).rstrip("/")


def verifund_ops_token() -> str:
    return _env("VERIFUND_OPS_TOKEN", "dev-verifund-ops")


def buyer_internal_token() -> str:
    return _env("BUYER_INTERNAL_TOKEN", "dev-buyer-internal")


def verifund_database_url() -> str:
    return _env(
        "VERIFUND_DATABASE_URL",
        "sqlite+aiosqlite:///./data/verifund.db",
    )


def verifund_evidence_dir() -> str:
    return _env("VERIFUND_EVIDENCE_DIR", "./data/evidence")


def verifund_seller_token_secret() -> str:
    return _env(
        "VERIFUND_SELLER_TOKEN_SECRET",
        "dev-verifund-seller-token-secret",
    )


def verifund_link_secret() -> str:
    return _env("VERIFUND_LINK_SECRET", "dev-verifund-link-secret")


def verifund_receipt_keys() -> str:
    return _env(
        "VERIFUND_RECEIPT_KEYS",
        '{"dev-1":"dev-verifund-receipt-key"}',
    )


def verifund_receipt_active_kid() -> str:
    return _env("VERIFUND_RECEIPT_ACTIVE_KID", "dev-1")


def verifund_fake_webhook_secret() -> str:
    return _env("VERIFUND_FAKE_WEBHOOK_SECRET", "dev-verifund-fake-webhook")


def verifund_timeout_seconds() -> float:
    raw = _env("VERIFUND_TIMEOUT_SECONDS", "20")
    try:
        return float(raw)
    except ValueError:
        return 20.0


def verifund_auto_evidence() -> str:
    return _env("VERIFUND_AUTO_EVIDENCE", "true")


def verifund_evidence_retry_seconds() -> str:
    return _env("VERIFUND_EVIDENCE_RETRY_SECONDS", "2")


def verifund_inspection_window_hours() -> int:
    default = "0" if verifund_mode() == "fake" else "24"
    raw = _env("VERIFUND_INSPECTION_WINDOW_HOURS", default)
    try:
        return max(0, int(raw))
    except ValueError:
        return int(default)


def seller_payout_emails() -> str:
    configured = _env("VERIFUND_SELLER_PAYOUT_EMAILS", "").strip()
    if not configured:
        return json.dumps(SELLER_PAYOUT_EMAILS, sort_keys=True)
    try:
        overrides = json.loads(configured)
    except json.JSONDecodeError:
        return configured
    if not isinstance(overrides, dict):
        return configured
    merged = dict(SELLER_PAYOUT_EMAILS)
    merged.update({str(key): str(value) for key, value in overrides.items()})
    return json.dumps(merged, sort_keys=True)


def paypal_env() -> str:
    return _env("PAYPAL_ENV", "sandbox")


def paypal_api_base() -> str:
    return _env("PAYPAL_API_BASE", "https://api-m.sandbox.paypal.com")


def paypal_webhook_id() -> str:
    return _env("PAYPAL_WEBHOOK_ID", "")


def paypal_platform_email() -> str:
    return _env("PAYPAL_PLATFORM_EMAIL", "")


def paypal_buyer_email() -> str:
    return _env("PAYPAL_BUYER_EMAIL", "")





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

    tokens = {seller.seller_id: buyer_agent_token() for seller in SELLERS}
    if configured:
        try:
            overrides = json.loads(configured)
        except json.JSONDecodeError:
            return configured
        if not isinstance(overrides, dict):
            return configured
        tokens.update(overrides)
    return json.dumps(tokens)


def shared_seller_port() -> int:
    return _port("SELLER_SHARED_PORT", 9200)


def shared_seller_url() -> str:
    return _env(
        "SELLER_SHARED_URL",
        f"http://127.0.0.1:{shared_seller_port()}",
    ).rstrip("/")


def shared_seller_db_url() -> str:
    return _env(
        "SELLER_SHARED_DB_URL",
        "sqlite+aiosqlite:///./data/sellers.db",
    )


def seller_internal_token() -> str:
    return _env("SELLER_INTERNAL_TOKEN", "dev-seller-internal")


def buyer_agent_token() -> str:
    return _env("BUYER_AGENT_TOKEN", "dev-buyer-agent")


def seller_checkpoint_path() -> str:
    return _env("SELLER_CHECKPOINT_PATH", "./data/seller-checkpoints.sqlite")


def shared_card_url(seller_id: str) -> str:
    return f"{shared_seller_url()}/{seller_id}/.well-known/agent-card.json"


def orchestrator_port() -> int:
    return _port("ORCHESTRATOR_PORT", 9000)


def orchestrator_url() -> str:
    return _env("ORCHESTRATOR_URL", f"http://127.0.0.1:{orchestrator_port()}")


def orchestrator_agui_url() -> str:
    return _env("ORCHESTRATOR_AGUI_URL", orchestrator_url())


def buyer_a2a_url() -> str:
    return _env("BUYER_A2A_URL", buyer_url().rstrip("/"))
