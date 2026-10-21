from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    service_name: str = "registry"
    host: str = "127.0.0.1"
    port: int = 9105
    database_url: str = "sqlite+aiosqlite:///./data/registry.db"
    admin_token: str = "dev-registry-admin"
    allowed_card_hosts: tuple[str, ...] = (
        "127.0.0.1",
        "localhost",
        "northwind",
        "circuitforge",
        "aurora",
    )
