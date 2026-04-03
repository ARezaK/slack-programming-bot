import asyncio
import json
import re
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


# Active tasks keyed by thread_ts
_active_tasks: dict[str, asyncio.Task] = {}


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

    feedback = SlackFeedback(client)
    await feedback.send_ack(channel, thread_ts, model_name)

    repos = load_repos()
    runner = TaskRunner(
        anthropic_api_key=settings.anthropic_api_key,
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
        # Remove from active tasks
        _active_tasks.pop(thread_ts, None)

    task = asyncio.create_task(_run_task())
    _active_tasks[thread_ts] = task
    return task  # returned so callers/tests can await if needed
