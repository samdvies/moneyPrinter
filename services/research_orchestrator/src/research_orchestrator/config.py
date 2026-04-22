"""Service-local settings for the research orchestrator.

Standalone ``OrchestratorSettings`` — does NOT inherit from
``algobet_common.config.Settings`` to keep orchestrator-specific fields out of
the shared base class.  Both classes read from the same ``.env`` file so they
coexist without duplication.

Usage::

    from research_orchestrator.config import OrchestratorSettings
    settings = OrchestratorSettings()

All ``XAI_*`` and ``HYPOTHESIS_*`` fields are read from environment variables
(or ``.env``).  In the test suite, ``XAI_API_KEY`` is always ``"mock"`` so no
real HTTP calls are made.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OrchestratorSettings(BaseSettings):
    """Orchestrator-specific configuration.

    Required fields (no default):
    - ``xai_api_key``: set to ``"mock"`` in tests; real xAI key in production.

    All other fields have safe defaults.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # xAI API
    # ------------------------------------------------------------------

    xai_api_key: str = Field(
        ...,
        description=(
            "xAI API key.  Set to 'mock' in tests to activate cassette-replay "
            "mode (no HTTP round-trips)."
        ),
    )
    xai_base_url: str = Field(
        default="https://api.x.ai/v1",
        description="Base URL for the xAI OpenAI-compatible API.",
    )
    xai_model_ideation: str = Field(
        default="grok-4",
        description="Model used for the ideation (hypothesis generation) stage.",
    )
    xai_model_codegen: str = Field(
        default="grok-4-fast-reasoning",
        description="Model used for the code-generation stage.",
    )

    # ------------------------------------------------------------------
    # Budget guard
    # ------------------------------------------------------------------

    hypothesis_daily_usd_cap: float = Field(
        default=5.0,
        description=(
            "Maximum USD to spend on xAI calls per UTC calendar day.  "
            "LLMClient raises BudgetExceeded if the running total + estimate "
            "would exceed this cap."
        ),
    )

    # ------------------------------------------------------------------
    # Cassette (mock) configuration
    # ------------------------------------------------------------------

    xai_cassette_dir: Path | None = Field(
        default=None,
        description=(
            "Override the cassette fixture directory.  "
            "If None, the LLMClient defaults to the test fixture path.  "
            "Production code never hits mock mode because xai_api_key != 'mock'."
        ),
    )
