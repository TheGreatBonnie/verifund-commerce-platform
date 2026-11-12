from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Gateway-level bind settings. Service-level settings live in each app."""

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True
    )

    host: str = Field(default="0.0.0.0", validation_alias="HOST")
    port: int = Field(default=10000, validation_alias="PORT")
