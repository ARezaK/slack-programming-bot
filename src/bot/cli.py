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
            idx = result.find(word)
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
