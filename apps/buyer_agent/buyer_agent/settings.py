from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from commerce_core.cards import DEFAULT_CARD_HOSTS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True
    )

    service_name: str = "buyer"
    host: str = "127.0.0.1"
    port: int = 9100
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
    llm_mode: Literal["scripted", "live"] = Field(
        default="scripted",
        validation_alias=AliasChoices("MARKETMESH_LLM_MODE", "LLM_MODE"),
    )
    openrouter_api_key: str | None = None
    openrouter_model: str = "deepseek/deepseek-v4.1-flash"
    seller_tokens: dict[str, str] = Field(
        default_factory=dict,
        validation_alias=AliasChoices(
            "BUYER_SELLER_TOKENS", "SELLER_TOKENS"
        ),
    )
