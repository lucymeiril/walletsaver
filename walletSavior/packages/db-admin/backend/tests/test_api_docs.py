"""Tests for API docs protection in production."""
import os
import sys
import importlib

import pytest
from fastapi.testclient import TestClient


def _reload_and_create_app():
    """Flush cached modules and create a fresh app."""
    for mod in list(sys.modules):
        if mod.startswith(("config", "api.app", "api.middleware")):
            del sys.modules[mod]
    from api.app import create_app
    return create_app()


def test_docs_hidden_in_production(monkeypatch):
    monkeypatch.setenv("DEBUG", "false")
    app = _reload_and_create_app()
    c = TestClient(app, raise_server_exceptions=False)
    assert c.get("/docs").status_code == 404
    assert c.get("/redoc").status_code == 404
    assert c.get("/openapi.json").status_code == 404


def test_docs_available_in_debug(monkeypatch):
    monkeypatch.setenv("DEBUG", "true")
    app = _reload_and_create_app()
    c = TestClient(app, raise_server_exceptions=False)
    assert c.get("/docs").status_code == 200
    assert c.get("/openapi.json").status_code == 200
