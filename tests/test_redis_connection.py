"""Unit tests for Redis (Redis Cloud) connection resolution and log redaction."""

from __future__ import annotations

import fakeredis
import pytest

from rezn_ai.storage import redis_store
from rezn_ai.storage.redis_store import (
    DEFAULT_REDIS_URL,
    RedisStore,
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


# ── RedisStore TLS cert configuration ─────────────────────────────────────────

def test_rediss_url_forwards_ssl_kwargs_from_env(monkeypatch):
    """A rediss:// (TLS) connection forwards cert config from env, so Redis Cloud
    with a private CA can be verified (or relaxed) without code changes."""
    captured: dict = {}

    def fake_from_url(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return fakeredis.FakeRedis(decode_responses=True)

    monkeypatch.setattr(redis_store.redis_lib, "from_url", fake_from_url)
    monkeypatch.setenv("REDIS_SSL_CA_CERTS", "/etc/ssl/redis-ca.pem")
    monkeypatch.setenv("REDIS_SSL_CERT_REQS", "required")
    RedisStore(redis_url="rediss://default:pw@cloud.example.com:6380")
    assert captured["kwargs"]["ssl_ca_certs"] == "/etc/ssl/redis-ca.pem"
    assert captured["kwargs"]["ssl_cert_reqs"] == "required"


def test_plain_redis_url_passes_no_ssl_kwargs(monkeypatch):
    """A plain redis:// connection never carries ssl_* kwargs, even if the cert env
    vars happen to be set — they only apply to TLS endpoints."""
    captured: dict = {}

    def fake_from_url(url, **kwargs):
        captured["kwargs"] = kwargs
        return fakeredis.FakeRedis(decode_responses=True)

    monkeypatch.setattr(redis_store.redis_lib, "from_url", fake_from_url)
    monkeypatch.setenv("REDIS_SSL_CA_CERTS", "/etc/ssl/redis-ca.pem")
    RedisStore(redis_url="redis://localhost:6379/0")
    assert "ssl_ca_certs" not in captured["kwargs"]
    assert "ssl_cert_reqs" not in captured["kwargs"]
