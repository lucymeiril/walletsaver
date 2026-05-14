import importlib.util
import os
import sys

DB_ADMIN_KEY_ALIAS = "DB_ADMIN_" + "API_KEY"
SERVICE_KEYS_ALIAS = "SERVICE_" + "API_KEYS"


def _load_config_from_repo():
    module_name = "db_admin_config_under_test"
    module_path = os.path.join(os.path.dirname(__file__), "..", "config.py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_load_local_env_files_adds_db_admin_api_key_as_normal_admin_role(tmp_path, monkeypatch):
    secret = "local-admin-config-key"
    dotenv = tmp_path / ".env"
    dotenv_local = tmp_path / ".env.local"
    dotenv.write_text(f"{DB_ADMIN_KEY_ALIAS}=older-key\n", encoding="utf-8")
    dotenv_local.write_text(f"{DB_ADMIN_KEY_ALIAS}={secret}\n", encoding="utf-8")
    monkeypatch.delenv("DB_ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("SERVICE_API_KEYS", raising=False)

    config = _load_config_from_repo()
    monkeypatch.delenv("DB_ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("SERVICE_API_KEYS", raising=False)
    config.load_local_env_files((dotenv, dotenv_local))
    settings = config.Settings()

    assert settings.SERVICE_API_KEYS == {secret: "admin"}


def test_load_local_env_files_does_not_override_process_env_or_registered_role(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"{DB_ADMIN_KEY_ALIAS}=file-key\n", encoding="utf-8")
    monkeypatch.setenv("DB_ADMIN_API_KEY", "process-key")
    monkeypatch.setenv("SERVICE_API_KEYS", "process-key:moderator")

    config = _load_config_from_repo()
    config.load_local_env_files((dotenv,))
    settings = config.Settings()

    assert os.environ["DB_ADMIN_API_KEY"] == "process-key"
    assert settings.SERVICE_API_KEYS == {"process-key": "moderator"}


def test_absent_local_admin_key_does_not_create_admin_api_key(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"{DB_ADMIN_KEY_ALIAS}=\n{SERVICE_KEYS_ALIAS}=malformed-entry-without-role\n", encoding="utf-8")
    monkeypatch.delenv("DB_ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("SERVICE_API_KEYS", raising=False)

    config = _load_config_from_repo()
    monkeypatch.delenv("DB_ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("SERVICE_API_KEYS", raising=False)
    config.load_local_env_files((dotenv,))
    settings = config.Settings()

    assert settings.SERVICE_API_KEYS == {}
