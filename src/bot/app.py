import asyncio

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from bot.config.settings import Settings, get_settings
from bot.slack.handler import handle_mention, handle_thread_reply, _active_tasks, _thread_contexts


def create_app(settings: Settings | None = None) -> AsyncApp:
    if settings is None:
        settings = get_settings()

    app = AsyncApp(token=settings.slack_bot_token)

    @app.event("app_mention")
    async def on_mention(event, client):
        await handle_mention(event, client, settings)

    @app.event("message")
    async def on_message(event, client):
        # Ignore non-thread messages and bot messages
        if "thread_ts" not in event or event.get("bot_id"):
            return
        # Ignore messages that are @mentions (handled by on_mention)
        if event.get("subtype") == "bot_message":
            return

        thread_ts = event["thread_ts"]

        # Skip if there's already an active task running for this thread
        if thread_ts in _active_tasks and not _active_tasks[thread_ts].done():
            return

        # If this thread has prior context, treat as a follow-up
        if thread_ts in _thread_contexts:
            await handle_thread_reply(event, client, settings)

    return app


async def start(settings: Settings | None = None) -> None:
    if settings is None:
        settings = get_settings()
    app = create_app(settings)
    handler = AsyncSocketModeHandler(app, settings.slack_app_token)
    await handler.start_async()
