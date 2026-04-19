"""Environment-driven settings for all services."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "algobet"
    postgres_user: str = "algobet"
    postgres_password: str = "devpassword"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    service_name: str = Field(..., description="Identifier used for consumer groups and logs.")
    ingestion_mode: str = Field(
        default="betfair",
        description="Ingestion runtime mode: betfair for streaming, synthetic for one scaffold tick.",
    )
    betfair_username: str | None = Field(
        default=None, description="Betfair account username for certificate login."
    )
    betfair_password: str | None = Field(
        default=None, description="Betfair account password for certificate login."
    )
    betfair_app_key: str | None = Field(
        default=None, description="Betfair app key provisioned via developer program."
    )
    betfair_certs_dir: str | None = Field(
        default=None, description="Directory containing Betfair client cert/key files."
    )
    betfair_stream_conflate_ms: int = 0
    betfair_reconnect_delay_seconds: float = 5.0
    betfair_poll_interval_seconds: float = 0.25
    betfair_market_ids_csv: str = ""
    kalshi_api_key: str | None = Field(
        default=None, description="Kalshi API key for authenticated REST/WebSocket access."
    )
    kalshi_api_secret: str | None = Field(
        default=None, description="Kalshi API secret paired with the configured API key."
    )
    kalshi_environment: str | None = Field(
        default="demo", description="Kalshi environment selector (for example: demo, prod)."
    )

    @property
    def betfair_market_ids(self) -> list[str]:
        return [
            market_id.strip()
            for market_id in self.betfair_market_ids_csv.split(",")
            if market_id.strip()
        ]

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"
