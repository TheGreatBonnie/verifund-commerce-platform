from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "seller"
    host: str = "127.0.0.1"
    port: int = 9201
    profile_path: Path = Path(
        "apps/seller_agent/seller_agent/profiles/northwind.yaml"
    )
    public_base_url: str = "http://127.0.0.1:9201"
    seller_token: str = "dev-seller"
    database_url: str = "sqlite+aiosqlite:///./data/seller.db"
    llm_mode: Literal["scripted", "live"] = "scripted"
    openrouter_api_key: str | None = None
    openrouter_model: str = "deepseek/deepseek-v4.1-flash"
