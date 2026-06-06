"""Unit tests for Redis (Redis Cloud) connection resolution and log redaction."""

from __future__ import annotations

import pytest

from rezn_ai.storage.redis_store import (
    DEFAULT_REDIS_URL,
    redact_url,
    redis_url_from_env,
)

_VARS = ("REDIS_URL", "REDIS_HOST", "REDIS_PORT", "REDIS_USERNAME", "REDIS_PASSWORD", "REDIS_TLS")


@pytest.fixture
def clean_redis_env(monkeypatch):
    for var in _VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


# ── redis_url_from_env ────────────────────────────────────────────────────────

def test_defaults_to_local_when_unset(clean_redis_env):
    assert redis_url_from_env() == DEFAULT_REDIS_URL


def test_redis_url_takes_precedence(clean_redis_env):
    clean_redis_env.setenv("REDIS_URL", "rediss://default:pw@cloud.example.com:6380")
    clean_redis_env.setenv("REDIS_HOST", "ignored")
    assert redis_url_from_env() == "rediss://default:pw@cloud.example.com:6380"


def test_builds_tls_url_from_discrete_cloud_vars(clean_redis_env):
    clean_redis_env.setenv("REDIS_HOST", "h.cloud.redislabs.com")
    clean_redis_env.setenv("REDIS_PORT", "12345")
    clean_redis_env.setenv("REDIS_PASSWORD", "secret")
    clean_redis_env.setenv("REDIS_TLS", "true")
    assert redis_url_from_env() == "rediss://default:secret@h.cloud.redislabs.com:12345"


def test_builds_plain_url_without_tls_or_password(clean_redis_env):
    clean_redis_env.setenv("REDIS_HOST", "localhost")
    clean_redis_env.setenv("REDIS_PORT", "6379")
    assert redis_url_from_env() == "redis://localhost:6379"


def test_custom_username_is_honored(clean_redis_env):
    clean_redis_env.setenv("REDIS_HOST", "h")
    clean_redis_env.setenv("REDIS_USERNAME", "app")
    clean_redis_env.setenv("REDIS_PASSWORD", "pw")
    assert redis_url_from_env() == "redis://app:pw@h:6379"


# ── redact_url ────────────────────────────────────────────────────────────────

def test_redact_masks_password_only():
    url = "rediss://default:supersecret@redis-1.cloud.redislabs.com:12345"
    redacted = redact_url(url)
    assert "supersecret" not in redacted
    assert redacted == "rediss://default:***@redis-1.cloud.redislabs.com:12345"


def test_redact_leaves_passwordless_url_untouched():
    url = "redis://localhost:6379/0"
    assert redact_url(url) == url
