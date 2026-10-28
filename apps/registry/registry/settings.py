from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True
    )
    service_name: str = "registry"
    host: str = "127.0.0.1"
    port: int = Field(
        default=9105,
        validation_alias=AliasChoices("REGISTRY_PORT", "PORT"),
    )
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/registry.db",
        validation_alias=AliasChoices(
            "REGISTRY_DATABASE_URL", "DATABASE_URL"
        ),
    )
    admin_token: str = "dev-registry-admin"
    allowed_card_hosts: tuple[str, ...] = (
        "127.0.0.1",
        "localhost",
        "northwind",
        "circuitforge",
        "aurora",
        "summit-tech",
        "buyer",
        "verifund-agent",
        "host.docker.internal",
    )
