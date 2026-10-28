from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True
    )
    service_name: str = "verifund-agent"
    host: str = Field(default="127.0.0.1", validation_alias=AliasChoices("HOST"))
    agent_port: int = Field(
        default=9301,
        validation_alias=AliasChoices("VERIFUND_AGENT_PORT", "PORT"),
    )
    public_url: str = Field(
        default="http://127.0.0.1:9301",
        validation_alias=AliasChoices("VERIFUND_AGENT_URL"),
    )
    a2a_token: str = Field(
        default="dev-verifund-agent-a2a",
        validation_alias=AliasChoices("VERIFUND_AGENT_A2A_TOKEN"),
    )
    buyer_base_url: str = Field(
        default="http://127.0.0.1:9100",
        validation_alias=AliasChoices(
            "BUYER_INTERNAL_URL",
            "VERIFUND_AGENT_BUYER_URL",
        ),
    )
    buyer_internal_token: str = Field(
        default="dev-verifund-agent-internal",
        validation_alias=AliasChoices("VERIFUND_AGENT_INTERNAL_TOKEN"),
    )
    request_timeout_seconds: float = Field(
        default=20.0,
        validation_alias=AliasChoices("VERIFUND_AGENT_TIMEOUT_SECONDS"),
    )
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/verifund-agent.db",
        validation_alias=AliasChoices(
            "VERIFUND_AGENT_DATABASE_URL", "DATABASE_URL"
        ),
    )
    checkpoint_path: Path = Field(
        default=Path("./data/verifund-agent-checkpoints.db"),
        validation_alias=AliasChoices(
            "VERIFUND_AGENT_CHECKPOINT_PATH", "CHECKPOINT_PATH"
        ),
    )
