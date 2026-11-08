from pathlib import Path
from typing import Literal

from commerce_core.cards import DEFAULT_CARD_HOSTS
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True
    )

    service_name: str = "buyer"
    host: str = "127.0.0.1"
    port: int = Field(
        default=9100,
        validation_alias=AliasChoices("BUYER_PORT", "PORT"),
    )
    registry_url: str = "http://127.0.0.1:9105"
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/buyer.db",
        validation_alias=AliasChoices(
            "BUYER_DATABASE_URL", "DATABASE_URL"
        ),
    )
    checkpoint_path: Path = Field(
        default=Path("./data/buyer-checkpoints.db"),
        validation_alias=AliasChoices(
            "BUYER_CHECKPOINT_PATH", "CHECKPOINT_PATH"
        ),
    )
    allowed_card_hosts: tuple[str, ...] = Field(
        default=DEFAULT_CARD_HOSTS,
        validation_alias=AliasChoices(
            "ALLOWED_CARD_HOSTS", "BUYER_ALLOWED_CARD_HOSTS"
        ),
    )
    public_base_url: str = Field(
        default="http://127.0.0.1:9100",
        validation_alias=AliasChoices("BUYER_PUBLIC_BASE_URL", "PUBLIC_BASE_URL"),
    )
    llm_mode: Literal["scripted", "live"] = Field(
        default="scripted",
        validation_alias=AliasChoices("MARKETMESH_LLM_MODE", "LLM_MODE"),
    )
    nebius_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("NEBIUS_API_KEY"),
    )
    nebius_base_url: str = Field(
        default="https://api.tokenfactory.us-central1.nebius.com/v1/",
        validation_alias=AliasChoices("NEBIUS_BASE_URL"),
    )
    nebius_model: str = Field(
        default="deepseek-ai/DeepSeek-V4-Flash-0731",
        validation_alias=AliasChoices("NEBIUS_MODEL"),
    )
    seller_tokens: dict[str, str] = Field(
        default_factory=dict,
        validation_alias=AliasChoices(
            "BUYER_SELLER_TOKENS", "SELLER_TOKENS"
        ),
    )
    buyer_internal_token: str = Field(
        default="dev-buyer-internal",
        validation_alias=AliasChoices("BUYER_INTERNAL_TOKEN"),
    )
    buyer_registry_poll_seconds: int = Field(
        default=30,
        validation_alias=AliasChoices("BUYER_REGISTRY_POLL_SECONDS"),
    )
    seller_internal_token: str = Field(
        default="dev-seller-internal",
        validation_alias=AliasChoices("SELLER_INTERNAL_TOKEN"),
    )
    console_api_token: str = Field(
        default="dev-console",
        validation_alias=AliasChoices("BUYER_CONSOLE_API_TOKEN"),
    )
    verifund_mode: Literal["off", "fake", "sandbox"] = Field(
        default="sandbox",
        validation_alias=AliasChoices("VERIFUND_MODE"),
    )
    verifund_url: str = Field(
        default="http://127.0.0.1:9300",
        validation_alias=AliasChoices("VERIFUND_URL", "BUYER_VERIFUND_URL"),
    )
    verifund_ops_token: str = Field(
        default="dev-verifund-ops",
        validation_alias=AliasChoices("VERIFUND_OPS_TOKEN", "BUYER_VERIFUND_OPS_TOKEN"),
    )
    buyer_settlement_internal_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VERIFUND_BUYER_SETTLEMENT_INTERNAL_TOKEN",
            "BUYER_SETTLEMENT_INTERNAL_TOKEN",
        ),
    )
    buyer_clerk_user_id: str = Field(
        default="user_buyer",
        validation_alias=AliasChoices("BUYER_CLERK_USER_ID"),
    )
    verifund_timeout_seconds: float = Field(
        default=20.0,
        validation_alias=AliasChoices("VERIFUND_TIMEOUT_SECONDS"),
    )
    internal_api_token: str = Field(
        default="dev-buyer-internal",
        validation_alias=AliasChoices("BUYER_INTERNAL_TOKEN"),
    )
    verifund_agent_internal_token: str = Field(
        default="dev-verifund-agent-internal",
        validation_alias=AliasChoices("VERIFUND_AGENT_INTERNAL_TOKEN"),
    )
    console_base_url: str = Field(
        default="http://127.0.0.1:3000",
        validation_alias=AliasChoices("VERIFUND_CONSOLE_BASE_URL", "BUYER_CONSOLE_BASE_URL"),
    )
