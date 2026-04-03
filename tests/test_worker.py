# tests/test_worker.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.executor.worker import TaskRunner, TaskResult


@pytest.fixture
def mock_feedback():
    fb = AsyncMock()
    fb.create_progress = AsyncMock(return_value=MagicMock(channel="C123", thread_ts="1111.0000", message_ts="2222.0000", last_update=0.0))
    return fb


def test_build_env_anthropic():
    runner = TaskRunner(
        litellm_url="http://localhost:4000",
        repos_base_dir="/tmp/repos",
    )
    env = runner._build_env(provider="anthropic")
    assert env == {}  # no env vars needed, CLI uses its own auth


def test_build_env_litellm():
    runner = TaskRunner(
        litellm_url="http://localhost:4000",
        repos_base_dir="/tmp/repos",
    )
    env = runner._build_env(provider="litellm")
    assert env["ANTHROPIC_BASE_URL"] == "http://localhost:4000"


def test_build_system_prompt():
    runner = TaskRunner(
        litellm_url="http://localhost:4000",
        repos_base_dir="/tmp/repos",
        repos_json='{"myrepo": {"path": "myrepo", "aliases": ["mr"]}}',
    )
    prompt = runner._build_system_prompt()
    assert "/tmp/repos" in prompt
    assert "myrepo" in prompt


def test_build_options():
    runner = TaskRunner(
        litellm_url="http://localhost:4000",
        repos_base_dir="/tmp/repos",
    )
    options = runner._build_options("claude-sonnet-4-20250514", "anthropic")
    assert options.model == "claude-sonnet-4-20250514"
    assert options.cwd == "/tmp/repos"
    assert options.permission_mode == "bypassPermissions"
