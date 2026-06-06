"""Weave initialization helpers.

The real trace-bearing functions should live beside the orchestration code. This module exists so the
app has one place to initialize Weave and one place to report whether tracing is available.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WeaveStatus:
    project: str
    available: bool
    initialized: bool
    reason: str


def default_project_name() -> str:
    return os.getenv("WEAVE_PROJECT", "rezn-ai-hackathon")


def initialize_weave(project: str | None = None) -> WeaveStatus:
    project_name = project or default_project_name()
    try:
        import weave  # type: ignore
    except ModuleNotFoundError:
        return WeaveStatus(project_name, available=False, initialized=False, reason="weave_not_installed")

    if not os.getenv("WANDB_API_KEY"):
        return WeaveStatus(project_name, available=True, initialized=False, reason="missing_wandb_api_key")

    weave.init(project_name)
    return WeaveStatus(project_name, available=True, initialized=True, reason="ok")


def weave_op(name: str | None = None) -> Any:
    try:
        import weave  # type: ignore
    except ModuleNotFoundError:
        return lambda fn: fn
    return weave.op(name=name) if name else weave.op()
