import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.slack.feedback import SlackFeedback


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.chat_postMessage = AsyncMock(return_value={"ts": "1234.5678"})
    client.chat_update = AsyncMock(return_value={"ok": True})
    return client


@pytest.mark.asyncio
async def test_send_ack(mock_client):
    fb = SlackFeedback(mock_client)
    await fb.send_ack("C123", "1111.0000", "sonnet")
    mock_client.chat_postMessage.assert_called_once()
    call_kwargs = mock_client.chat_postMessage.call_args.kwargs
    assert call_kwargs["channel"] == "C123"
    assert call_kwargs["thread_ts"] == "1111.0000"
    assert "sonnet" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_create_and_update_progress(mock_client):
    fb = SlackFeedback(mock_client)
    handle = await fb.create_progress("C123", "1111.0000")
    assert handle is not None

    await fb.update_progress(handle, "Running tests...")
    mock_client.chat_update.assert_called_once()
    call_kwargs = mock_client.chat_update.call_args.kwargs
    assert "Running tests..." in call_kwargs["text"]


@pytest.mark.asyncio
async def test_update_progress_throttled(mock_client):
    fb = SlackFeedback(mock_client, throttle_seconds=1.0)
    handle = await fb.create_progress("C123", "1111.0000")

    await fb.update_progress(handle, "Step 1")
    await fb.update_progress(handle, "Step 2")  # should be throttled

    # Only one chat_update call (throttled)
    assert mock_client.chat_update.call_count == 1


@pytest.mark.asyncio
async def test_finalize_progress(mock_client):
    fb = SlackFeedback(mock_client)
    handle = await fb.create_progress("C123", "1111.0000")

    await fb.finalize_progress(handle, "Fixed 3 tests. PR: http://example.com")
    # Should edit the existing progress message, not post a new one
    call_kwargs = mock_client.chat_update.call_args.kwargs
    assert call_kwargs["ts"] == "1234.5678"  # same message
    assert "Fixed 3 tests" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_send_error(mock_client):
    fb = SlackFeedback(mock_client)
    await fb.send_error("C123", "1111.0000", "Timeout after 600s")
    call_kwargs = mock_client.chat_postMessage.call_args.kwargs
    assert "Timeout" in call_kwargs["text"]
