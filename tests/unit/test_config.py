"""Testes de lumbra.shared.config."""

import pytest
from pydantic import ValidationError

from lumbra.shared.config import Settings


def test_defaults_are_local_and_private():
    s = Settings(_env_file=None)
    assert s.environment == "local"
    assert s.is_production is False
    # Privacy first: telemetria desligada por padrão
    assert s.observability.telemetry_enabled is False


def test_nested_env_override(monkeypatch):
    monkeypatch.setenv("LUMBRA_ENVIRONMENT", "production")
    monkeypatch.setenv("LUMBRA_DATABASE__POOL_SIZE", "42")
    monkeypatch.setenv("LUMBRA_OBSERVABILITY__LOG_LEVEL", "ERROR")
    s = Settings(_env_file=None)
    assert s.is_production is True
    assert s.database.pool_size == 42
    assert s.observability.log_level == "ERROR"


def test_secrets_never_leak_in_repr():
    s = Settings(_env_file=None)
    rendered = repr(s) + s.model_dump_json()
    assert "dev-only-insecure-secret" not in rendered
    assert "lumbra:lumbra@localhost" not in rendered


def test_invalid_environment_rejected(monkeypatch):
    monkeypatch.setenv("LUMBRA_ENVIRONMENT", "banana")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_bounds_enforced(monkeypatch):
    monkeypatch.setenv("LUMBRA_SECURITY__ACCESS_TOKEN_TTL_SECONDS", "10")  # < 60
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
