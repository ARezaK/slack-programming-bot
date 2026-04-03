# Slack-Controlled AI Coding Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Slack bot that receives coding tasks via @mentions, dispatches them to Claude Code (via Agent SDK), and streams progress + results back into the Slack thread.

**Architecture:** Single-process Slack Bolt app in Socket Mode (no HTTP server needed). Each task spawns an async task running the Claude Agent SDK. Model routing via environment variables (Anthropic direct or LiteLLM proxy for local models).

**Tech Stack:** Python 3.11+, uv, slack-bolt, claude-agent-sdk, pydantic-settings, pytest

**Spec:** `docs/superpowers/specs/2026-04-03-slack-coding-agent-design.md`

---

### Task 1: Project Scaffolding (uv + pyproject.toml + directory structure)

**Files:**
- Create: `pyproject.toml`
- Create: `src/bot/__init__.py`
- Create: `src/bot/slack/__init__.py`
- Create: `src/bot/executor/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Initialize uv project with pyproject.toml**

```toml
# pyproject.toml
[project]
name = "slack-programming-bot"
version = "0.1.0"
description = "Slack-controlled AI coding agent"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "slack-bolt>=1.20.0",
    "aiohttp>=3.9.0",
    "claude-agent-sdk>=0.1.50",
    "pydantic-settings>=2.5.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
]

[project.scripts]
bot-cli = "bot.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/bot"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create .env.example**

```
SLACK_BOT_TOKEN=xoxb-your-token
SLACK_APP_TOKEN=xapp-your-token
ANTHROPIC_API_KEY=sk-ant-your-key
REPOS_BASE_DIR=/Users/Shared/github
LITELLM_URL=http://localhost:4000
DEFAULT_MODEL=sonnet
TASK_TIMEOUT_SECONDS=600
```

- [ ] **Step 3: Create directory structure and __init__.py files**

```bash
mkdir -p src/bot/slack src/bot/executor config tests
touch src/bot/__init__.py src/bot/slack/__init__.py src/bot/executor/__init__.py tests/__init__.py
```

- [ ] **Step 4: Run uv sync to install dependencies**

Run: `uv sync --all-extras`
Expected: All dependencies installed, `.venv` created

- [ ] **Step 5: Verify imports work**

Run: `uv run python -c "import slack_bolt; import pydantic_settings; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: scaffold project with uv, dependencies, and directory structure"
```

---

### Task 2: Settings Module (pydantic-settings)

**Files:**
- Create: `config/settings.py`
- Create: `config/models.json`
- Create: `tests/test_settings.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_settings.py
import os
import pytest
from bot.config.settings import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("REPOS_BASE_DIR", "/tmp/repos")
    monkeypatch.setenv("DEFAULT_MODEL", "opus")
    monkeypatch.setenv("TASK_TIMEOUT_SECONDS", "300")

    settings = Settings()
    assert settings.slack_bot_token == "xoxb-test"
    assert settings.slack_app_token == "xapp-test"
    assert settings.anthropic_api_key == "sk-ant-test"
    assert settings.repos_base_dir == "/tmp/repos"
    assert settings.default_model == "opus"
    assert settings.task_timeout_seconds == 300


def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    settings = Settings()
    assert settings.default_model == "sonnet"
    assert settings.task_timeout_seconds == 600
    assert settings.litellm_url == "http://localhost:4000"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_settings.py -v`
Expected: FAIL (cannot import `bot.config.settings`)

- [ ] **Step 3: Create the config package and settings module**

First, make `config/` a Python package inside `src/bot/`:

```bash
mkdir -p src/bot/config
touch src/bot/config/__init__.py
```

```python
# src/bot/config/__init__.py
from bot.config.settings import Settings, get_settings, load_models, load_repos

__all__ = ["Settings", "get_settings", "load_models", "load_repos"]
```

```python
# src/bot/config/settings.py
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    slack_bot_token: str
    slack_app_token: str
    anthropic_api_key: str
    repos_base_dir: str = "/Users/Shared/github"
    litellm_url: str = "http://localhost:4000"
    default_model: str = "sonnet"
    task_timeout_seconds: int = 600


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_settings.py -v`
Expected: 2 PASSED

- [ ] **Step 5: Create models.json**

```json
{
  "sonnet": {"provider": "anthropic", "model_id": "claude-sonnet-4-20250514"},
  "opus": {"provider": "anthropic", "model_id": "claude-opus-4-0-20250516"},
  "haiku": {"provider": "anthropic", "model_id": "claude-haiku-4-5-20251001"},
  "qwen3": {"provider": "litellm", "model_id": "ollama/qwen3"},
  "local": {"provider": "litellm", "model_id": "ollama/qwen3"}
}
```

