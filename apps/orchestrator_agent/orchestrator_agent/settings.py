from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True
    )

    service_name: str = "orchestrator"
    host: str = "127.0.0.1"
    port: int = Field(
        default=9000,
        validation_alias=AliasChoices("ORCHESTRATOR_PORT", "PORT"),
    )
    orchestrator_url: str = "http://127.0.0.1:9000"
    buyer_a2a_url: str = "http://127.0.0.1:9100"
    seller_northwind_token: str = Field(
        default="dev-northwind",
        validation_alias=AliasChoices("SELLER_NORTHWIND_TOKEN"),
    )
    seller_circuitforge_token: str = Field(
        default="dev-circuitforge",
        validation_alias=AliasChoices("SELLER_CIRCUITFORGE_TOKEN"),
    )
    seller_aurora_token: str = Field(
        default="dev-aurora",
        validation_alias=AliasChoices("SELLER_AURORA_TOKEN"),
    )
    seller_summit_tech_token: str = Field(
        default="dev-summit-tech",
        validation_alias=AliasChoices("SELLER_SUMMIT_TECH_TOKEN"),
    )
    llm_mode: str = Field(
        default="live",
        validation_alias=AliasChoices("MARKETMESH_LLM_MODE", "LLM_MODE"),
    )
    nebius_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("NEBIUS_API_KEY", "OPENAI_API_KEY"),
    )
    nebius_base_url: str = Field(
        default="https://api.tokenfactory.us-central1.nebius.com/v1/",
        validation_alias=AliasChoices("NEBIUS_BASE_URL", "OPENAI_BASE_URL"),
    )
    nebius_model: str = Field(
        default="deepseek-ai/DeepSeek-V4-Flash-0731",
        validation_alias=AliasChoices("NEBIUS_MODEL", "OPENAI_MODEL"),
    )

    buyer_internal_url: str = Field(
        default="http://127.0.0.1:9100",
        validation_alias=AliasChoices("BUYER_INTERNAL_URL"),
    )
    buyer_internal_token: str = Field(
        default="dev-buyer-internal",
        validation_alias=AliasChoices("BUYER_INTERNAL_TOKEN"),
    )
    buyer_internal_timeout_seconds: float = Field(
        default=10.0,
        validation_alias=AliasChoices("BUYER_INTERNAL_TIMEOUT_SECONDS"),
    )

    verifund_mode: str = Field(
        default="sandbox",
        validation_alias=AliasChoices("VERIFUND_MODE"),
    )
    verifund_agent_url: str = Field(
        default="http://127.0.0.1:9301",
        validation_alias=AliasChoices("VERIFUND_AGENT_URL"),
    )
    verifund_agent_a2a_token: str = Field(
        default="dev-verifund-agent-a2a",
        validation_alias=AliasChoices("VERIFUND_AGENT_A2A_TOKEN"),
    )
    verifund_agent_card_url: str = Field(
        default="http://127.0.0.1:9301/.well-known/agent-card.json",
        validation_alias=AliasChoices("VERIFUND_AGENT_CARD_URL"),
    )
    verifund_timeout_seconds: float = Field(
        default=60.0,
        validation_alias=AliasChoices("VERIFUND_AGENT_TIMEOUT_SECONDS"),
    )
    session_db_url: str = Field(
        default="sqlite+aiosqlite:///./data/orchestrator_sessions.db",
        validation_alias=AliasChoices("ORCHESTRATOR_SESSION_DB_URL"),
    )
