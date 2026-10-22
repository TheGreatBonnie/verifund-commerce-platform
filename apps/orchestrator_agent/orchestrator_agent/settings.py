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