Save to: `config/models.json`

- [ ] **Step 6: Add model loading to settings**

Add test first:

```python
# append to tests/test_settings.py
import json
from pathlib import Path
from bot.config.settings import load_models


def test_load_models(tmp_path):
    models_file = tmp_path / "models.json"
    models_file.write_text(json.dumps({
        "sonnet": {"provider": "anthropic", "model_id": "claude-sonnet-4-20250514"},
        "local": {"provider": "litellm", "model_id": "ollama/qwen3"},
    }))
    models = load_models(models_file)
    assert models["sonnet"]["provider"] == "anthropic"
    assert models["local"]["model_id"] == "ollama/qwen3"


def test_load_models_missing_file():
    with pytest.raises(FileNotFoundError):
        load_models(Path("/nonexistent/models.json"))
```

Then implement:

```python
# append to src/bot/config/settings.py
import json
from pathlib import Path


def _find_project_root() -> Path:
    """Walk up from this file to find the directory containing pyproject.toml."""
    p = Path(__file__).resolve()
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    raise FileNotFoundError("Cannot find project root (no pyproject.toml found)")


def load_models(path: Path | None = None) -> dict:
    if path is None:
        path = _find_project_root() / "config" / "models.json"
    return json.loads(path.read_text())


def load_repos(path: Path | None = None) -> dict:
    if path is None:
        path = _find_project_root() / "config" / "repos.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())
```

- [ ] **Step 7: Run all tests**

Run: `uv run pytest tests/test_settings.py -v`
Expected: 4 PASSED

- [ ] **Step 8: Commit**

```bash
git add src/bot/config/ config/models.json tests/test_settings.py
git commit -m "feat: add settings module with pydantic-settings and model registry"
```

---

### Task 3: Slack Feedback Module

**Files:**
- Create: `src/bot/slack/feedback.py`
- Create: `tests/test_feedback.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_feedback.py
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock
from bot.slack.feedback import SlackFeedback


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.chat_postMessage = AsyncMock(return_value={"ts": "1234.5678"})
    client.chat_update = AsyncMock(return_value={"ok": True})
    return client


@pytest.mark.asyncio
async def test_send_ack(mock_client):
    fb = SlackFeedback(mock_client)
    await fb.send_ack("C123", "1111.0000", "sonnet")
    mock_client.chat_postMessage.assert_called_once()
    call_kwargs = mock_client.chat_postMessage.call_args.kwargs
    assert call_kwargs["channel"] == "C123"
    assert call_kwargs["thread_ts"] == "1111.0000"
    assert "sonnet" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_create_and_update_progress(mock_client):
    fb = SlackFeedback(mock_client)
    handle = await fb.create_progress("C123", "1111.0000")
    assert handle is not None

    await fb.update_progress(handle, "Running tests...")
    mock_client.chat_update.assert_called_once()
    call_kwargs = mock_client.chat_update.call_args.kwargs
    assert "Running tests..." in call_kwargs["text"]


@pytest.mark.asyncio
async def test_update_progress_throttled(mock_client):
    fb = SlackFeedback(mock_client, throttle_seconds=1.0)
    handle = await fb.create_progress("C123", "1111.0000")

    await fb.update_progress(handle, "Step 1")
    await fb.update_progress(handle, "Step 2")  # should be throttled

    # Only one chat_update call (throttled)
    assert mock_client.chat_update.call_count == 1


@pytest.mark.asyncio
async def test_send_summary(mock_client):
    fb = SlackFeedback(mock_client)
    await fb.send_summary("C123", "1111.0000", "Fixed 3 tests. PR: http://example.com")
    call_kwargs = mock_client.chat_postMessage.call_args.kwargs
    assert "Fixed 3 tests" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_send_error(mock_client):
    fb = SlackFeedback(mock_client)
    await fb.send_error("C123", "1111.0000", "Timeout after 600s")
    call_kwargs = mock_client.chat_postMessage.call_args.kwargs
    assert "Timeout" in call_kwargs["text"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_feedback.py -v`
Expected: FAIL (cannot import)

- [ ] **Step 3: Implement feedback module**

