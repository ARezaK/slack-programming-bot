import asyncio
from dataclasses import dataclass

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from bot.slack.feedback import SlackFeedback, ProgressHandle


@dataclass
class TaskResult:
    success: bool
    summary: str
    cost_usd: float | None = None
    progress_handle: ProgressHandle | None = None


SYSTEM_PROMPT_TEMPLATE = """You are a coding agent. The user will give you a task.

Here is the repo registry. All paths are relative to: {repos_base_dir}

{repos_json}

Determine which repo the user is referring to (from context, aliases, or keywords).
Navigate to that repo's full path (e.g., {repos_base_dir}/<path>) before starting work.

If you can't determine the repo, ask the user to clarify.

After completing work:
- Summarize what you did
- If you made code changes, create a branch and commit them
- Offer to create a PR if appropriate
"""


class TaskRunner:
    def __init__(
        self,
        repos_base_dir: str,
        repos_json: str = "{}",
    ):
        self.repos_base_dir = repos_base_dir
        self.repos_json = repos_json

    def _build_system_prompt(self) -> str:
        return SYSTEM_PROMPT_TEMPLATE.format(
            repos_base_dir=self.repos_base_dir,
            repos_json=self.repos_json,
        )

    def _build_options(self, model_id: str) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            model=model_id,
            cwd=self.repos_base_dir,
            system_prompt=self._build_system_prompt(),
            permission_mode="bypassPermissions",
            max_turns=50,
        )

    async def run(
        self,
        task_text: str,
        model_id: str,
        feedback: SlackFeedback,
        channel: str,
        thread_ts: str,
        timeout_seconds: int = 600,
    ) -> tuple[TaskResult, ClaudeSDKClient | None]:
        """Run a task, returning the result and the live client for follow-ups."""
        options = self._build_options(model_id)
        client = ClaudeSDKClient(options=options)
        try:
            await client.connect()
        except Exception as e:
            error_info = self._format_error(e)
            await feedback.send_error(channel, thread_ts, error_info)
            return TaskResult(success=False, summary=error_info), None

        result = await self._execute_turn(
            client, task_text, feedback, channel, thread_ts, timeout_seconds
        )
        # Don't disconnect — keep client alive for follow-ups
        return result, client

    def _format_error(self, error: Exception) -> str:
        message = str(error)
        if (
            "Failed to authenticate" in message
            or "authentication_error" in message
            or "Invalid authentication credentials" in message
        ):
            return (
                "Claude Code authentication failed. The bot host's Claude session looks stale. "
                "Run `claude auth logout` and `claude auth login` on the bot machine, then retry."
            )
        return message

    async def continue_session(
        self,
        client: ClaudeSDKClient,
        task_text: str,
        feedback: SlackFeedback,
        channel: str,
        thread_ts: str,
        timeout_seconds: int = 600,
    ) -> TaskResult:
        """Continue an existing session with a follow-up message."""
        return await self._execute_turn(
            client, task_text, feedback, channel, thread_ts, timeout_seconds
        )

    async def _execute_turn(
        self,
        client: ClaudeSDKClient,
        task_text: str,
        feedback: SlackFeedback,
        channel: str,
        thread_ts: str,
        timeout_seconds: int,
    ) -> TaskResult:
        progress = await feedback.create_progress(channel, thread_ts)
        last_text = ""

        try:
            async with asyncio.timeout(timeout_seconds):
                await client.query(task_text)
                async for message in client.receive_response():
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                last_text = block.text
                                await feedback.update_progress(progress, block.text[:300])
                            elif isinstance(block, ToolUseBlock):
                                await feedback.update_progress(progress, f"Running: `{block.name}`...")
                    elif isinstance(message, ResultMessage):
                        cost = getattr(message, "total_cost_usd", None)
                        return TaskResult(
                            success=True,
                            summary=last_text,
                            cost_usd=cost,
                            progress_handle=progress,
                        )

        except TimeoutError:
            await feedback.send_error(channel, thread_ts, f"Task timed out after {timeout_seconds}s")
            return TaskResult(success=False, summary="Timed out")
        except Exception as e:
            error_info = self._format_error(e)
            await feedback.send_error(channel, thread_ts, error_info)
            return TaskResult(success=False, summary=error_info)

        return TaskResult(success=True, summary=last_text, progress_handle=progress)
