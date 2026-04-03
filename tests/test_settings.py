import json
import os
from pathlib import Path

import pytest
from bot.config.settings import Settings, load_models


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("REPOS_BASE_DIR", "/tmp/repos")
    monkeypatch.setenv("DEFAULT_MODEL", "opus")
    monkeypatch.setenv("TASK_TIMEOUT_SECONDS", "300")

    settings = Settings()
    assert settings.slack_bot_token == "xoxb-test"
    assert settings.slack_app_token == "xapp-test"
    assert settings.anthropic_api_key == "sk-ant-test"
    assert settings.repos_base_dir == "/tmp/repos"
    assert settings.default_model == "opus"
    assert settings.task_timeout_seconds == 300


def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    settings = Settings()
    assert settings.default_model == "sonnet"
    assert settings.task_timeout_seconds == 600
    assert settings.litellm_url == "http://localhost:4000"


def test_load_models(tmp_path):
    models_file = tmp_path / "models.json"
    models_file.write_text(json.dumps({
        "sonnet": {"provider": "anthropic", "model_id": "claude-sonnet-4-20250514"},
        "local": {"provider": "litellm", "model_id": "ollama/qwen3"},
    }))
    models = load_models(models_file)
    assert models["sonnet"]["provider"] == "anthropic"
    assert models["local"]["model_id"] == "ollama/qwen3"


def test_load_models_missing_file():
    with pytest.raises(FileNotFoundError):
        load_models(Path("/nonexistent/models.json"))