```python
# src/bot/slack/feedback.py
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

    async def send_summary(self, channel: str, thread_ts: str, result: str) -> None:
        await self.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=result,
        )

    async def send_error(self, channel: str, thread_ts: str, error_info: str) -> None:
        await self.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Something went wrong: {error_info}",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_feedback.py -v`
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/bot/slack/feedback.py tests/test_feedback.py
git commit -m "feat: add Slack feedback module with throttled progress updates"
```

---

### Task 4: Execution Worker (Claude Agent SDK)

**Files:**
- Create: `src/bot/executor/worker.py`
- Create: `tests/test_worker.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_worker.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bot.executor.worker import TaskRunner, TaskResult


@pytest.fixture
def mock_feedback():
    fb = AsyncMock()
    fb.create_progress = AsyncMock(return_value=MagicMock(channel="C123", thread_ts="1111.0000", message_ts="2222.0000", last_update=0.0))
    return fb


def test_build_env_anthropic():
    runner = TaskRunner(
        anthropic_api_key="sk-test",
        litellm_url="http://localhost:4000",
        repos_base_dir="/tmp/repos",
    )
    env = runner._build_env(provider="anthropic")
    assert env["ANTHROPIC_API_KEY"] == "sk-test"
    assert "ANTHROPIC_BASE_URL" not in env


def test_build_env_litellm():
    runner = TaskRunner(
        anthropic_api_key="sk-test",
        litellm_url="http://localhost:4000",
        repos_base_dir="/tmp/repos",
    )
    env = runner._build_env(provider="litellm")
    assert env["ANTHROPIC_BASE_URL"] == "http://localhost:4000"


def test_build_system_prompt():
    runner = TaskRunner(
        anthropic_api_key="sk-test",
        litellm_url="http://localhost:4000",
        repos_base_dir="/tmp/repos",
        repos_json='{"myrepo": {"path": "myrepo", "aliases": ["mr"]}}',
    )
    prompt = runner._build_system_prompt()
    assert "/tmp/repos" in prompt
    assert "myrepo" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_worker.py -v`
Expected: FAIL (cannot import)

- [ ] **Step 3: Implement the worker**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_worker.py -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/bot/executor/worker.py tests/test_worker.py
git commit -m "feat: add execution worker with Claude Agent SDK integration"
```

---

### Task 5: Slack Event Handler

**Files:**
- Create: `src/bot/slack/handler.py`
- Create: `tests/test_handler.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_handler.py
import pytest
from bot.slack.handler import extract_model, strip_bot_mention


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_handler.py -v`
Expected: FAIL (cannot import)

- [ ] **Step 3: Implement handler module**

```python
# src/bot/slack/handler.py
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
        return model, text.strip()
    return None, text.strip()


def strip_bot_mention(text: str) -> str:
    return re.sub(r"<@\w+>\s*", "", text).strip()


# Active tasks keyed by thread_ts
_active_tasks: dict[str, asyncio.Task] = {}


async def handle_mention(event: dict, client, settings: Settings) -> None:
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
        return

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_handler.py -v`
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/bot/slack/handler.py tests/test_handler.py
git commit -m "feat: add Slack event handler with model extraction and task dispatch"
```

---

### Task 6: App Entrypoint (Slack Bolt + Socket Mode)

**Files:**
- Create: `src/bot/app.py`
- Create: `tests/test_app.py`

- [ ] **Step 1: Write a basic smoke test**

```python
# tests/test_app.py
import pytest


def test_app_module_imports():
    from bot.app import create_app
    assert callable(create_app)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_app.py -v`
Expected: FAIL (cannot import)

- [ ] **Step 3: Implement app.py**

```python
# src/bot/app.py
import asyncio

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from bot.config.settings import Settings, get_settings
from bot.slack.handler import handle_mention, _active_tasks


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

        thread_ts = event["thread_ts"]
        # If there's an active task for this thread, queue the follow-up
        if thread_ts in _active_tasks:
            task_info = _active_tasks[thread_ts]
            if hasattr(task_info, "follow_up_queue"):
                await task_info.follow_up_queue.put(event.get("text", ""))

    return app


async def start(settings: Settings | None = None) -> None:
    if settings is None:
        settings = get_settings()
    app = create_app(settings)
    handler = AsyncSocketModeHandler(app, settings.slack_app_token)
    await handler.start_async()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_app.py -v`
Expected: 1 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/bot/app.py tests/test_app.py
git commit -m "feat: add Slack Bolt app entrypoint with Socket Mode"
```

---

### Task 7: CLI Module

