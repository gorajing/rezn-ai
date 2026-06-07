"""Agent orchestration package for bounded music candidate generation."""

from .roster import (
    BATCH_PIPELINE,
    COMPOSER_STRATEGIES,
    CURATION_ACTORS,
    REFINE_PIPELINE,
    orchestration_summary,
)

__all__ = [
    "BATCH_PIPELINE",
    "COMPOSER_STRATEGIES",
    "CURATION_ACTORS",
    "REFINE_PIPELINE",
    "orchestration_summary",
]
