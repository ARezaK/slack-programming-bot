import asyncio
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from bot.executor.worker import TaskResult, SYSTEM_PROMPT_TEMPLATE
from bot.slack.feedback import SlackFeedback


TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Read a file from disk. Returns the file contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Write",
            "description": "Write content to a file, overwriting if it exists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file."},
                    "content": {"type": "string", "description": "Full file contents to write."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Edit",
            "description": "Replace exactly one occurrence of old_string with new_string in a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Bash",
            "description": "Run a shell command. Returns stdout+stderr (truncated to 8000 chars).",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string", "description": "Working directory (optional)."},
                },
                "required": ["command"],
            },
        },
    },
]


def _truncate(s: str, limit: int = 8000) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n...[truncated, {len(s) - limit} more chars]"


async def _execute_tool(name: str, args: dict[str, Any], default_cwd: str) -> str:
    try:
        if name == "Read":
            path = args["path"]
            return _truncate(Path(path).read_text(errors="replace"))
        if name == "Write":
            path = args["path"]
            content = args["content"]
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(content)
            return f"Wrote {len(content)} chars to {path}"
        if name == "Edit":
            path = args["path"]
            old = args["old_string"]
            new = args["new_string"]
            text = Path(path).read_text()
            count = text.count(old)
            if count == 0:
                return f"ERROR: old_string not found in {path}"
            if count > 1:
                return f"ERROR: old_string appears {count} times in {path}; needs to be unique"
            Path(path).write_text(text.replace(old, new, 1))
            return f"Edited {path}"
        if name == "Bash":
            cmd = args["command"]
            cwd = args.get("cwd") or default_cwd
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=cwd,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
            except asyncio.TimeoutError:
                proc.kill()
                return "ERROR: command timed out after 120s"
            output = stdout.decode("utf-8", errors="replace")
            return _truncate(f"[exit {proc.returncode}]\n{output}")
        return f"ERROR: unknown tool {name}"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


@dataclass
class LMStudioSession:
    """Per-thread conversation state for follow-ups."""
    messages: list[dict[str, Any]] = field(default_factory=list)


class LMStudioRunner:
    """Drives an LM Studio model with a tool-execution loop, mirroring TaskRunner's interface."""

    def __init__(
        self,
        base_url: str,
        repos_base_dir: str,
        repos_json: str = "{}",
        max_iterations: int = 30,
        max_tokens: int = 8192,
    ):
        self.base_url = base_url
        self.repos_base_dir = repos_base_dir
        self.repos_json = repos_json
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.client = AsyncOpenAI(base_url=base_url, api_key=os.getenv("LMSTUDIO_API_KEY", "lm-studio"))

    def _system_prompt(self) -> str:
        return SYSTEM_PROMPT_TEMPLATE.format(
            repos_base_dir=self.repos_base_dir,
            repos_json=self.repos_json,
        )

    async def run(
        self,
        task_text: str,
        model_id: str,
        feedback: SlackFeedback,
        channel: str,
        thread_ts: str,
        timeout_seconds: int = 600,
    ) -> tuple[TaskResult, LMStudioSession]:
        session = LMStudioSession(messages=[{"role": "system", "content": self._system_prompt()}])
        result = await self._execute_turn(
            session, task_text, model_id, feedback, channel, thread_ts, timeout_seconds
        )
        return result, session

    async def continue_session(
        self,
        client: LMStudioSession,
        task_text: str,
        feedback: SlackFeedback,
        channel: str,
        thread_ts: str,
        timeout_seconds: int = 600,
        model_id: str | None = None,
    ) -> TaskResult:
        if model_id is None:
            raise ValueError("LMStudioRunner.continue_session requires model_id")
        return await self._execute_turn(
            client, task_text, model_id, feedback, channel, thread_ts, timeout_seconds
        )

    async def _execute_turn(
        self,
        session: LMStudioSession,
        task_text: str,
        model_id: str,
        feedback: SlackFeedback,
        channel: str,
        thread_ts: str,
        timeout_seconds: int,
    ) -> TaskResult:
        session.messages.append({"role": "user", "content": task_text})
        progress = await feedback.create_progress(channel, thread_ts)
        last_text = ""

        try:
            async with asyncio.timeout(timeout_seconds):
                for _ in range(self.max_iterations):
                    response = await self.client.chat.completions.create(
                        model=model_id,
                        messages=session.messages,
                        tools=TOOLS_SCHEMA,
                        max_tokens=self.max_tokens,
                    )
                    msg = response.choices[0].message
                    assistant_entry: dict[str, Any] = {"role": "assistant"}
                    if msg.content:
                        assistant_entry["content"] = msg.content
                        last_text = msg.content
                        await feedback.update_progress(progress, msg.content[:300])
                    if msg.tool_calls:
                        assistant_entry["tool_calls"] = [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                            }
                            for tc in msg.tool_calls
                        ]
                    session.messages.append(assistant_entry)

                    if not msg.tool_calls:
                        return TaskResult(
                            success=True,
                            summary=last_text or "(no text)",
                            cost_usd=None,
                            progress_handle=progress,
                        )

                    for tc in msg.tool_calls:
                        try:
                            args = json.loads(tc.function.arguments or "{}")
                        except json.JSONDecodeError as e:
                            tool_result = f"ERROR: invalid JSON arguments: {e}"
                        else:
                            await feedback.update_progress(progress, f"Running: `{tc.function.name}`...")
                            tool_result = await _execute_tool(tc.function.name, args, self.repos_base_dir)
                        session.messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": tool_result,
                        })

                await feedback.send_error(channel, thread_ts, f"Hit max iterations ({self.max_iterations})")
                return TaskResult(success=False, summary=f"Max iterations reached. Last text: {last_text}")

        except asyncio.TimeoutError:
            await feedback.send_error(channel, thread_ts, f"Task timed out after {timeout_seconds}s")
            return TaskResult(success=False, summary="Timed out")
        except Exception as e:
            await feedback.send_error(channel, thread_ts, f"{type(e).__name__}: {e}")
            return TaskResult(success=False, summary=str(e))