**Files:**
- Create: `src/bot/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli.py
import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch
from bot.cli import scan_repos


def test_scan_repos_finds_git_repos(tmp_path):
    # Create fake repos
    repo1 = tmp_path / "myproject"
    repo1.mkdir()
    (repo1 / ".git").mkdir()
    (repo1 / "manage.py").touch()

    repo2 = tmp_path / "frontend-app"
    repo2.mkdir()
    (repo2 / ".git").mkdir()
    (repo2 / "package.json").touch()

    # Non-repo directory (no .git)
    non_repo = tmp_path / "random-folder"
    non_repo.mkdir()

    output = tmp_path / "repos.json"
    scan_repos(str(tmp_path), str(output))

    data = json.loads(output.read_text())
    assert "myproject" in data
    assert data["myproject"]["framework"] == "django"
    assert "mp" in data["myproject"]["aliases"] or "myproject" in data["myproject"]["aliases"]

    assert "frontend-app" in data
    assert data["frontend-app"]["framework"] == "node"

    assert "random-folder" not in data


def test_scan_repos_generates_acronym_alias(tmp_path):
    repo = tmp_path / "predictmystepscore"
    repo.mkdir()
    (repo / ".git").mkdir()

    output = tmp_path / "repos.json"
    scan_repos(str(tmp_path), str(output))

    data = json.loads(output.read_text())
    assert "pmss" in data["predictmystepscore"]["aliases"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL (cannot import)

- [ ] **Step 3: Implement CLI module**

```python
# src/bot/cli.py
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path


def _generate_acronym(name: str) -> str:
    """Generate acronym from camelCase or concatenated words."""
    # Split on common boundaries: camelCase, hyphens, underscores
    parts = re.split(r"[-_]", name)
    if len(parts) == 1:
        # Try splitting camelCase-style concatenated lowercase words
        # Heuristic: split before common words
        common_words = [
            "my", "the", "and", "for", "app", "web", "api",
            "based", "case", "step", "score", "game", "guess",
            "predict", "learning", "hard", "golf", "kinda",
        ]
        result = name.lower()
        boundaries = [0]
        for word in sorted(common_words, key=len, reverse=True):
            idx = result.find(word, boundaries[-1] if boundaries else 0)
            while idx != -1:
                if idx not in boundaries:
                    boundaries.append(idx)
                idx = result.find(word, idx + len(word))
        boundaries.sort()
        if len(boundaries) > 1:
            return "".join(result[b] for b in boundaries)
    return "".join(p[0] for p in parts if p)


def _detect_framework(repo_path: Path) -> str:
    if (repo_path / "manage.py").exists():
        return "django"
    if (repo_path / "package.json").exists():
        return "node"
    if (repo_path / "pyproject.toml").exists():
        return "python"
    if (repo_path / "Cargo.toml").exists():
        return "rust"
    if (repo_path / "go.mod").exists():
        return "go"
    return "unknown"


def _extract_keywords(repo_path: Path, limit: int = 500) -> list[str]:
    readme = None
    for name in ["README.md", "README.rst", "README.txt", "README"]:
        candidate = repo_path / name
        if candidate.exists():
            readme = candidate
            break
    if readme is None:
        return []

    text = readme.read_text(errors="ignore")[:limit].lower()
    # Extract simple words, filter out common ones
    words = set(re.findall(r"\b[a-z]{4,}\b", text))
    stopwords = {"this", "that", "with", "from", "have", "your", "will", "been", "about", "more", "some", "what", "when", "make", "like", "just", "also", "into", "over"}
    return sorted(words - stopwords)[:10]


def scan_repos(base_dir: str, output_path: str) -> None:
    base = Path(base_dir)
    result = {}

    for entry in sorted(base.iterdir()):
        if not entry.is_dir() or not (entry / ".git").exists():
            continue

        name = entry.name
        acronym = _generate_acronym(name)
        aliases = [name]
        if acronym != name and len(acronym) > 1:
            aliases.append(acronym)

        result[name] = {
            "path": name,
            "aliases": aliases,
            "keywords": _extract_keywords(entry),
            "framework": _detect_framework(entry),
        }

    Path(output_path).write_text(json.dumps(result, indent=2) + "\n")
    print(f"Found {len(result)} repos, written to {output_path}")


