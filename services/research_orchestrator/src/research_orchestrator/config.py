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

    # ------------------------------------------------------------------
    # Hypothesis cycle parameters
    # ------------------------------------------------------------------

    hypothesis_batch_size: int = Field(
        default=4,
        description="Number of strategy specs to generate per hypothesis cycle.",
    )
    hypothesis_prior_cycle_k: int = Field(
        default=3,
        description="Top-K and bottom-K prior strategies to include in ideation context.",
    )
    hypothesis_prior_cycle_n: int = Field(
        default=10,
        description="Maximum number of recent strategies to consider for prior-cycle context.",
    )
    hypothesis_sandbox_cpu_seconds: int = Field(
        default=60,
        description="CPU time limit (seconds) for the per-spec sandbox import check (Unix only).",
    )
    hypothesis_sandbox_mem_mb: int = Field(
        default=1024,
        description="Address-space limit (MiB) for the per-spec sandbox import check (Unix only).",
    )
    hypothesis_sandbox_wall_timeout_s: float = Field(
        default=30.0,
        description=(
            "Wall-clock timeout (seconds) for the per-spec sandbox check.  "
            "Shorter than cpu_seconds to guard infinite loops before the CPU "
            "signal fires."
        ),
    )
