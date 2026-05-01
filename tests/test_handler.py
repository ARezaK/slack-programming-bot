# tests/test_handler.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.slack.handler import extract_model, strip_bot_mention, handle_mention, fetch_thread_context, _thread_sessions, ThreadSession
from bot.config.settings import Settings


def test_extract_model_present():
    model, text = extract_model("model=qwen3 fix the login tests")
    assert model == "qwen3"
    assert text == "fix the login tests"


def test_extract_model_absent():
    model, text = extract_model("fix the login tests")
    assert model is None
    assert text == "fix the login tests"


def test_extract_model_in_middle():
    model, text = extract_model("fix model=opus the login tests")
    assert model == "opus"
    assert text == "fix the login tests"


def test_strip_bot_mention():
    text = strip_bot_mention("<@U12345> fix the login tests")
    assert text == "fix the login tests"


def test_strip_bot_mention_no_mention():
    text = strip_bot_mention("fix the login tests")
    assert text == "fix the login tests"


@pytest.mark.asyncio
async def test_follow_up_uses_existing_session():
    """When @mentioning in a thread with a prior session, the bot continues that session."""
    mock_sdk_client = AsyncMock()
    mock_runner = MagicMock()

    # Mock continue_session to return a result with a progress handle
    async def mock_continue(client, task_text, feedback, channel, thread_ts, timeout_seconds):
        from bot.slack.feedback import ProgressHandle
        handle = ProgressHandle(channel=channel, thread_ts=thread_ts, message_ts="prog.0000")
        return MagicMock(success=True, summary="Pushed and created PR #42", cost_usd=0.01, progress_handle=handle)

    mock_runner.continue_session = mock_continue

    _thread_sessions["1111.0000"] = ThreadSession(
        model_name="sonnet",
        model_id="claude-sonnet-4-20250514",
        provider="anthropic",
        client=mock_sdk_client,
        runner=mock_runner,
    )

    mock_client = AsyncMock()
    mock_client.chat_postMessage = AsyncMock(return_value={"ts": "2222.0000"})
    mock_client.chat_update = AsyncMock(return_value={"ok": True})

    settings = Settings(
        slack_bot_token="xoxb-test",
        slack_app_token="xapp-test",
        olla_url="http://test-olla:40114/olla/proxy/v1",
        _env_file=None,
    )

    # Simulate a follow-up @mention in the same thread
    event = {
        "text": "<@U123> yes please push it",
        "channel": "C123",
        "ts": "3333.0000",
        "thread_ts": "1111.0000",
    }

    with patch("bot.slack.handler.load_models", return_value={
        "sonnet": {"provider": "anthropic", "model_id": "claude-sonnet-4-20250514"},
    }), patch("bot.slack.handler.load_repos", return_value={}):
        task = await handle_mention(event, mock_client, settings)
        if task:
            await task

    # Verify ACK was sent
    post_calls = mock_client.chat_postMessage.call_args_list
    assert any("sonnet" in str(c) for c in post_calls)
    # Verify summary was edited into the progress message (not posted as new)
    update_calls = mock_client.chat_update.call_args_list
    assert any("PR #42" in str(c) for c in update_calls)

    # Clean up
    _thread_sessions.pop("1111.0000", None)


@pytest.mark.asyncio
async def test_fetch_thread_context():
    """fetch_thread_context should format thread messages into readable context."""
    mock_client = AsyncMock()
    mock_client.conversations_replies = AsyncMock(return_value={
        "messages": [
            {"user": "U001", "text": "I think we should refactor the auth middleware"},
            {"user": "U002", "text": "agreed, the JWT handling is a mess"},
            {"user": "U001", "text": "here's the file that needs changing: auth.py lines 40-60"},
            {"user": "U003", "text": "<@UBOT> make the change suggested above for PMSS"},
        ]
    })

    result = await fetch_thread_context(mock_client, "C123", "1111.0000")

    assert result is not None
    assert "@U001: I think we should refactor" in result
    assert "@U002: agreed" in result
    assert "auth.py lines 40-60" in result
    assert "make the change suggested above" in result


@pytest.mark.asyncio
async def test_fetch_thread_context_no_prior_messages():
    """If the @mention is the first message, return None (no context to inject)."""
    mock_client = AsyncMock()
    mock_client.conversations_replies = AsyncMock(return_value={
        "messages": [
            {"user": "U001", "text": "<@UBOT> fix the login bug"},
        ]
    })

    result = await fetch_thread_context(mock_client, "C123", "1111.0000")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_thread_context_api_failure():
    """If the Slack API call fails, return None gracefully."""
    mock_client = AsyncMock()
    mock_client.conversations_replies = AsyncMock(side_effect=Exception("API error"))

    result = await fetch_thread_context(mock_client, "C123", "1111.0000")
    assert result is None