def main():
    parser = argparse.ArgumentParser(prog="bot-cli", description="Slack Programming Bot CLI")
    subparsers = parser.add_subparsers(dest="command")

    # scan-repos
    scan_parser = subparsers.add_parser("scan-repos", help="Scan repos and build registry")
    scan_parser.add_argument("--base-dir", default=None, help="Override REPOS_BASE_DIR")
    scan_parser.add_argument("--output", default=None, help="Output path (defaults to config/repos.json in project root)")

    # run
    subparsers.add_parser("run", help="Start the bot")

    # test-model
    test_parser = subparsers.add_parser("test-model", help="Test model connectivity")
    test_parser.add_argument("model", help="Model name from models.json")

    args = parser.parse_args()

    if args.command == "scan-repos":
        base_dir = args.base_dir
        if base_dir is None:
            from bot.config.settings import get_settings
            base_dir = get_settings().repos_base_dir
        output = args.output
        if output is None:
            from bot.config.settings import _find_project_root
            output = str(_find_project_root() / "config" / "repos.json")
        scan_repos(base_dir, output)

    elif args.command == "run":
        from bot.app import start
        asyncio.run(start())

    elif args.command == "test-model":
        from bot.config.settings import load_models
        models = load_models()
        if args.model not in models:
            print(f"Unknown model: {args.model}. Available: {', '.join(models.keys())}")
            sys.exit(1)
        config = models[args.model]
        print(f"Model: {args.model}")
        print(f"Provider: {config['provider']}")
        print(f"Model ID: {config['model_id']}")
        print("Connectivity test not yet implemented (requires running LLM call)")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: 2 PASSED

- [ ] **Step 5: Verify CLI entry point works**

Run: `uv run bot-cli --help`
Expected: Shows help with `scan-repos`, `run`, `test-model` commands

- [ ] **Step 6: Commit**

```bash
git add src/bot/cli.py tests/test_cli.py
git commit -m "feat: add CLI with scan-repos, run, and test-model commands"
```

---

### Task 8: Integration Wiring and .env.example

**Files:**
- Modify: `src/bot/slack/__init__.py`
- Modify: `src/bot/executor/__init__.py`
- Create: `.env.example` (the detailed version with comments)

- [ ] **Step 1: Wire up package exports**

```python
# src/bot/slack/__init__.py
from bot.slack.feedback import SlackFeedback
from bot.slack.handler import handle_mention, extract_model, strip_bot_mention

__all__ = ["SlackFeedback", "handle_mention", "extract_model", "strip_bot_mention"]
```

```python
# src/bot/executor/__init__.py
from bot.executor.worker import TaskRunner, TaskResult

__all__ = ["TaskRunner", "TaskResult"]
```

- [ ] **Step 2: Create .env.example**

```
# Slack tokens — get from https://api.slack.com/apps
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-level-token

# Anthropic API key
ANTHROPIC_API_KEY=sk-ant-your-key

# Base directory containing all repos
REPOS_BASE_DIR=/Users/Shared/github

# LiteLLM proxy URL (for non-Anthropic models)
LITELLM_URL=http://localhost:4000

# Default model (must match a key in config/models.json)
DEFAULT_MODEL=sonnet

# Task timeout in seconds
TASK_TIMEOUT_SECONDS=600
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add src/bot/slack/__init__.py src/bot/executor/__init__.py .env.example
git commit -m "feat: wire up package exports and add .env.example"
```

---

### Task 9: End-to-End Smoke Test

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write integration test with mocked SDK**

