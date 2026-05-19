# tests/test_worker.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.executor.worker import TaskRunner


@pytest.fixture
def mock_feedback():
    fb = AsyncMock()
    fb.create_progress = AsyncMock(return_value=MagicMock(channel="C123", thread_ts="1111.0000", message_ts="2222.0000", last_update=0.0))
    return fb


def test_build_system_prompt():
    runner = TaskRunner(
        repos_base_dir="/tmp/repos",
        repos_json='{"myrepo": {"path": "myrepo", "aliases": ["mr"]}}',
    )
    prompt = runner._build_system_prompt()
    assert "/tmp/repos" in prompt
    assert "myrepo" in prompt


def test_build_options():
    runner = TaskRunner(
        repos_base_dir="/tmp/repos",
    )
    options = runner._build_options("claude-sonnet-4-20250514")
    assert options.model == "claude-sonnet-4-20250514"
    assert options.cwd == "/tmp/repos"
    assert options.permission_mode == "bypassPermissions"


@pytest.mark.asyncio
async def test_run_returns_failed_result_on_connect_auth_error(mock_feedback):
    runner = TaskRunner(repos_base_dir="/tmp/repos")
    mock_sdk_client = AsyncMock()
    mock_sdk_client.connect.side_effect = Exception(
        'Failed to authenticate. API Error: 401 {"type":"error","error":{"type":"authentication_error","message":"Invalid authentication credentials"}}'
    )

    with patch("bot.executor.worker.ClaudeSDKClient", return_value=mock_sdk_client):
        result, client = await runner.run(
            task_text="find the largest folder",
            model_id="claude-sonnet-4-20250514",
            feedback=mock_feedback,
            channel="C123",
            thread_ts="1111.0000",
        )

    assert result.success is False
    assert client is None
    error_text = mock_feedback.send_error.await_args.args[2]
    assert "Claude Code authentication failed" in error_text
    assert "claude auth logout" in error_text
    assert "claude auth login" in error_text


@pytest.mark.asyncio
async def test_run_rewrites_query_auth_error(mock_feedback):
    runner = TaskRunner(repos_base_dir="/tmp/repos")
    mock_sdk_client = AsyncMock()
    mock_sdk_client.connect = AsyncMock()
    mock_sdk_client.query.side_effect = Exception(
        'Failed to authenticate. API Error: 401 {"type":"error","error":{"type":"authentication_error","message":"Invalid authentication credentials"}}'
    )

    with patch("bot.executor.worker.ClaudeSDKClient", return_value=mock_sdk_client):
        result, client = await runner.run(
            task_text="find the largest folder",
            model_id="claude-sonnet-4-20250514",
            feedback=mock_feedback,
            channel="C123",
            thread_ts="1111.0000",
        )

    assert result.success is False
    assert client is mock_sdk_client
    error_text = mock_feedback.send_error.await_args.args[2]
    assert "Claude Code authentication failed" in error_text
    assert "claude auth logout" in error_text
