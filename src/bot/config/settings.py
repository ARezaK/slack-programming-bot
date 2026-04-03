import json
from functools import lru_cache
from pathlib import Path

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
