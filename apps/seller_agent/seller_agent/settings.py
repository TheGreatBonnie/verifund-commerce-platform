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
    profile_path: Path = Path(
        "apps/seller_agent/seller_agent/profiles/northwind.yaml"
    )
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
