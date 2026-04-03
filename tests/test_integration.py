# tests/test_integration.py
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.slack.handler import handle_mention
from bot.config.settings import Settings


@pytest.fixture
def settings(tmp_path):
    # Create models.json
    models_file = tmp_path / "config" / "models.json"
    models_file.parent.mkdir(parents=True)
    models_file.write_text(json.dumps({
        "sonnet": {"provider": "anthropic", "model_id": "claude-sonnet-4-20250514"},
    }))

    return Settings(
        slack_bot_token="xoxb-test",
        slack_app_token="xapp-test",
        anthropic_api_key="sk-ant-test",
        repos_base_dir=str(tmp_path),
    )


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.chat_postMessage = AsyncMock(return_value={"ts": "1234.5678"})
    client.chat_update = AsyncMock(return_value={"ok": True})
    return client


@pytest.mark.asyncio
async def test_full_flow_mocked(settings, mock_client):
    """Test the full flow from Slack event to task completion with mocked SDK."""
    event = {
        "text": "<@U123> model=sonnet fix the login bug",
        "channel": "C123",
        "ts": "1111.0000",
    }

    # Mock the SDK query to return our fake messages
    async def mock_query(*args, **kwargs):
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

        # Yield an assistant message
        assistant = MagicMock(spec=AssistantMessage)
        text_block = MagicMock(spec=TextBlock)
        text_block.text = "Fixed the bug in auth.py"
        assistant.content = [text_block]
        yield assistant

        # Yield a result message
        result = MagicMock(spec=ResultMessage)
        result.total_cost_usd = 0.01
        yield result

    with patch("bot.executor.worker.query", side_effect=mock_query), \
         patch("bot.slack.handler.load_models", return_value={
             "sonnet": {"provider": "anthropic", "model_id": "claude-sonnet-4-20250514"},
         }), \
         patch("bot.slack.handler.load_repos", return_value={}):
        task = await handle_mention(event, mock_client, settings)
        if task:
            await task  # await the background task directly — no sleep

    # Verify ACK was sent
    calls = mock_client.chat_postMessage.call_args_list
    assert any("sonnet" in str(c) for c in calls)
