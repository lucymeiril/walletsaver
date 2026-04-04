"""Tests for configuration security."""
import os
import sys
import importlib
import pytest


def test_cors_origins_not_wildcard():
    """CORS must not be configured with wildcard in default settings."""
    import config
    importlib.reload(config)
    assert "*" not in config.settings.CORS_ORIGINS


def test_cors_origins_from_env(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://admin.example.com")
    import config
    importlib.reload(config)
    assert config.settings.CORS_ORIGINS == ["https://admin.example.com"]


def test_alembic_ini_no_hardcoded_password():
    """alembic.ini must not contain plaintext passwords."""
    ini_path = os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
    if os.path.exists(ini_path):
        content = open(ini_path).read()
        assert "changeme" not in content, "alembic.ini contains default password"


def test_production_rejects_default_password(monkeypatch):
    """Startup must fail if 'changeme' password detected in production."""
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:changeme@localhost/db",
    )
    for mod in list(sys.modules):
        if mod.startswith(("config", "api.app", "api.middleware")):
            del sys.modules[mod]
    from api.app import create_app
    app = create_app()

    from fastapi.testclient import TestClient
    with pytest.raises((RuntimeError, Exception)):
        with TestClient(app):
            pass
