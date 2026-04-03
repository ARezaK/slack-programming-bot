# src/bot/executor/worker.py
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from claude_agent_sdk import query, ClaudeAgentOptions
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from bot.slack.feedback import SlackFeedback, ProgressHandle


@dataclass
class TaskResult:
    success: bool
    summary: str
    cost_usd: float | None = None


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
        anthropic_api_key: str,
        litellm_url: str,
        repos_base_dir: str,
        repos_json: str = "{}",
    ):
        self.anthropic_api_key = anthropic_api_key
        self.litellm_url = litellm_url
        self.repos_base_dir = repos_base_dir
        self.repos_json = repos_json

    def _build_env(self, provider: str) -> dict[str, str]:
        env = {"ANTHROPIC_API_KEY": self.anthropic_api_key}
        if provider == "litellm":
            env["ANTHROPIC_BASE_URL"] = self.litellm_url
        return env

    def _build_system_prompt(self) -> str:
        return SYSTEM_PROMPT_TEMPLATE.format(
            repos_base_dir=self.repos_base_dir,
            repos_json=self.repos_json,
        )

    async def run(
        self,
        task_text: str,
        model_id: str,
        provider: str,
        feedback: SlackFeedback,
        channel: str,
        thread_ts: str,
        timeout_seconds: int = 600,
    ) -> TaskResult:
        env = self._build_env(provider)
        options = ClaudeAgentOptions(
            model=model_id,
            cwd=self.repos_base_dir,
            system_prompt=self._build_system_prompt(),
            permission_mode="bypassPermissions",
            max_turns=50,
            env=env,
        )

        progress = await feedback.create_progress(channel, thread_ts)
        last_text = ""

        try:
            async with asyncio.timeout(timeout_seconds):
                async for message in query(prompt=task_text, options=options):
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
                        )

        except TimeoutError:
            await feedback.send_error(channel, thread_ts, f"Task timed out after {timeout_seconds}s")
            return TaskResult(success=False, summary="Timed out")
        except Exception as e:
            await feedback.send_error(channel, thread_ts, str(e))
            return TaskResult(success=False, summary=str(e))

        return TaskResult(success=True, summary=last_text)
