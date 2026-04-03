# Slack-Controlled AI Coding Agent — Design Spec

## Overview

A Python application that lets users issue coding tasks via Slack mentions, routes them to an AI coding agent (Claude Code) running against a local repo, and streams progress + results back into the same Slack thread. Supports multiple repos and multiple models (Anthropic cloud + local models via LiteLLM proxy).

## Architecture

Single-process monolith: one FastAPI app running Slack Bolt in Socket Mode. No message queue, no microservices. Each incoming task spawns an async task that runs the Claude Agent SDK and streams results back to Slack.

```
Slack Thread
   ↓
Slack Bolt (Socket Mode — no public URL needed)
   ↓
handler.py — extract model= hint, ACK in thread
   ↓
worker.py — launch Claude Agent SDK with correct model + env vars
   ↓
Claude Code CLI (via SDK) — starts at REPOS_BASE_DIR, agent navigates to correct repo
   ↓
feedback.py — stream progress + final summary back to Slack thread
```

## Project Structure

```
slack-programming-bot/
├── pyproject.toml
├── .env.example
├── .env                    # gitignored
├── config/
│   ├── settings.py         # pydantic-settings, loads .env
│   ├── repos.json          # repo registry (aliases, keywords, paths)
│   └── models.json         # model registry (provider, model_id)
├── src/
│   └── bot/
│       ├── __init__.py
│       ├── app.py          # FastAPI + Slack Bolt setup
│       ├── cli.py          # CLI commands (scan-repos, run, test-model)
│       ├── slack/
│       │   ├── __init__.py
│       │   ├── handler.py  # Slack event handlers
│       │   └── feedback.py # Thread update helpers
│       └── executor/
│           ├── __init__.py
│           └── worker.py   # Claude Agent SDK execution
└── tests/
    └── ...
```

## Dependencies

- `slack-bolt` — Slack Events API + Socket Mode
- `fastapi` + `uvicorn` — web server
- `claude-agent-sdk` — Claude Code execution (replaces deprecated claude-code-sdk)
- `pydantic-settings` — typed config from .env
- `pytest` + `pytest-asyncio` — testing

LiteLLM is used as an external proxy (not a Python dependency) — run separately for all non-Anthropic models. Required because Ollama and other local providers use OpenAI-compatible APIs, not the Anthropic Messages API. LiteLLM translates between the two formats.

## Configuration

### Environment Variables (.env)

```
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
ANTHROPIC_API_KEY=sk-ant-...
REPOS_BASE_DIR=/Users/Shared/github
LITELLM_URL=http://localhost:4000
DEFAULT_MODEL=sonnet
TASK_TIMEOUT_SECONDS=600
```

### Repo Registry (config/repos.json)

Populated by `scan-repos` CLI command, then hand-editable.

```json
{
  "predictmystepscore": {
    "path": "predictmystepscore",
    "aliases": ["pmss", "predict my step score"],
    "keywords": ["usmle", "score", "step", "stripe"],
    "framework": "django"
  }
}
```

The `path` field is relative to `REPOS_BASE_DIR`.

### Model Registry (config/models.json)

```json
{
  "sonnet": {"provider": "anthropic", "model_id": "claude-sonnet-4-20250514"},
  "opus": {"provider": "anthropic", "model_id": "claude-opus-4-0-20250516"},
  "haiku": {"provider": "anthropic", "model_id": "claude-haiku-4-5-20251001"},
  "qwen3": {"provider": "litellm", "model_id": "ollama/qwen3"},
  "local": {"provider": "litellm", "model_id": "ollama/qwen3"}
}
```

Adding a new model = one line in this JSON.

## Slack Event Flow

### Message Handling

1. User posts `@bot model=qwen3 fix the login tests in PMSS`
2. Slack sends `app_mention` event via Socket Mode WebSocket
3. `handler.py` receives event, extracts `model=qwen3` via regex, strips it from message
4. Posts ACK in thread: "Working on this using `qwen3`" (model only — repo is resolved by the agent later)
5. Spawns async task → `worker.py`
6. Agent determines correct repo from message + `repos.json`
7. Progress streamed back to thread via `feedback.py`
8. Final summary posted when agent completes

### Model Extraction

Simple regex: if message contains `model=<value>`, extract and strip it. Otherwise use `DEFAULT_MODEL` from settings.

### Thread Follow-ups

Thread replies are detected via Slack `message` events filtered by `thread_ts` matching an active task.

