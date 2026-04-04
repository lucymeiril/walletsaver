"""Tests for bind address configuration."""
import os
import importlib


def test_default_host_is_localhost():
    """Default bind address must be 127.0.0.1, not 0.0.0.0."""
    os.environ.pop("DB_ADMIN_HOST", None)
    import config
    importlib.reload(config)
    assert config.settings.API_HOST == "127.0.0.1"


def test_host_override_from_env(monkeypatch):
    """DB_ADMIN_HOST env var overrides the default."""
    monkeypatch.setenv("DB_ADMIN_HOST", "0.0.0.0")
    import config
    importlib.reload(config)
    assert config.settings.API_HOST == "0.0.0.0"
