"""Production posture flags."""

from __future__ import annotations

import pytest

from rezn_ai.config import (
    agent_memory_required,
    inference_required,
    is_truthy,
    production_mode,
    redis_required,
    validate_deployment,
)


def test_production_mode(monkeypatch):
    monkeypatch.delenv("REZN_PRODUCTION", raising=False)
    assert production_mode() is False
    monkeypatch.setenv("REZN_PRODUCTION", "true")
    assert production_mode() is True


def test_required_flags_follow_production(monkeypatch):
    monkeypatch.delenv("REDIS_REQUIRED", raising=False)
    monkeypatch.delenv("AGENT_MEMORY_REQUIRED", raising=False)
    monkeypatch.delenv("REZN_INFERENCE_REQUIRED", raising=False)
    monkeypatch.delenv("REZN_PRODUCTION", raising=False)
    assert redis_required() is False
    assert agent_memory_required() is False
    assert inference_required() is False
    monkeypatch.setenv("REZN_PRODUCTION", "1")
    assert redis_required() is True
    assert agent_memory_required() is True
    assert inference_required() is True


def test_validate_deployment_skipped_under_disable_redis(monkeypatch):
    monkeypatch.setenv("REZN_DISABLE_REDIS", "1")
    monkeypatch.setenv("REZN_PRODUCTION", "true")
    validate_deployment()  # must not raise in hermetic test mode


def test_is_truthy():
    assert is_truthy("1") and is_truthy("yes") and not is_truthy("0")