- **Agent still running:** The reply is placed on an `asyncio.Queue` associated with that task. The worker checks this queue between agent turns and feeds new messages as follow-up prompts via `query()`.
- **Agent finished:** A new agent session is started in the same repo/model context, with the original task + follow-up as the prompt.

## Execution Engine

### How Claude Agent SDK Routes to Different Providers

All tasks run through Claude Agent SDK (which shells out to Claude Code CLI). The model provider is controlled by environment variables set on `ClaudeAgentOptions` per-task:

```python
from claude_agent_sdk import query, ClaudeAgentOptions

# Build env vars based on provider
env = {"ANTHROPIC_API_KEY": settings.ANTHROPIC_API_KEY}
if provider == "litellm":
    env["ANTHROPIC_BASE_URL"] = settings.LITELLM_URL

options = ClaudeAgentOptions(
    model=model_id,
    cwd=settings.REPOS_BASE_DIR,    # agent navigates to correct repo via repos.json
    max_turns=50,
    system_prompt=SYSTEM_PROMPT,
    env=env,
)

async for event in query(prompt=task_text, options=options):
    # stream events to Slack
```

- **Anthropic models** → default ANTHROPIC_BASE_URL (Anthropic API direct)
- **All non-Anthropic models (Ollama, vLLM, OpenAI, etc.)** → ANTHROPIC_BASE_URL points to LiteLLM proxy, which translates between the Anthropic Messages API format and the target provider's API format

**Why LiteLLM is required for local models:** Ollama and other local providers expose OpenAI-compatible APIs (`/v1/chat/completions`), not the Anthropic Messages API (`/v1/messages`). Claude Code CLI speaks only the Anthropic protocol. LiteLLM bridges this gap by accepting Anthropic-format requests and translating them to the target provider's format.

Valid `provider` values in `models.json`: `"anthropic"`, `"litellm"`.

No split code paths. One execution engine.

### System Prompt

The agent receives a system prompt that includes:
- Instructions to use `repos.json` to determine which repo to work in
- Path to `REPOS_BASE_DIR` so it can navigate to the correct directory
- Instructions to summarize work, create branches, and offer PRs when appropriate

### Caveats

Tool-use quality depends on model capability. Local models may struggle with complex multi-file edits that Opus handles well. This is a model limitation, not an architecture limitation.

## Slack Feedback System

Three messages per task — not 30:

1. **ACK** — immediate confirmation with model info (repo resolved later by agent)
2. **Progress** — single message updated in-place via `chat.update` as agent works
   - "Scanning repo..." → "Running tests..." → "Editing auth.py..." → "Committing..."
3. **Summary** — final message with results, diff summary, PR link if applicable

### feedback.py API

- `send_ack(channel, thread_ts, model)` — initial acknowledgment
- `create_progress(channel, thread_ts)` → returns message handle
- `update_progress(handle, status_text)` — edits progress message in-place (throttled to max once per 3 seconds to respect Slack rate limits)
- `send_summary(channel, thread_ts, result)` — final result
- `send_error(channel, thread_ts, error_info)` — post error with options for user

### Timeouts

Default task timeout: 10 minutes. Configurable via `TASK_TIMEOUT_SECONDS` env var. Also limited by `max_turns=50` on the agent. On timeout, the agent process is cancelled and `send_error` is called.

### Error Handling

On failure or timeout, post a message asking user how to proceed rather than silently failing.

## CLI Commands

All run via `uv run bot-cli <command>` (registered as a script entry point in `pyproject.toml`):

- `scan-repos` — scan `REPOS_BASE_DIR`, find git repos, populate `config/repos.json`. Alias generation: directory name + first-letter acronym (e.g., `predictmystepscore` → `pmss`). Framework detection: check for `manage.py` (Django), `package.json` (Node), `pyproject.toml` (Python). Keywords: extracted from first 500 chars of README if present.
- `run` — start the bot (FastAPI + Slack Bolt in Socket Mode)
- `test-model <name>` — smoke test that a model is reachable and responds

## Safety & Guardrails

- Agent operates within `REPOS_BASE_DIR` only
- Each task is an isolated async task — no shared state between tasks
- Dangerous actions (push, migrations) are gated by the agent's own safety checks
- Every action is logged in the Slack thread (audit trail)

## Out of Scope (Future)

- Redis/Celery task queue (not needed until concurrent load is high)
- Plan vs Execute mode
- Multi-repo tasks
- Model escalation (try cheap → escalate to expensive)
- Persistent memory per repo/user
