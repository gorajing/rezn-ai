"""AGENT_MEMORY_REQUIRED resilience override.

For an unattended public deploy, a transient Agent Memory outage should degrade to the
local taste fallback rather than refusing to boot. An explicit ``AGENT_MEMORY_REQUIRED=false``
opts out even under ``REZN_PRODUCTION=true``; unset/truthy keeps the strict default.
"""

from __future__ import annotations

from rezn_ai.config import agent_memory_required


def test_explicit_false_overrides_production(monkeypatch):
    monkeypatch.setenv("REZN_PRODUCTION", "true")
    monkeypatch.setenv("AGENT_MEMORY_REQUIRED", "false")
    assert agent_memory_required() is False


def test_production_requires_agent_memory_by_default(monkeypatch):
    monkeypatch.setenv("REZN_PRODUCTION", "true")
    monkeypatch.delenv("AGENT_MEMORY_REQUIRED", raising=False)
    assert agent_memory_required() is True


def test_explicit_true_without_production(monkeypatch):
    monkeypatch.delenv("REZN_PRODUCTION", raising=False)
    monkeypatch.setenv("AGENT_MEMORY_REQUIRED", "true")
    assert agent_memory_required() is True


def test_default_off_without_production(monkeypatch):
    monkeypatch.delenv("REZN_PRODUCTION", raising=False)
    monkeypatch.delenv("AGENT_MEMORY_REQUIRED", raising=False)
    assert agent_memory_required() is False
