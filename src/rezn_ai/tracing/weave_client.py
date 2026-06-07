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


def weave_workspace_url(project: str | None = None) -> str | None:
    """The W&B Weave workspace URL for the project (``entity/project``), or None.

    A batch/project-level link the UI can surface today; per-call deep links can
    layer on later via the Weave call API.
    """
    project_name = project or default_project_name()
    if "/" not in project_name:
        return None
    entity, name = project_name.split("/", 1)
    return f"https://wandb.ai/{entity}/{name}/weave"


def weave_call_url(call_id: str | None, project: str | None = None) -> str | None:
    """Deep link to a single Weave call (the exact generation trace), or None."""
    if not call_id:
        return None
    project_name = project or default_project_name()
    if "/" not in project_name:
        return None
    entity, name = project_name.split("/", 1)
    return f"https://wandb.ai/{entity}/{name}/r/call/{call_id}"


def weave_op(name: str | None = None) -> Any:
    try:
        import weave  # type: ignore
    except ModuleNotFoundError:
        return lambda fn: fn
    return weave.op(name=name) if name else weave.op()


# ── Human-in-the-loop feedback on traced calls ────────────────────────────────
#
# These let curation (approve / reject / variant / final) attach the human signal
# to the exact Weave call that generated a candidate, so the producer's judgment
# becomes first-class trace data: queryable, chartable, and usable to build
# evaluation datasets from real usage. Feedback is observability — it is always
# best-effort and never raises into the request path, even in production.


def current_call_id() -> str | None:
    """The id of the Weave call currently executing (inside an ``@weave.op``)."""
    try:
        import weave  # type: ignore

        call = weave.get_current_call()
        return getattr(call, "id", None) if call is not None else None
    except Exception:
        return None


def add_call_feedback(
    call_id: str | None, *, reaction: str | None = None, note: str | None = None
) -> bool:
    """Attach a reaction emoji and/or a note to a Weave call. Best-effort.

    Returns True when at least one piece of feedback was recorded. Safe to call
    when Weave is unavailable or tracing is off — it simply returns False.
    """
    if not call_id or (reaction is None and note is None):
        return False
    try:
        import weave  # type: ignore

        client = weave.init(default_project_name())
        call = client.get_call(call_id)
        if reaction:
            call.feedback.add_reaction(reaction)
        if note:
            call.feedback.add_note(note)
        return True
    except Exception:
        return False
