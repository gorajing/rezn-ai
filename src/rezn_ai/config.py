"""Project constants and deployment posture flags."""

from __future__ import annotations

import os

# ── Project layout ────────────────────────────────────────────────────────────

DEFAULT_RUNS_DIR = "runs"
DEFAULT_MIDI_DIR = "midi"
DEFAULT_RENDERS_DIR = "renders"
MANIFEST_NAME = "manifest.json"
ARRANGEMENT_NAME = "arrangement.json"
NOTES_NAME = "notes.md"

# ── Deployment posture ────────────────────────────────────────────────────────
#
# ``REZN_PRODUCTION=true`` is the master switch for deploy/live use. Individual
# ``*_REQUIRED`` flags still work on their own for partial strictness during dev.
#
# The hermetic test suite sets ``REZN_DISABLE_REDIS=1`` before import; validation
# is skipped in that mode so pytest never needs Redis Cloud or Agent Memory.


def is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def production_mode() -> bool:
    return is_truthy(os.getenv("REZN_PRODUCTION"))


def redis_required() -> bool:
    return production_mode() or is_truthy(os.getenv("REDIS_REQUIRED"))


def agent_memory_required() -> bool:
    # An explicit ``AGENT_MEMORY_REQUIRED=false`` opts out even under
    # ``REZN_PRODUCTION=true``: taste memory then degrades to the local fallback
    # instead of failing the whole deploy when the managed Agent Memory service is
    # unavailable. Unset (or a truthy value) keeps the strict production default.
    explicit = os.getenv("AGENT_MEMORY_REQUIRED")
    if explicit is not None and not is_truthy(explicit):
        return False
    return production_mode() or is_truthy(explicit)


def inference_required() -> bool:
    return production_mode() or is_truthy(os.getenv("REZN_INFERENCE_REQUIRED"))


def deep_mode_requested() -> bool:
    """The operator asked for the multi-agent LLM ensemble (lens critics + judge)."""
    return is_truthy(os.getenv("REZN_DEEP_MODE"))


def deep_mode_enabled() -> bool:
    """True only when deep mode is requested AND live inference is actually available.
    Requested-but-unavailable is handled (fail loud) at the call site, not here."""
    if not deep_mode_requested():
        return False
    from .agents.llm_agents import inference_enabled

    return inference_enabled()


def validate_deployment() -> None:
    """Fail fast at API startup when production posture is violated."""
    if is_truthy(os.getenv("REZN_DISABLE_REDIS")):
        return  # hermetic tests — never block the suite

    errors: list[str] = []

    if production_mode():
        from .agents.llm_agents import inference_enabled

        if not inference_enabled():
            errors.append(
                "REZN_PRODUCTION=true requires live inference "
                "(REZN_ENABLE_INFERENCE=1 and WANDB_API_KEY or OPENAI_API_KEY)"
            )

    if errors:
        raise RuntimeError("Production deployment misconfigured:\n  • " + "\n  • ".join(errors))