```python
# tests/test_integration.py
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.slack.handler import handle_mention
from bot.config.settings import Settings


@pytest.fixture
def settings(tmp_path):
    # Create models.json
    models_file = tmp_path / "config" / "models.json"
    models_file.parent.mkdir(parents=True)
    models_file.write_text(json.dumps({
        "sonnet": {"provider": "anthropic", "model_id": "claude-sonnet-4-20250514"},
    }))

    return Settings(
        slack_bot_token="xoxb-test",
        slack_app_token="xapp-test",
        anthropic_api_key="sk-ant-test",
        repos_base_dir=str(tmp_path),
    )


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.chat_postMessage = AsyncMock(return_value={"ts": "1234.5678"})
    client.chat_update = AsyncMock(return_value={"ok": True})
    return client


@pytest.fixture
def mock_result_message():
    msg = MagicMock()
    msg.total_cost_usd = 0.01
    return msg


@pytest.fixture
def mock_assistant_message():
    text_block = MagicMock()
    text_block.text = "Fixed the bug in auth.py"
    type(text_block).__name__ = "TextBlock"
    msg = MagicMock()
    msg.content = [text_block]
    return msg


@pytest.mark.asyncio
async def test_full_flow_mocked(settings, mock_client, mock_assistant_message, mock_result_message):
    """Test the full flow from Slack event to task completion with mocked SDK."""
    event = {
        "text": "<@U123> model=sonnet fix the login bug",
        "channel": "C123",
        "ts": "1111.0000",
    }

    # Mock the SDK query to return our fake messages
    async def mock_query(*args, **kwargs):
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
        
        # Yield an assistant message
        assistant = MagicMock(spec=AssistantMessage)
        text_block = MagicMock(spec=TextBlock)
        text_block.text = "Fixed the bug in auth.py"
        assistant.content = [text_block]
        yield assistant

        # Yield a result message
        result = MagicMock(spec=ResultMessage)
        result.total_cost_usd = 0.01
        yield result

    with patch("bot.executor.worker.query", side_effect=mock_query), \
         patch("bot.slack.handler.load_models", return_value={
             "sonnet": {"provider": "anthropic", "model_id": "claude-sonnet-4-20250514"},
         }), \
         patch("bot.slack.handler.load_repos", return_value={}):
        task = await handle_mention(event, mock_client, settings)
        if task:
            await task  # await the background task directly — no sleep

    # Verify ACK was sent
    calls = mock_client.chat_postMessage.call_args_list
    assert any("sonnet" in str(c) for c in calls)
```

- [ ] **Step 2: Run integration test**

Run: `uv run pytest tests/test_integration.py -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add integration smoke test with mocked SDK"
```

---

### Task 10: Slack App Setup Guide

**Files:**
- Create: `docs/slack-setup.md`

- [ ] **Step 1: Write the Slack app setup guide**

```markdown
# Slack App Setup Guide

## 1. Create a Slack App

1. Go to https://api.slack.com/apps
2. Click "Create New App" → "From scratch"
3. Name: "Coding Agent" (or whatever you prefer)
4. Select your workspace
5. Click "Create App"

## 2. Enable Socket Mode

1. Go to **Settings** → **Socket Mode** in the left sidebar
2. Toggle "Enable Socket Mode" → ON
3. When prompted, create an app-level token:
   - Token Name: "socket-mode"
   - Scope: `connections:write`
   - Click "Generate"
4. Copy the `xapp-...` token → this is your `SLACK_APP_TOKEN`

## 3. Set Bot Scopes

1. Go to **Features** → **OAuth & Permissions**
2. Under "Bot Token Scopes", add:
   - `app_mentions:read` — to receive @mentions
   - `chat:write` — to reply in threads
   - `channels:history` — to read thread replies
   - `groups:history` — for private channels (optional)

## 4. Enable Events

1. Go to **Features** → **Event Subscriptions**
2. Toggle "Enable Events" → ON
3. Under "Subscribe to bot events", add:
   - `app_mention` — triggers when someone @mentions the bot
   - `message.channels` — to catch thread replies
4. Click "Save Changes"

## 5. Install to Workspace

1. Go to **Settings** → **Install App**
2. Click "Install to Workspace"
3. Authorize the app
4. Copy the "Bot User OAuth Token" (`xoxb-...`) → this is your `SLACK_BOT_TOKEN`

## 6. Configure .env

```bash
cp .env.example .env
# Edit .env with your tokens:
# SLACK_BOT_TOKEN=xoxb-...
# SLACK_APP_TOKEN=xapp-...
# ANTHROPIC_API_KEY=sk-ant-...
```

## 7. Run the Bot

```bash
# First, scan your repos
uv run bot-cli scan-repos

# Start the bot
uv run bot-cli run
```

## 8. Test It

In any channel where the bot is added, type:
```
@Coding Agent fix the login tests in PMSS
```

To add the bot to a channel: go to the channel, click the channel name at top → "Integrations" → "Add apps" → select your bot.
```

- [ ] **Step 2: Commit**

```bash
git add docs/slack-setup.md
git commit -m "docs: add Slack app setup guide"
```

---

### Task 11: Final Verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 2: Verify CLI works**

Run: `uv run bot-cli --help`
Expected: Shows help

Run: `uv run bot-cli scan-repos --base-dir /Users/Shared/github --output /tmp/test-repos.json`
Expected: Scans repos and writes output

- [ ] **Step 3: Verify imports**

Run: `uv run python -c "from bot.app import create_app; from bot.cli import main; print('All imports OK')"`
Expected: `All imports OK`

- [ ] **Step 4: Final commit if any loose changes**

```bash
git status
# If clean, done. If not, commit.
```
