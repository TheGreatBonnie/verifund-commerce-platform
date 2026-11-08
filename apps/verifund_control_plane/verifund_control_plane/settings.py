from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, PrivateAttr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRETS = {
    "dev-verifund-ops",
    "dev-verifund-seller-token-secret",
    "dev-verifund-link-secret",
    "dev-verifund-fake-webhook",
    "dev-1",
}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True, case_sensitive=False
    )

    _clerk_directory = PrivateAttr(default=None)

    mode: Literal["off", "fake", "sandbox"] = Field(
        default="sandbox", validation_alias="VERIFUND_MODE"
    )
    service_name: str = "verifund-control-plane"
    host: str = Field(default="127.0.0.1", validation_alias="HOST")
    port: int = Field(default=9300, validation_alias="VERIFUND_PORT")
    public_base_url: str = Field(
        default="http://127.0.0.1:9300", validation_alias="VERIFUND_PUBLIC_BASE_URL"
    )
    console_base_url: str = Field(
        default="http://127.0.0.1:3000", validation_alias="VERIFUND_CONSOLE_BASE_URL"
    )
    seller_agent_url: str = Field(
        default="http://127.0.0.1:9201", validation_alias="SELLER_AGENT_URL"
    )
    seller_internal_token: str | None = Field(
        default=None, validation_alias="SELLER_INTERNAL_TOKEN"
    )
    settlement_internal_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VERIFUND_SETTLEMENT_INTERNAL_TOKEN", "SETTLEMENT_INTERNAL_TOKEN"
        ),
    )
    buyer_settlement_internal_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VERIFUND_BUYER_SETTLEMENT_INTERNAL_TOKEN",
            "BUYER_SETTLEMENT_INTERNAL_TOKEN",
        ),
    )
    registry_url: str = Field(
        default="http://127.0.0.1:9100", validation_alias="REGISTRY_URL"
    )
    agents_public_base_url: str = Field(
        default="https://agents.verifund.com",
        validation_alias="AGENTS_PUBLIC_BASE_URL",
    )
    allow_public_bind: bool = Field(
        default=False, validation_alias="VERIFUND_ALLOW_PUBLIC_BIND"
    )

    ops_token: str = Field(
        default="dev-verifund-ops", validation_alias="VERIFUND_OPS_TOKEN"
    )
    seller_token_secret: str = Field(
        default="dev-verifund-seller-token-secret",
        validation_alias="VERIFUND_SELLER_TOKEN_SECRET",
    )
    link_secret: str = Field(
        default="dev-verifund-link-secret", validation_alias="VERIFUND_LINK_SECRET"
    )
    agreement_seller_acceptance_hours: int = Field(
        default=24, validation_alias="VERIFUND_AGREEMENT_SELLER_ACCEPTANCE_HOURS"
    )
    agreement_buyer_approval_hours: int = Field(
        default=24, validation_alias="VERIFUND_AGREEMENT_BUYER_APPROVAL_HOURS"
    )
    agreement_change_response_hours: int = Field(
        default=24, validation_alias="VERIFUND_AGREEMENT_CHANGE_RESPONSE_HOURS"
    )
    approval_token_ttl_minutes: int = Field(
        default=30, validation_alias="VERIFUND_APPROVAL_TOKEN_TTL_MINUTES"
    )
    receipt_keys: dict[str, str] = Field(
        default_factory=lambda: {"dev-1": "dev-verifund-receipt-key"},
        validation_alias="VERIFUND_RECEIPT_KEYS",
    )
    receipt_active_kid: str = Field(
        default="dev-1", validation_alias="VERIFUND_RECEIPT_ACTIVE_KID"
    )

    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/verifund.db",
        validation_alias="VERIFUND_DATABASE_URL",
    )
    evidence_dir: Path = Field(
        default=Path("./data/evidence"), validation_alias="VERIFUND_EVIDENCE_DIR"
    )
    max_evidence_bytes: int = Field(
        default=25_000_000, validation_alias="VERIFUND_MAX_EVIDENCE_BYTES"
    )

    seller_token_ttl_hours: int = Field(
        default=72, validation_alias="VERIFUND_SELLER_TOKEN_TTL_HOURS"
    )
    seller_token_ttl_minutes: int = Field(
        default=60, validation_alias="VERIFUND_SELLER_TOKEN_TTL_MINUTES"
    )
    seller_rate_limit_per_minute: int = Field(
        default=60, validation_alias="VERIFUND_SELLER_RATE_LIMIT_PER_MINUTE"
    )
    checkout_link_ttl_minutes: int = Field(
        default=30, validation_alias="VERIFUND_CHECKOUT_LINK_TTL_MINUTES"
    )
    return_link_ttl_hours: int = Field(
        default=24, validation_alias="VERIFUND_RETURN_LINK_TTL_HOURS"
    )
    evidence_deadline_hours: int = Field(
        default=72, validation_alias="VERIFUND_EVIDENCE_DEADLINE_HOURS"
    )
    inspection_window_hours: int = Field(
        default=24, validation_alias="VERIFUND_INSPECTION_WINDOW_HOURS"
    )
    funding_timeout_hours: int = Field(
        default=24, validation_alias="VERIFUND_FUNDING_TIMEOUT_HOURS"
    )
    payout_alert_hours: int = Field(
        default=1, validation_alias="VERIFUND_PAYOUT_ALERT_HOURS"
    )

    paypal_env: str = Field(default="sandbox", validation_alias="PAYPAL_ENV")
    paypal_api_base: str = Field(
        default="https://api-m.sandbox.paypal.com", validation_alias="PAYPAL_API_BASE"
    )
    paypal_client_id: str = Field(default="", validation_alias="PAYPAL_CLIENT_ID")
    paypal_client_secret: str = Field(
        default="", validation_alias="PAYPAL_CLIENT_SECRET"
    )
    paypal_webhook_id: str = Field(
        default="", validation_alias="PAYPAL_WEBHOOK_ID"
    )
    paypal_platform_email: str = Field(
        default="", validation_alias="PAYPAL_PLATFORM_EMAIL"
    )
    paypal_buyer_email: str = Field(
        default="", validation_alias="PAYPAL_BUYER_EMAIL"
    )
    seller_payout_emails: dict[str, str] = Field(
        default_factory=dict, validation_alias="VERIFUND_SELLER_PAYOUT_EMAILS"
    )
    seller_tokens: dict[str, str] = Field(
        default_factory=dict,
        validation_alias=AliasChoices(
            "VERIFUND_SELLER_AGENT_TOKENS", "SELLER_AGENT_TOKENS"),
    )
    buyer_agent_token: str = Field(
        default="dev-buyer-agent",
        validation_alias=AliasChoices("BUYER_AGENT_TOKEN"),
    )

    reconciler_enabled: bool = Field(
        default=True, validation_alias="VERIFUND_RECONCILER_ENABLED"
    )
    reconciler_pending_seconds: int = Field(
        default=30, validation_alias="VERIFUND_RECONCILER_PENDING_SECONDS"
    )
    reconciler_deadline_seconds: int = Field(
        default=60, validation_alias="VERIFUND_RECONCILER_DEADLINE_SECONDS"
    )
    reconciler_receipt_seconds: int = Field(
        default=300, validation_alias="VERIFUND_RECONCILER_RECEIPT_SECONDS"
    )
    reconciler_interval_seconds: int = Field(
        default=30, validation_alias="VERIFUND_RECONCILER_INTERVAL_SECONDS"
    )
    scan_pending_timeout_minutes: int = Field(
        default=60, validation_alias="VERIFUND_SCAN_PENDING_TIMEOUT_MINUTES"
    )
    fake_webhook_secret: str = Field(
        default="dev-verifund-fake-webhook",
        validation_alias="VERIFUND_FAKE_WEBHOOK_SECRET",
    )
    fake_payment_scenario: str = Field(
        default="success", validation_alias="VERIFUND_FAKE_SCENARIO"
    )
    tenancy_enabled: bool = Field(default=False, validation_alias="VERIFUND_TENANCY_ENABLED")
    clerk_webhook_secret: str = Field(
        default="", validation_alias="CLERK_WEBHOOK_SIGNING_SECRET"
    )
    clerk_secret_key: str = Field(default="", validation_alias="CLERK_SECRET_KEY")
    clerk_jwt_key: str = Field(default="", validation_alias="CLERK_JWT_KEY")
    marketmesh_dev_identity: str = Field(
        default="", validation_alias="MARKETMESH_DEV_IDENTITY"
    )
    verifund_auto_verify: bool = Field(
        default=False, validation_alias="VERIFUND_AUTO_VERIFY"
    )

    @property
    def is_sandbox(self) -> bool:
        return self.mode == "sandbox"

    @property
    def is_fake(self) -> bool:
        return self.mode == "fake"

    def payout_email_for(self, seller_id: str) -> str | None:
        return self.seller_payout_emails.get(seller_id)

    def require_strong_secret(self, name: str, value: str) -> None:
        if len(value.encode("utf-8")) < 32 or value in DEFAULT_SECRETS:
            raise ValueError(f"{name} must be at least 32 bytes and not a default")

    @model_validator(mode="after")
    def _validate_base(self) -> Settings:
        if self.mode == "off":
            return self
        if self.receipt_active_kid not in self.receipt_keys:
            raise ValueError("VERIFUND_RECEIPT_ACTIVE_KID must exist in VERIFUND_RECEIPT_KEYS")
        host = self.host.strip()
        if host not in LOOPBACK_HOSTS and not self.allow_public_bind:
            raise ValueError("non-loopback HOST requires VERIFUND_ALLOW_PUBLIC_BIND=1")
        return self

    def validate_for_mode(self) -> None:
        if self.mode != "sandbox":
            return
        self.require_strong_secret("VERIFUND_OPS_TOKEN", self.ops_token)
        self.require_strong_secret("VERIFUND_SELLER_TOKEN_SECRET", self.seller_token_secret)
        self.require_strong_secret("VERIFUND_LINK_SECRET", self.link_secret)
        if self.receipt_active_kid in DEFAULT_SECRETS:
            raise ValueError("VERIFUND_RECEIPT_ACTIVE_KID must not be a default")
        self.require_strong_secret(
            "VERIFUND_RECEIPT_KEYS value", self.receipt_keys[self.receipt_active_kid]
        )
        if not self.paypal_client_id or not self.paypal_client_secret:
            raise ValueError("PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET are required")
        if not self.paypal_webhook_id:
            raise ValueError("PAYPAL_WEBHOOK_ID is required")
        if not self.paypal_api_base.startswith("https://api-m.sandbox.paypal.com"):
            raise ValueError("PAYPAL_API_BASE must be the PayPal sandbox host")
        if urlsplit(self.paypal_api_base).hostname == "api-m.paypal.com":
            raise ValueError("live PayPal is not supported; use the sandbox host")
        if not self.public_base_url.startswith("https://"):
            raise ValueError("VERIFUND_PUBLIC_BASE_URL must be HTTPS in sandbox mode")
        if not self.seller_payout_emails:
            raise ValueError(
                "VERIFUND_SELLER_PAYOUT_EMAILS: seller payout emails are required for sandbox"
            )
        payout_emails = list(self.seller_payout_emails.values())
        if len(payout_emails) != len(set(payout_emails)):
            raise ValueError("seller payout emails must be unique")
        disallowed = {self.paypal_platform_email, self.paypal_buyer_email} - {""}
        if disallowed.intersection(payout_emails):
            raise ValueError("seller payout emails must not be platform/buyer accounts")
