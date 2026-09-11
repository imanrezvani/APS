"""Phase 10 P1 database configuration tests (no live database needed)."""

import pytest

pytest.importorskip("sqlalchemy", reason="optional 'postgres' dependencies not installed")

from aps_persistence.config import (  # noqa: E402
    DatabaseConfigurationError,
    resolve_database_url,
    resolve_test_database_url,
    settings_from_env,
)

_DSN = "postgresql+psycopg://user:pw@127.0.0.1:5432/db"


def _clear_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("APS_DATABASE_URL", raising=False)


def test_missing_url_raises_configuration_error(monkeypatch):
    _clear_env(monkeypatch)
    with pytest.raises(DatabaseConfigurationError):
        resolve_database_url()


def test_url_read_from_environment(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", _DSN)
    assert resolve_database_url() == _DSN
    assert settings_from_env().url == _DSN


def test_aps_prefixed_url_supported(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("APS_DATABASE_URL", _DSN)
    assert resolve_database_url() == _DSN


def test_explicit_url_overrides_environment(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", _DSN)
    other = "postgresql+psycopg://u:p@other:5432/db2"
    assert resolve_database_url(other) == other


def test_invalid_url_without_scheme_rejected(monkeypatch):
    _clear_env(monkeypatch)
    with pytest.raises(DatabaseConfigurationError):
        settings_from_env("not-a-url")


def test_pool_settings_from_environment(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", _DSN)
    monkeypatch.setenv("APS_DB_POOL_SIZE", "7")
    monkeypatch.setenv("APS_DB_MAX_OVERFLOW", "3")
    monkeypatch.setenv("APS_DB_POOL_TIMEOUT", "11")
    monkeypatch.setenv("APS_DB_POOL_RECYCLE", "120")
    monkeypatch.setenv("APS_DB_ECHO", "true")
    settings = settings_from_env()
    assert settings.pool_size == 7
    assert settings.max_overflow == 3
    assert settings.pool_timeout == 11
    assert settings.pool_recycle == 120
    assert settings.echo is True


def test_invalid_pool_setting_rejected(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", _DSN)
    monkeypatch.setenv("APS_DB_POOL_SIZE", "many")
    with pytest.raises(DatabaseConfigurationError):
        settings_from_env()


def test_engine_kwargs_are_explicit():
    kwargs = settings_from_env(_DSN).engine_kwargs()
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["future"] is True
    assert kwargs["pool_size"] == 5
    assert kwargs["max_overflow"] == 10


def test_test_database_url_resolution(monkeypatch):
    monkeypatch.delenv("APS_TEST_DATABASE_URL", raising=False)
    assert resolve_test_database_url() is None
    monkeypatch.setenv("APS_TEST_DATABASE_URL", _DSN)
    assert resolve_test_database_url() == _DSN
