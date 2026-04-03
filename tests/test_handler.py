import pytest
from bot.slack.handler import extract_model, strip_bot_mention, ThreadContext, _thread_contexts, handle_thread_reply
from unittest.mock import AsyncMock, MagicMock, patch
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
async def test_handle_thread_reply_with_context():
    """Thread replies should include prior conversation context in the prompt."""
    # Set up a thread context as if a previous task completed
    _thread_contexts["1111.0000"] = ThreadContext(
        model_name="sonnet",
        model_id="claude-sonnet-4-20250514",
        provider="anthropic",
        original_task="fix the login tests in GTG",
        last_summary="Fixed 3 tests. Created branch fix-login. Want me to push and create a PR?",
        history=[{
            "user": "fix the login tests in GTG",
            "agent": "Fixed 3 tests. Created branch fix-login. Want me to push and create a PR?",
        }],
    )

    mock_client = AsyncMock()
    mock_client.chat_postMessage = AsyncMock(return_value={"ts": "2222.0000"})
    mock_client.chat_update = AsyncMock(return_value={"ok": True})

    settings = Settings(
        slack_bot_token="xoxb-test",
        slack_app_token="xapp-test",
        _env_file=None,
    )

    event = {
        "text": "yes",
        "channel": "C123",
        "ts": "3333.0000",
        "thread_ts": "1111.0000",
    }

    captured_prompt = {}

    async def mock_query(*args, **kwargs):
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
        captured_prompt["text"] = kwargs.get("prompt") or (args[0] if args else "")
        assistant = MagicMock(spec=AssistantMessage)
        text_block = MagicMock(spec=TextBlock)
        text_block.text = "Pushed and created PR #42"
        assistant.content = [text_block]
        yield assistant
        result = MagicMock(spec=ResultMessage)
        result.total_cost_usd = 0.01
        yield result

    with patch("bot.executor.worker.query", side_effect=mock_query), \
         patch("bot.slack.handler.load_models", return_value={
             "sonnet": {"provider": "anthropic", "model_id": "claude-sonnet-4-20250514"},
         }), \
         patch("bot.slack.handler.load_repos", return_value={}):
        task = await handle_thread_reply(event, mock_client, settings)
        if task:
            await task

    # The prompt sent to the agent should contain the conversation history
    assert "fix the login tests" in captured_prompt["text"]
    assert "yes" in captured_prompt["text"]
    assert "follow-up" in captured_prompt["text"].lower()

    # Clean up
    _thread_contexts.pop("1111.0000", None)
