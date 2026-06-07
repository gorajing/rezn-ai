"""Weave initialization helpers.

The real trace-bearing functions should live beside the orchestration code. This module exists so the
app has one place to initialize Weave and one place to report whether tracing is available.
"""

from __future__ import annotations

import logging
import os
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_WEAVE_PROJECT = "rezn-ai/rezn-ai"

logger = logging.getLogger(__name__)
_AGENTS_WARNED = False


def _warn_agents_once(op: str, exc: Exception) -> None:
    """Surface the FIRST agentic-SDK failure (the SDK is public preview) once per
    process, so the Agents view silently going empty doesn't pass unnoticed."""
    global _AGENTS_WARNED
    if not _AGENTS_WARNED:
        _AGENTS_WARNED = True
        logger.warning("Weave Agents instrumentation disabled (%s failed: %s)", op, exc)


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


def _project_parts(project: str) -> tuple[str | None, str]:
    """Return ``(entity, project_name)`` for a W&B project string."""
    if "/" not in project:
        return None, project
    entity, name = project.split("/", 1)
    return entity or None, name


def _client_matches_project(client: Any, project: str) -> bool:
    """True when a normalized Weave client already targets ``project``.

    Weave normalizes ``entity/project`` into separate ``client.entity`` and
    ``client.project`` fields. Calling ``weave.init("entity/project")`` again
    compares the raw string against ``client.project`` internally and can flush
    the current client unnecessarily, so the app does that comparison itself.
    """
    entity, name = _project_parts(project)
    if getattr(client, "project", None) != name:
        return False
    if entity is not None and getattr(client, "entity", None) != entity:
        return False
    return True


def initialize_weave(project: str | None = None) -> WeaveStatus:
    global _WEAVE_CLIENT

    load_project_env()
    project_name = project or default_project_name()
    try:
        import weave  # type: ignore
    except ModuleNotFoundError:
        return WeaveStatus(project_name, available=False, initialized=False, reason="weave_not_installed")

    if not os.getenv("WANDB_API_KEY"):
        return WeaveStatus(project_name, available=True, initialized=False, reason="missing_wandb_api_key")

    try:
        current = weave.get_client()
        if current is not None and _client_matches_project(current, project_name):
            _WEAVE_CLIENT = current
            return WeaveStatus(project_name, available=True, initialized=True, reason="ok")
    except Exception:
        pass

    # A bad/expired key or an unreachable W&B must not take down API startup:
    # degrade to untraced rather than raising out of module import.
    try:
        _WEAVE_CLIENT = weave.init(project_name)
    except Exception as exc:  # noqa: BLE001 - report any init failure, keep serving
        return WeaveStatus(project_name, available=True, initialized=False, reason=f"init_failed:{type(exc).__name__}")
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


# ── Agents view: sessions & turns (Weave agentic SDK, public preview) ──────────
#
# The Agents / Conversations / Spans tabs are driven by the Weave *agentic* SDK
# (start_session / start_turn), which is SEPARATE from the @weave.op Traces tab.
# A turn emits an ``invoke_agent`` span carrying ``gen_ai.agent.name`` (which
# registers the agent) and the session's ``conversation.id`` (which groups turns
# into one Conversation). This API is public-preview and unstable across 0.52.x,
# so every call is guarded: real sessions/turns when Weave is initialized, and a
# no-op context manager otherwise — never raising into the request path.


def _agents_weave() -> Any:
    """Return the ``weave`` module iff the agentic Agents SDK is usable here, else None.

    Usable means: weave importable, exposes ``start_session``/``start_turn``, and a
    client is initialized (``get_client()`` is not None — a session needs a live
    client). Isolated into one patchable function so the helpers stay trivial and the
    real-SDK path is unit-testable. Never raises.
    """
    try:
        import weave  # type: ignore
    except Exception:
        return None
    if not (hasattr(weave, "start_session") and hasattr(weave, "start_turn")):
        return None
    try:
        if weave.get_client() is None:
            return None
    except Exception:
        return None
    return weave


def weave_session(
    *, agent_name: str, session_id: str, session_name: str = "", model: str = ""
) -> Any:
    """Open a Weave Agents *session* (a context manager) grouping all turns of one
    batch lineage into a single Conversation. No-op when the agentic SDK isn't usable.

    ``continue_parent_trace=False`` keeps each turn on its own OTel trace — the
    documented choice for the standalone Agents/Conversations view rather than
    nesting turns under an outer ``@weave.op`` call. Never raises into the request path.
    """
    weave = _agents_weave()
    if weave is None:
        return nullcontext()
    try:
        return weave.start_session(
            agent_name=agent_name,
            session_id=session_id,
            session_name=session_name,
            model=model,
            continue_parent_trace=False,
        )
    except Exception as exc:
        _warn_agents_once("start_session", exc)
        return nullcontext()


def weave_turn(*, user_message: str = "", agent_name: str = "", model: str = "") -> Any:
    """Open a Weave *turn* (a context manager) inside the current session. The turn
    emits the ``invoke_agent`` span that registers ``agent_name`` in the Agents view.
    No-op when the agentic SDK isn't usable; never raises into the request path.
    """
    weave = _agents_weave()
    if weave is None:
        return nullcontext()
    try:
        return weave.start_turn(user_message=user_message, agent_name=agent_name, model=model)
    except Exception as exc:
        _warn_agents_once("start_turn", exc)
        return nullcontext()


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


_WEAVE_CLIENT: Any = None


def _weave_client() -> Any:
    """The process-wide Weave client, initialized once and cached.

    ``add_call_feedback`` previously called ``weave.init`` on every curation action,
    re-handshaking with W&B each time and making real-Weave runs (e.g. the proof
    script) impractically slow. Caching the client keeps feedback to a single
    network round-trip per call.
    """
    global _WEAVE_CLIENT
    if _WEAVE_CLIENT is None:
        import weave  # type: ignore

        project_name = default_project_name()
        current = weave.get_client()
        if current is not None and _client_matches_project(current, project_name):
            _WEAVE_CLIENT = current
        else:
            if not os.getenv("WANDB_API_KEY"):
                raise RuntimeError("WANDB_API_KEY is required for Weave feedback")
            _WEAVE_CLIENT = weave.init(project_name)
    return _WEAVE_CLIENT


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
        client = _weave_client()
        call = client.get_call(call_id)
        if reaction:
            call.feedback.add_reaction(reaction)
        if note:
            call.feedback.add_note(note)
        return True
    except Exception:
        return False
