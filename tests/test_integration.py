# tests/test_integration.py
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.slack.handler import handle_mention, _thread_sessions
from bot.config.settings import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(
        slack_bot_token="xoxb-test",
        slack_app_token="xapp-test",
        olla_url="http://test-olla:40114/olla/proxy/v1",
        repos_base_dir=str(tmp_path),
        _env_file=None,
    )


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.chat_postMessage = AsyncMock(return_value={"ts": "1234.5678"})
    client.chat_update = AsyncMock(return_value={"ok": True})
    # Return only the current message (no prior thread context)
    client.conversations_replies = AsyncMock(return_value={
        "messages": [
            {"user": "U123", "text": "<@UBOT> model=sonnet fix the login bug"},
        ]
    })
    return client


@pytest.mark.asyncio
async def test_full_flow_mocked(settings, mock_client):
    """Test the full flow from Slack event to task completion with mocked SDK."""
    event = {
        "text": "<@U123> model=sonnet fix the login bug",
        "channel": "C123",
        "ts": "1111.0000",
    }

    mock_sdk_client = AsyncMock()

    # Mock ClaudeSDKClient
    mock_sdk_instance = AsyncMock()

    async def mock_receive():
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
        assistant = MagicMock(spec=AssistantMessage)
        text_block = MagicMock(spec=TextBlock)
        text_block.text = "Fixed the bug in auth.py"
        assistant.content = [text_block]
        yield assistant
        result = MagicMock(spec=ResultMessage)
        result.total_cost_usd = 0.01
        yield result

    mock_sdk_instance.connect = AsyncMock()
    mock_sdk_instance.query = AsyncMock()
    mock_sdk_instance.receive_response = mock_receive
    mock_sdk_instance.disconnect = AsyncMock()

    with patch("bot.executor.worker.ClaudeSDKClient", return_value=mock_sdk_instance), \
         patch("bot.slack.handler.load_models", return_value={
             "sonnet": {"provider": "anthropic", "model_id": "claude-sonnet-4-20250514"},
         }), \
         patch("bot.slack.handler.load_repos", return_value={}):
        task = await handle_mention(event, mock_client, settings)
        if task:
            await task

    # Verify ACK was sent
    post_calls = mock_client.chat_postMessage.call_args_list
    assert any("sonnet" in str(c) for c in post_calls)
    # Verify summary was edited into the progress message (not posted as new)
    update_calls = mock_client.chat_update.call_args_list
    assert any("Fixed the bug" in str(c) for c in update_calls)

    # Clean up thread session
    _thread_sessions.pop("1111.0000", None)
