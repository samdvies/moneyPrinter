"""xAI LLM client with mock (cassette) backend and budget guard.

Phase 6c — this module wraps the OpenAI-compatible xAI API for two operations:

* ``ideate`` — calls ``grok-4`` in JSON mode to produce a list of
  :class:`~research_orchestrator.types.StrategySpec` hypotheses.
* ``codegen`` — calls ``grok-4-fast-reasoning`` to generate Python source for
  a given :class:`~research_orchestrator.types.StrategySpec`.

Mock mode
---------
When ``settings.xai_api_key == "mock"`` the client reads pre-recorded JSON
cassettes from ``settings.xai_cassette_dir`` (or the default fixture path).
No HTTP calls are made.  All tests use mock mode.

Budget guard
------------
Every call first checks ``spend_tracker.would_exceed(estimate, cap)`` before
any HTTP round-trip.  The estimate is derived from the prompt length (tokens ≈
``len(prompt) / 4``) plus a fixed output allocation.  If the estimate would
push daily spend over the cap, :class:`BudgetExceeded` is raised immediately.

Retry policy
------------
Ideation: on a parse or schema error, retry once with a lower temperature
(``0.3``), then raise :class:`LLMResponseInvalid`.
Codegen: single-shot — failures propagate immediately.

Cassette file format
--------------------
See ``tests/fixtures/llm_cassettes/*.json``.  The schema is:

.. code-block:: json

    {
      "name": "<cassette-name>",
      "request": { ... },
      "response": {
        "choices": [{"message": {"content": "..."}}],
        "usage": {"prompt_tokens": N, "completion_tokens": M}
      }
    }

Cassette name resolution
------------------------
Callers may pass ``cassette_name`` explicitly.  Defaults:
* ``ideate`` → ``"ideation_default"``
* ``codegen(spec)`` → ``"codegen_<spec.name>"``
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, cast

from research_orchestrator.config import OrchestratorSettings
from research_orchestrator.spend_tracker import SpendTracker
from research_orchestrator.types import IdeationContext, ParamRange, StrategySpec

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default output-token allocations for cost estimation (before the call)
# ---------------------------------------------------------------------------

_IDEATION_OUTPUT_TOKEN_ESTIMATE = 1500
_CODEGEN_OUTPUT_TOKEN_ESTIMATE = 500

# Default cassette directory (relative to THIS source file, two levels up to tests/).
# Production code never reaches this because xai_api_key != "mock" in prod.
_DEFAULT_CASSETTE_DIR = Path(__file__).parents[4] / "tests" / "fixtures" / "llm_cassettes"

# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------


class BudgetExceeded(RuntimeError):
    """Raised when an LLM call would push daily spend over the configured cap.

    Attributes
    ----------
    estimated_usd:
        The estimated cost (USD) of the call that was blocked.
    cap_usd:
        The daily cap (USD) that would have been exceeded.
    cumulative_usd:
        The cumulative spend already recorded today.
    """

    def __init__(self, estimated_usd: float, cap_usd: float, cumulative_usd: float) -> None:
        self.estimated_usd = estimated_usd
        self.cap_usd = cap_usd
        self.cumulative_usd = cumulative_usd
        super().__init__(
            f"Budget guard: call would cost ~${estimated_usd:.4f} but "
            f"daily spend is already ${cumulative_usd:.4f} / ${cap_usd:.2f} cap."
        )


class LLMResponseInvalid(RuntimeError):
    """Raised when the LLM response cannot be parsed or validated.

    Raised after the retry budget is exhausted (for ideation) or on the first
    failure (for codegen).
    """

    def __init__(self, message: str, raw_content: str | None = None) -> None:
        self.raw_content = raw_content
        super().__init__(message)


class CassetteNotFoundError(FileNotFoundError):
    """Raised when a cassette file cannot be located.

    The error message includes the resolved path that was looked up so callers
    know exactly where to put the fixture.
    """

    def __init__(self, cassette_name: str, cassette_dir: Path) -> None:
        self.cassette_name = cassette_name
        self.cassette_dir = cassette_dir
        path = cassette_dir / f"{cassette_name}.json"
        super().__init__(f"Cassette '{cassette_name}' not found.  " f"Expected file: {path}")


# ---------------------------------------------------------------------------
# Cassette helpers
# ---------------------------------------------------------------------------


def _resolve_cassette_dir(settings: OrchestratorSettings) -> Path:
    """Return the cassette directory, preferring ``settings.xai_cassette_dir``."""
    if settings.xai_cassette_dir is not None:
        return settings.xai_cassette_dir
    return _DEFAULT_CASSETTE_DIR


def _load_cassette(name: str, cassette_dir: Path) -> dict[str, Any]:
    """Load and parse a cassette JSON file.

    Parameters
    ----------
    name:
        Cassette name without the ``.json`` suffix.
    cassette_dir:
        Directory to look in.

    Returns
    -------
    dict
        Parsed cassette dict.

    Raises
    ------
    CassetteNotFoundError
        If the file does not exist.
    LLMResponseInvalid
        If the file exists but contains malformed JSON or is missing the
        expected ``response.choices[0].message.content`` path.
    """
    path = cassette_dir / f"{name}.json"
    if not path.exists():
        raise CassetteNotFoundError(name, cassette_dir)

    try:
        raw = path.read_text(encoding="utf-8")
        data: dict[str, Any] = cast(dict[str, Any], json.loads(raw))
    except json.JSONDecodeError as exc:
        raise LLMResponseInvalid(
            f"Cassette '{name}' contains malformed JSON: {exc}",
            raw_content=None,
        ) from exc

    # Structural validation — we need choices[0].message.content and usage.
    try:
        _extract_content(data)
        _extract_usage(data)
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMResponseInvalid(
            f"Cassette '{name}' has unexpected shape: {exc}",
            raw_content=str(data),
        ) from exc

    return data


def _extract_content(cassette: dict[str, Any]) -> str:
    """Return the content string from cassette response choices[0]."""
    return str(cassette["response"]["choices"][0]["message"]["content"])


def _extract_usage(cassette: dict[str, Any]) -> tuple[int, int]:
    """Return (prompt_tokens, completion_tokens) from cassette usage."""
    usage = cassette["response"]["usage"]
    return int(usage["prompt_tokens"]), int(usage["completion_tokens"])


# ---------------------------------------------------------------------------
# Internal schema helpers for ideation response
# ---------------------------------------------------------------------------


def _parse_ideation_content(content: str) -> list[StrategySpec]:
    """Parse the JSON envelope from an ideation response.

    Raises
    ------
    LLMResponseInvalid
        If the content is not valid JSON, is missing ``hypotheses``, or any
        hypothesis is missing required fields.
    """
    try:
        envelope = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMResponseInvalid(
            f"Ideation response is not valid JSON: {exc}",
            raw_content=content,
        ) from exc

    if "hypotheses" not in envelope:
        raise LLMResponseInvalid(
            "Ideation response JSON is missing the 'hypotheses' key.",
            raw_content=content,
        )

    hypotheses = envelope["hypotheses"]
    if not isinstance(hypotheses, list):
        raise LLMResponseInvalid(
            f"'hypotheses' must be a list, got {type(hypotheses).__name__}.",
            raw_content=content,
        )

    specs: list[StrategySpec] = []
    for i, raw in enumerate(hypotheses):
        try:
            spec = _build_strategy_spec(raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMResponseInvalid(
                f"Hypothesis #{i} has invalid shape: {exc}",
                raw_content=json.dumps(raw),
            ) from exc
        specs.append(spec)

    return specs


def _build_strategy_spec(raw: dict[str, Any]) -> StrategySpec:
    """Construct a StrategySpec from a raw dict, raising on missing fields."""
    required = {
        "name",
        "rationale",
        "signal_formula",
        "params",
        "entry_rules",
        "exit_rules",
        "expected_edge",
    }
    missing = required - set(raw.keys())
    if missing:
        raise KeyError(f"Missing required fields: {sorted(missing)}")

    params: dict[str, ParamRange] = {}
    for param_name, param_raw in raw["params"].items():
        params[param_name] = ParamRange(
            kind=param_raw["kind"],
            low=float(param_raw["low"]),
            high=float(param_raw["high"]),
            default=float(param_raw["default"]),
        )

    return StrategySpec(
        name=str(raw["name"]),
        rationale=str(raw["rationale"]),
        signal_formula=str(raw["signal_formula"]),
        params=params,
        entry_rules=str(raw["entry_rules"]),
        exit_rules=str(raw["exit_rules"]),
        expected_edge=str(raw["expected_edge"]),
    )


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------


def _estimate_input_tokens(prompt: str) -> int:
    """Rough token count estimate: 1 token ≈ 4 characters."""
    return max(1, len(prompt) // 4)


def _strip_code_fence(content: str) -> str:
    """Strip a surrounding markdown code fence if present.

    Grok routinely wraps codegen output in ``` ```python ... ``` ``` fences.
    The AST validator expects raw Python source, so unwrap the fence here.
    Idempotent when no fence is present.
    """
    s = content.strip()
    if not s.startswith("```"):
        return content
    lines = s.splitlines()
    # Drop first line (``` or ```python) and last line if it is the closing fence.
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1])
    return "\n".join(lines[1:])


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------


class LLMClient:
    """Two-stage LLM client: ideation (hypothesis generation) + codegen.

    Parameters
    ----------
    settings:
        Orchestrator settings.  ``settings.xai_api_key == "mock"`` activates
        cassette-replay mode.
    spend_tracker:
        Injected spend tracker.  ``record()`` is called after every successful
        call (mock or live) so the daily budget stays accurate in tests too.

    Notes
    -----
    The OpenAI client is lazily instantiated on first live call so that mock
    mode never touches the ``openai`` HTTP machinery.
    """

    def __init__(self, settings: OrchestratorSettings, spend_tracker: SpendTracker) -> None:
        self._settings = settings
        self._tracker = spend_tracker
        self._cassette_dir = _resolve_cassette_dir(settings)
        self._is_mock = settings.xai_api_key == "mock"
        self._openai_client: Any = None  # lazy; None in mock mode

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ideate(
        self,
        context: IdeationContext,
        cassette_name: str | None = None,
    ) -> list[StrategySpec]:
        """Generate strategy hypotheses from the assembled ideation context.

        Parameters
        ----------
        context:
            Assembled four-layer context (see :class:`IdeationContext`).
        cassette_name:
            Explicit cassette name to use in mock mode.  Defaults to
            ``"ideation_default"``.

        Returns
        -------
        list[StrategySpec]
            Parsed hypotheses from the LLM response.

        Raises
        ------
        BudgetExceeded
            If the daily budget cap would be exceeded by this call.
        LLMResponseInvalid
            If the response cannot be parsed after the retry budget is
            exhausted.
        """
        effective_cassette = cassette_name if cassette_name is not None else "ideation_default"
        model = self._settings.xai_model_ideation

        system_prompt = context.static
        user_prompt = self._build_ideation_user_prompt(context)
        full_prompt = system_prompt + "\n" + user_prompt

        estimated_usd = self._estimate_cost(
            model=model,
            prompt=full_prompt,
            output_tokens=_IDEATION_OUTPUT_TOKEN_ESTIMATE,
        )
        self._guard_budget(estimated_usd)

        return self._ideate_with_retry(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            full_prompt=full_prompt,
            estimated_usd=estimated_usd,
            cassette_name=effective_cassette,
            max_retries=1,
        )

    def codegen(
        self,
        spec: StrategySpec,
        cassette_name: str | None = None,
    ) -> str:
        """Generate Python source code for a single strategy spec.

        Parameters
        ----------
        spec:
            The strategy specification to generate code for.
        cassette_name:
            Explicit cassette name to use in mock mode.  Defaults to
            ``"codegen_<spec.name>"``.

        Returns
        -------
        str
            Python source string (not validated here; callers should pass it
            through :func:`~research_orchestrator.ast_validator.validate`).

        Raises
        ------
        BudgetExceeded
            If the daily budget cap would be exceeded by this call.
        LLMResponseInvalid
            If the response content is empty or unparseable.
        """
        effective_cassette = cassette_name if cassette_name is not None else f"codegen_{spec.name}"
        model = self._settings.xai_model_codegen

        system_prompt = "You are a Python trading strategy code generator."
        user_prompt = self._build_codegen_user_prompt(spec)
        full_prompt = system_prompt + "\n" + user_prompt

        estimated_usd = self._estimate_cost(
            model=model,
            prompt=full_prompt,
            output_tokens=_CODEGEN_OUTPUT_TOKEN_ESTIMATE,
        )
        self._guard_budget(estimated_usd)

        if self._is_mock:
            return self._codegen_mock(
                model=model,
                full_prompt=full_prompt,
                cassette_name=effective_cassette,
            )

        return self._codegen_live(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            full_prompt=full_prompt,
        )

    # ------------------------------------------------------------------
    # Internal: ideation
    # ------------------------------------------------------------------

    def _ideate_with_retry(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        full_prompt: str,
        estimated_usd: float,
        cassette_name: str,
        max_retries: int,
    ) -> list[StrategySpec]:
        """Call the LLM (or cassette) with retry-on-parse-error for ideation."""
        attempt = 0
        last_exc: LLMResponseInvalid | None = None
        temperatures = [0.7, 0.3]  # first attempt, retry

        while attempt <= max_retries:
            temperature = temperatures[min(attempt, len(temperatures) - 1)]
            try:
                if self._is_mock:
                    specs, prompt_tokens, completion_tokens = self._ideate_mock(
                        cassette_name=cassette_name,
                    )
                else:
                    specs, prompt_tokens, completion_tokens = self._ideate_live(
                        model=model,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        temperature=temperature,
                    )

                # Successful call — record spend and return
                self._tracker.record(
                    model=model,
                    input_tokens=prompt_tokens,
                    output_tokens=completion_tokens,
                )
                return specs

            except LLMResponseInvalid as exc:
                last_exc = exc
                logger.warning(
                    "Ideation response invalid on attempt %d/%d: %s",
                    attempt + 1,
                    max_retries + 1,
                    exc,
                )
                attempt += 1

        # All attempts exhausted
        assert last_exc is not None
        raise last_exc

    def _ideate_mock(
        self,
        cassette_name: str,
    ) -> tuple[list[StrategySpec], int, int]:
        """Load cassette and parse ideation response."""
        cassette = _load_cassette(cassette_name, self._cassette_dir)
        content = _extract_content(cassette)
        prompt_tokens, completion_tokens = _extract_usage(cassette)
        specs = _parse_ideation_content(content)
        return specs, prompt_tokens, completion_tokens

    def _ideate_live(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
    ) -> tuple[list[StrategySpec], int, int]:
        """Make a live API call and parse the ideation response."""
        client = self._get_openai_client()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=temperature,
        )
        content = response.choices[0].message.content or ""
        prompt_tokens = response.usage.prompt_tokens if response.usage else 0
        completion_tokens = response.usage.completion_tokens if response.usage else 0
        specs = _parse_ideation_content(content)
        return specs, prompt_tokens, completion_tokens

    # ------------------------------------------------------------------
    # Internal: codegen
    # ------------------------------------------------------------------

    def _codegen_mock(
        self,
        *,
        model: str,
        full_prompt: str,
        cassette_name: str,
    ) -> str:
        """Load cassette and return the codegen content string."""
        cassette = _load_cassette(cassette_name, self._cassette_dir)
        content = _extract_content(cassette)
        prompt_tokens, completion_tokens = _extract_usage(cassette)
        if not content.strip():
            raise LLMResponseInvalid(
                f"Cassette '{cassette_name}' returned empty codegen content.",
                raw_content=content,
            )
        self._tracker.record(
            model=model,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
        )
        return content

    def _codegen_live(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        full_prompt: str,
    ) -> str:
        """Make a live codegen API call and return the source string."""
        client = self._get_openai_client()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content or ""
        prompt_tokens = response.usage.prompt_tokens if response.usage else 0
        completion_tokens = response.usage.completion_tokens if response.usage else 0
        if not content.strip():
            raise LLMResponseInvalid(
                "Live codegen response was empty.",
                raw_content=content,
            )
        self._tracker.record(
            model=model,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
        )
        return _strip_code_fence(content)

    # ------------------------------------------------------------------
    # Internal: prompt builders
    # ------------------------------------------------------------------

    @staticmethod
    def _build_ideation_user_prompt(context: IdeationContext) -> str:
        """Assemble the user-facing ideation prompt from context layers."""
        features_block = "\n".join(f"- {f}" for f in context.features)
        prior_block = context.prior_cycles if context.prior_cycles else "(none)"
        regime_block = context.regime if context.regime else "(unknown)"
        return (
            f"Available features:\n{features_block}\n\n"
            f"Prior cycles:\n{prior_block}\n\n"
            f"Current regime:\n{regime_block}\n\n"
            "Generate 4 trading strategy hypotheses as a JSON object with a "
            "'hypotheses' key containing a list."
        )

    @staticmethod
    def _build_codegen_user_prompt(spec: StrategySpec) -> str:
        """Assemble the codegen user prompt for a single StrategySpec."""
        param_lines = "\n".join(
            f"  {k}: {v.kind}, [{v.low}, {v.high}], default={v.default}"
            for k, v in spec.params.items()
        )
        return (
            f"Strategy name: {spec.name}\n"
            f"Rationale: {spec.rationale}\n"
            f"Signal formula: {spec.signal_formula}\n"
            f"Parameters:\n{param_lines}\n"
            f"Entry rules: {spec.entry_rules}\n"
            f"Exit rules: {spec.exit_rules}\n\n"
            "Generate a Python function ``compute_signal(snapshot, params)`` "
            "that returns a float signal or None.  Use only whitelisted builtins."
        )

    # ------------------------------------------------------------------
    # Internal: budget + cost
    # ------------------------------------------------------------------

    def _estimate_cost(self, *, model: str, prompt: str, output_tokens: int) -> float:
        """Estimate the USD cost before making a call."""
        from research_orchestrator.spend_tracker import MODEL_PRICING

        if model not in MODEL_PRICING:
            # Unknown model — be conservative and estimate as grok-4 price.
            logger.warning("Unknown model '%s' for cost estimation; using grok-4 pricing.", model)
            pricing = MODEL_PRICING["grok-4"]
        else:
            pricing = MODEL_PRICING[model]

        input_tokens = _estimate_input_tokens(prompt)
        return (
            input_tokens * pricing.input_per_million + output_tokens * pricing.output_per_million
        ) / 1_000_000

    def _guard_budget(self, estimated_usd: float) -> None:
        """Raise BudgetExceeded if the estimate would push spend over the cap."""
        cap = self._settings.hypothesis_daily_usd_cap
        if self._tracker.would_exceed(estimated_usd, cap):
            cumulative = self._tracker.cumulative_today_usd()
            raise BudgetExceeded(
                estimated_usd=estimated_usd,
                cap_usd=cap,
                cumulative_usd=cumulative,
            )

    # ------------------------------------------------------------------
    # Internal: OpenAI client (lazy, live only)
    # ------------------------------------------------------------------

    def _get_openai_client(self) -> Any:
        """Return (or lazily instantiate) the OpenAI client for live mode."""
        if self._openai_client is None:
            from openai import OpenAI

            self._openai_client = OpenAI(
                api_key=self._settings.xai_api_key,
                base_url=self._settings.xai_base_url,
            )
        return self._openai_client
