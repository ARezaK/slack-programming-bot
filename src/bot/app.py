import asyncio

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from bot.config.settings import Settings, get_settings
from bot.slack.handler import handle_mention


def create_app(settings: Settings | None = None) -> AsyncApp:
    if settings is None:
        settings = get_settings()

    app = AsyncApp(token=settings.slack_bot_token)

    @app.event("app_mention")
    async def on_mention(event, client):
        await handle_mention(event, client, settings)

    @app.event("message")
    async def on_message(event, client):
        # Required to avoid warnings from Slack Bolt about unhandled events.
        # All bot interaction requires @mention — no implicit thread replies.
        pass

    return app


async def start(settings: Settings | None = None) -> None:
    if settings is None:
        settings = get_settings()
    app = create_app(settings)
    handler = AsyncSocketModeHandler(app, settings.slack_app_token)
    await handler.start_async()
