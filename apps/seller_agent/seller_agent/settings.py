from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True
    )

    service_name: str = "seller"
    host: str = "127.0.0.1"
    port: int = Field(
        default=9201,
        validation_alias=AliasChoices("SELLER_PORT", "PORT"),
    )
    config_source: Literal["file", "shared"] = Field(
        default="file",
        validation_alias=AliasChoices("SELLER_CONFIG_SOURCE"),
    )
    shared_db_url: str = Field(
        default="sqlite+aiosqlite:///./data/sellers.db",
        validation_alias=AliasChoices("SELLER_SHARED_DB_URL"),
    )
    internal_api_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SELLER_INTERNAL_TOKEN"),
    )
    checkpoint_path: str = Field(
        default="./data/seller-checkpoints.sqlite",
        validation_alias=AliasChoices("SELLER_CHECKPOINT_PATH"),
    )
    demo_credentials_path: Path = Field(
        default=Path("data/demo-credentials.json"),
        validation_alias=AliasChoices("SELLER_DEMO_CREDENTIALS_PATH"),
    )
    credential_cache_ttl_seconds: float = Field(
        default=30.0,
        validation_alias=AliasChoices("SELLER_CREDENTIAL_CACHE_TTL_SECONDS"),
    )
    evidence_sweep_seconds: float = Field(
        default=2.0,
        validation_alias=AliasChoices("SELLER_EVIDENCE_SWEEP_SECONDS"),
    )
    profile_path: Path = Path("docs/templates/northwind.yaml")
    public_base_url: str = "http://127.0.0.1:9201"
    seller_token: str = "dev-seller"
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/seller.db",
        validation_alias=AliasChoices("SELLER_DATABASE_URL", "DATABASE_URL"),
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

    verifund_mode: Literal["off", "fake", "sandbox"] = Field(
        default="sandbox",
        validation_alias=AliasChoices("VERIFUND_MODE"),
    )
    verifund_url: str = Field(
        default="http://127.0.0.1:9300",
        validation_alias=AliasChoices("VERIFUND_URL", "SELLER_VERIFUND_URL"),
    )
    verifund_timeout_seconds: float = Field(
        default=20.0,
        validation_alias=AliasChoices("VERIFUND_TIMEOUT_SECONDS"),
    )
    verifund_settlement_internal_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VERIFUND_SETTLEMENT_INTERNAL_TOKEN",
            "SETTLEMENT_INTERNAL_TOKEN",
            "SELLER_VERIFUND_INTERNAL_TOKEN",
        ),
    )
    seller_organization_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "SELLER_ORGANIZATION_ID",
            "VERIFUND_SELLER_ORGANIZATION_ID",
        ),
    )
    verifund_auto_evidence: bool = Field(
        default=True,
        validation_alias=AliasChoices("VERIFUND_AUTO_EVIDENCE"),
    )
    verifund_evidence_retry_seconds: float = Field(
        default=2.0,
        validation_alias=AliasChoices("VERIFUND_EVIDENCE_RETRY_SECONDS"),
    )
