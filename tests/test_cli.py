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
