import time
from dataclasses import dataclass


@dataclass
class ProgressHandle:
    channel: str
    thread_ts: str
    message_ts: str
    last_update: float = 0.0


class SlackFeedback:
    def __init__(self, client, throttle_seconds: float = 3.0):
        self.client = client
        self.throttle_seconds = throttle_seconds

    async def send_ack(self, channel: str, thread_ts: str, model: str) -> None:
        await self.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Got it, working on this using `{model}`...",
        )

    async def create_progress(self, channel: str, thread_ts: str) -> ProgressHandle:
        result = await self.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Starting...",
        )
        return ProgressHandle(
            channel=channel,
            thread_ts=thread_ts,
            message_ts=result["ts"],
        )

    async def update_progress(self, handle: ProgressHandle, status: str) -> None:
        now = time.monotonic()
        if now - handle.last_update < self.throttle_seconds:
            return
        handle.last_update = now
        await self.client.chat_update(
            channel=handle.channel,
            ts=handle.message_ts,
            text=status,
        )

    async def finalize_progress(self, handle: ProgressHandle, summary: str) -> None:
        """Final edit to the progress message — bypasses throttle."""
        await self.client.chat_update(
            channel=handle.channel,
            ts=handle.message_ts,
            text=summary,
        )

    async def send_error(self, channel: str, thread_ts: str, error_info: str) -> None:
        await self.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Something went wrong: {error_info}",
        )
