"""Environment-driven settings for all services."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, field_validator
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
        description=(
            "Ingestion runtime mode: betfair for streaming, synthetic for one scaffold tick."
        ),
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

    # Risk manager settings — safe defaults leave existing services unaffected.
    risk_max_strategy_exposure_gbp: Decimal = Decimal("1000")
    risk_max_signal_liability_gbp: Decimal = Decimal("1000")
    risk_venue_notionals: dict[str, Decimal] = Field(default_factory=dict)
    risk_kill_switch: bool = False

    # Dashboard auth — session cookies default fail-closed (Secure=True).
    # Local dev over plain HTTP must opt out via DASHBOARD_INSECURE_COOKIES=1
    # in the fixture env, not in shipped defaults.
    session_ttl_seconds: int = 28800
    cookie_secure: bool = True
    cookie_samesite: Literal["lax", "strict"] = "lax"
    dashboard_allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:8000", "http://localhost:8000"]
    )
    login_rate_limit_ip: tuple[int, int] = (5, 300)
    login_rate_limit_email: tuple[int, int] = (10, 900)

    # Phase 6a historical loader — populates market_data_archive hypertable.
    historical_archive_dir: str | None = Field(
        default=None, description="Directory containing Betfair historical TAR files."
    )
    historical_load_batch_size: int = 5000

    @field_validator("dashboard_allowed_origins", mode="before")
    @classmethod
    def _parse_allowed_origins(cls, v: Any) -> Any:
        """Accept a JSON list or comma-separated string from env."""
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                return json.loads(stripped)
            return [part.strip() for part in stripped.split(",") if part.strip()]
        return v

    @field_validator("login_rate_limit_ip", "login_rate_limit_email", mode="before")
    @classmethod
    def _parse_rate_limit(cls, v: Any) -> Any:
        """Accept `"max,window"` or JSON `[max, window]` from env."""
        if isinstance(v, str):
            stripped = v.strip()
            parts = json.loads(stripped) if stripped.startswith("[") else stripped.split(",")
            if len(parts) != 2:
                raise ValueError("rate-limit setting must be `max,window`")
            return (int(parts[0]), int(parts[1]))
        return v

    @field_validator("risk_venue_notionals", mode="before")
    @classmethod
    def _parse_venue_notionals(cls, v: Any) -> Any:
        """Accept a JSON string from env (e.g. '{"betfair": "5000"}')."""
        if isinstance(v, str):
            parsed = json.loads(v)
            return {k: Decimal(str(val)) for k, val in parsed.items()}
        return v

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
