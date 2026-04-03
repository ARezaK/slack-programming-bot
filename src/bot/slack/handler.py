import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

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
class ThreadContext:
    """Stores conversation context for a completed thread so follow-ups work."""
    model_name: str
    model_id: str
    provider: str
    original_task: str
    last_summary: str
    history: list[dict] = field(default_factory=list)


# Active tasks keyed by thread_ts
_active_tasks: dict[str, asyncio.Task] = {}

# Completed thread contexts keyed by thread_ts
_thread_contexts: dict[str, ThreadContext] = {}


async def handle_mention(event: dict, client, settings: Settings) -> asyncio.Task | None:
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]
    raw_text = event.get("text", "")

    text = strip_bot_mention(raw_text)
    model_hint, task_text = extract_model(text)

    # Resolve model
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

    return await _dispatch_task(
        task_text=task_text,
        model_name=model_name,
        model_id=model_id,
        provider=provider,
        channel=channel,
        thread_ts=thread_ts,
        settings=settings,
        client=client,
    )


async def handle_thread_reply(event: dict, client, settings: Settings) -> asyncio.Task | None:
    """Handle a reply in a thread where the bot previously completed a task."""
    channel = event["channel"]
    thread_ts = event["thread_ts"]
    raw_text = event.get("text", "")
    text = strip_bot_mention(raw_text)

    ctx = _thread_contexts.get(thread_ts)
    if ctx is None:
        return None

    # Check for model override in follow-up
    model_hint, task_text = extract_model(text)
    if model_hint:
        models = load_models()
        model_config = models.get(model_hint)
        if model_config:
            ctx.model_name = model_hint
            ctx.model_id = model_config["model_id"]
            ctx.provider = model_config["provider"]

    # Build a prompt that includes conversation history
    history_lines = []
    for entry in ctx.history:
        history_lines.append(f"User: {entry['user']}")
        history_lines.append(f"Agent: {entry['agent']}")
    history_text = "\n".join(history_lines)

    contextual_prompt = f"""This is a follow-up in an ongoing conversation.

Previous conversation:
{history_text}

User's new message: {task_text}

Continue where you left off. You already know which repo this is about from the conversation above."""

    return await _dispatch_task(
        task_text=contextual_prompt,
        model_name=ctx.model_name,
        model_id=ctx.model_id,
        provider=ctx.provider,
        channel=channel,
        thread_ts=thread_ts,
        settings=settings,
        client=client,
        thread_context=ctx,
        raw_user_text=task_text,
    )


async def _dispatch_task(
    task_text: str,
    model_name: str,
    model_id: str,
    provider: str,
    channel: str,
    thread_ts: str,
    settings: Settings,
    client,
    thread_context: ThreadContext | None = None,
    raw_user_text: str | None = None,
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
        result = await runner.run(
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

        # Update or create thread context for future follow-ups
        user_text = raw_user_text or task_text
        if thread_context:
            thread_context.history.append({
                "user": user_text,
                "agent": result.summary[:500] if result.summary else "(no response)",
            })
            thread_context.last_summary = result.summary or ""
        else:
            ctx = ThreadContext(
                model_name=model_name,
                model_id=model_id,
                provider=provider,
                original_task=task_text,
                last_summary=result.summary or "",
                history=[{
                    "user": user_text,
                    "agent": result.summary[:500] if result.summary else "(no response)",
                }],
            )
            _thread_contexts[thread_ts] = ctx

        # Remove from active tasks
        _active_tasks.pop(thread_ts, None)

    task = asyncio.create_task(_run_task())
    _active_tasks[thread_ts] = task
    return task
