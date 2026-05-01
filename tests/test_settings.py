import json
import os
from pathlib import Path

import pytest
from bot.config.settings import Settings, load_models


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("OLLA_URL", "http://test-olla:40114/olla/proxy/v1")
    monkeypatch.setenv("REPOS_BASE_DIR", "/tmp/repos")
    monkeypatch.setenv("DEFAULT_MODEL", "opus")
    monkeypatch.setenv("TASK_TIMEOUT_SECONDS", "300")

    settings = Settings()
    assert settings.slack_bot_token == "xoxb-test"
    assert settings.slack_app_token == "xapp-test"
    assert settings.repos_base_dir == "/tmp/repos"
    assert settings.default_model == "opus"
    assert settings.task_timeout_seconds == 300


def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("OLLA_URL", "http://test-olla:40114/olla/proxy/v1")
    # Clear any .env overrides so we test actual code defaults
    monkeypatch.delenv("DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("TASK_TIMEOUT_SECONDS", raising=False)

    settings = Settings(_env_file=None)  # skip .env file
    assert settings.default_model == "sonnet"
    assert settings.task_timeout_seconds == 900


def test_load_models(tmp_path):
    models_file = tmp_path / "models.json"
    models_file.write_text(json.dumps({
        "sonnet": {"provider": "anthropic", "model_id": "claude-sonnet-4-20250514"},
        "qwen": {"provider": "local", "model_id": "qwen/qwen3.6-35b-a3b"},
    }))
    models = load_models(models_file)
    assert models["sonnet"]["provider"] == "anthropic"
    assert models["qwen"]["model_id"] == "qwen/qwen3.6-35b-a3b"


def test_load_models_missing_file():
    with pytest.raises(FileNotFoundError):
        load_models(Path("/nonexistent/models.json"))
