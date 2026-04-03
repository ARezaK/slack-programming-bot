import asyncio
import json
import re
from dataclasses import dataclass, field

from claude_agent_sdk import ClaudeSDKClient

from bot.config.settings import Settings, load_models, load_repos
from bot.executor.worker import TaskRunner, TaskResult
from bot.slack.feedback import SlackFeedback


def extract_model(text: str) -> tuple[str | None, str]:
    match = re.search(r"model=(\S+)", text)
    if match:
        model = match.group(1)
        text = text[: match.start()] + text[match.end() :]
        text = re.sub(r"\s+", " ", text).strip()
        return model, text
    return None, text.strip()


def strip_bot_mention(text: str) -> str:
    return re.sub(r"<@\w+>\s*", "", text).strip()


@dataclass
class ThreadSession:
    """Stores a live SDK client session for a thread."""
    model_name: str
    model_id: str
    provider: str
    client: ClaudeSDKClient
    runner: TaskRunner


async def fetch_thread_context(client, channel: str, thread_ts: str, bot_user_id: str | None = None) -> str | None:
    """Fetch prior messages in a thread and format them as context for the agent.

    Returns None if there are no prior messages (i.e., the @mention is the first message).
    """
    try:
        result = await client.conversations_replies(
            channel=channel,
            ts=thread_ts,
            limit=50,
        )
    except Exception:
        return None

    messages = result.get("messages", [])
    if len(messages) <= 1:
        # Only the current message — no prior context
        return None

    lines = []
    for msg in messages:
        user = msg.get("user", "unknown")
        text = msg.get("text", "")
        # Skip bot messages from ourselves
        if bot_user_id and msg.get("user") == bot_user_id:
            user = "bot (you)"
        # Clean up Slack user mentions for readability
        text = re.sub(r"<@(\w+)>", r"@\1", text)
        lines.append(f"@{user}: {text}")

    return "\n".join(lines)


# Active tasks (currently running) keyed by thread_ts
_active_tasks: dict[str, asyncio.Task] = {}

# Live sessions for threads that completed at least one task
_thread_sessions: dict[str, ThreadSession] = {}


async def handle_mention(event: dict, client, settings: Settings) -> asyncio.Task | None:
    """Handle an @mention — either a new task or a follow-up in an existing thread."""
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]
    raw_text = event.get("text", "")

    text = strip_bot_mention(raw_text)
    model_hint, task_text = extract_model(text)

    # Check if this is a follow-up in an existing thread session
    session = _thread_sessions.get(thread_ts)

    if session and not model_hint:
        # Follow-up in existing session — continue the conversation
        return await _dispatch_follow_up(
            session=session,
            task_text=task_text,
            channel=channel,
            thread_ts=thread_ts,
            settings=settings,
            client=client,
        )

    # New task (or model override = start fresh)
    models = load_models()
    model_name = model_hint or settings.default_model
    model_config = models.get(model_name)

    if model_config is None:
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Unknown model `{model_name}`. Available: {', '.join(models.keys())}",
        )
        return None

    model_id = model_config["model_id"]
    provider = model_config["provider"]

    # If there's an old session for this thread, clean it up
    old_session = _thread_sessions.pop(thread_ts, None)
    if old_session:
        try:
            await old_session.client.disconnect()
        except Exception:
            pass

    # Fetch thread history so the agent can see the full conversation
    thread_context = await fetch_thread_context(client, channel, thread_ts)
    if thread_context:
        task_text = (
            f"Here is the Slack thread conversation for context:\n\n"
            f"{thread_context}\n\n"
            f"---\n\n"
            f"Your task (from the latest message): {task_text}"
        )

    return await _dispatch_new_task(
        task_text=task_text,
        model_name=model_name,
        model_id=model_id,
        provider=provider,
        channel=channel,
        thread_ts=thread_ts,
        settings=settings,
        client=client,
    )


async def _dispatch_new_task(
    task_text: str,
    model_name: str,
    model_id: str,
    provider: str,
    channel: str,
    thread_ts: str,
    settings: Settings,
    client,
) -> asyncio.Task:
    feedback = SlackFeedback(client)
    await feedback.send_ack(channel, thread_ts, model_name)

    repos = load_repos()
    runner = TaskRunner(
        litellm_url=settings.litellm_url,
        repos_base_dir=settings.repos_base_dir,
        repos_json=json.dumps(repos, indent=2),
    )

    async def _run_task():
        result, sdk_client = await runner.run(
            task_text=task_text,
            model_id=model_id,
            provider=provider,
            feedback=feedback,
            channel=channel,
            thread_ts=thread_ts,
            timeout_seconds=settings.task_timeout_seconds,
        )

        if result.success:
            cost_line = f"\n_Cost: ${result.cost_usd:.4f}_" if result.cost_usd else ""
            await feedback.send_summary(channel, thread_ts, result.summary + cost_line)

        # Store the live session for follow-ups
        _thread_sessions[thread_ts] = ThreadSession(
            model_name=model_name,
            model_id=model_id,
            provider=provider,
            client=sdk_client,
            runner=runner,
        )
        _active_tasks.pop(thread_ts, None)

    task = asyncio.create_task(_run_task())
    _active_tasks[thread_ts] = task
    return task


async def _dispatch_follow_up(
    session: ThreadSession,
    task_text: str,
    channel: str,
    thread_ts: str,
    settings: Settings,
    client,
) -> asyncio.Task:
    feedback = SlackFeedback(client)
    await feedback.send_ack(channel, thread_ts, session.model_name)

    async def _run_follow_up():
        result = await session.runner.continue_session(
            client=session.client,
            task_text=task_text,
            feedback=feedback,
            channel=channel,
            thread_ts=thread_ts,
            timeout_seconds=settings.task_timeout_seconds,
        )

        if result.success:
            cost_line = f"\n_Cost: ${result.cost_usd:.4f}_" if result.cost_usd else ""
            await feedback.send_summary(channel, thread_ts, result.summary + cost_line)

        _active_tasks.pop(thread_ts, None)

    task = asyncio.create_task(_run_follow_up())
    _active_tasks[thread_ts] = task
    return task
