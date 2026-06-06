"""Weave initialization helpers.

The real trace-bearing functions should live beside the orchestration code. This module exists so the
app has one place to initialize Weave and one place to report whether tracing is available.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_WEAVE_PROJECT = "rezn-ai/rezn-ai"


@dataclass(frozen=True)
class WeaveStatus:
    project: str
    available: bool
    initialized: bool
    reason: str


def default_env_path() -> Path:
    return Path(__file__).resolve().parents[3] / ".env"


def load_project_env(path: Path | None = None) -> list[str]:
    env_path = path or default_env_path()
    if not env_path.is_file():
        return []

    loaded: list[str] = []
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def default_project_name() -> str:
    load_project_env()
    return os.getenv("WEAVE_PROJECT", DEFAULT_WEAVE_PROJECT)


def initialize_weave(project: str | None = None) -> WeaveStatus:
    load_project_env()
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
