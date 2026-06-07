"""W&B Weave Agents-SDK instrumentation (session/turn).

The Agents/Conversations/Spans views are driven by the Weave *agentic* SDK
(start_session/start_turn), separate from the @weave.op Traces tab. These helpers
must emit real sessions/turns when Weave is initialized, and degrade to clean
no-ops when it is not — the graceful-degradation invariant (tests run hermetic,
with no WANDB key, so the no-op path is what runs here). The real-session path is
verified at runtime against the live project, not in unit tests.
"""

from __future__ import annotations

import types

import rezn_ai.tracing.weave_client as wc
from rezn_ai.tracing.weave_client import weave_session, weave_turn


def test_session_helper_is_noop_when_weave_unavailable():
    # Hermetic env: Weave is not initialized -> must be a usable, do-nothing
    # context manager that never raises.
    with weave_session(agent_name="rezn-conductor", session_id="batch_x", session_name="x"):
        pass
    with weave_session(agent_name="a", session_id="b"):  # repeatable
        pass


def test_turn_helper_is_noop_when_weave_unavailable():
    with weave_turn(user_message="dark techno", agent_name="rezn-conductor"):
        pass


def test_session_helper_opens_real_session_when_available(monkeypatch):
    """When the agentic SDK is usable, the helper opens a session with the right
    args, including continue_parent_trace=False (each turn its own OTel trace —
    the documented choice for the standalone Agents tab)."""
    seen: dict = {}

    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    fake = types.SimpleNamespace(
        start_session=lambda **kw: (seen.update(kw) or _FakeSession()),
        get_client=lambda: object(),
    )
    monkeypatch.setattr(wc, "_agents_weave", lambda: fake)
    with weave_session(agent_name="rezn-conductor", session_id="batch_x", session_name="lab"):
        pass
    assert seen["agent_name"] == "rezn-conductor"
    assert seen["session_id"] == "batch_x"
    assert seen["continue_parent_trace"] is False


def test_turn_helper_opens_real_turn_when_available(monkeypatch):
    seen: dict = {}

    class _FakeTurn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    fake = types.SimpleNamespace(
        start_turn=lambda **kw: (seen.update(kw) or _FakeTurn()),
        get_client=lambda: object(),
    )
    monkeypatch.setattr(wc, "_agents_weave", lambda: fake)
    with weave_turn(user_message="brief text", agent_name="rezn-conductor"):
        pass
    assert seen["agent_name"] == "rezn-conductor"
    assert seen["user_message"] == "brief text"
