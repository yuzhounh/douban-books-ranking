from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
import subprocess


DEFAULT_REPOSITORY = "https://github.com/yuzhounh/douban-books-ranking.git"
MANAGED_PATHS = (
    Path(".gitignore"),
    Path("assets"),
    Path("data"),
    Path(".github/workflows/pages.yml"),
    Path("index.html"),
    Path(".nojekyll"),
    Path("README.md"),
)

PROJECT_PATHS = (
    (Path("pyproject.toml"), Path("pyproject.toml")),
    (Path("src"), Path("src")),
    (Path("tests"), Path("tests")),
    (Path("data/seeds"), Path("sources")),
    (Path("data/analysis/report.md"), Path("analysis/report.md")),
    (Path("data/analysis/summary.json"), Path("analysis/summary.json")),
)


@dataclass(frozen=True)
class PublishResult:
    changed: bool
    commit: str | None
    repository: str


def publish_pages(
    site_dir: Path,
    checkout_dir: Path,
    *,
    repository: str = DEFAULT_REPOSITORY,
    project_dir: Path | None = None,
) -> PublishResult:
    """Commit and push generated files to the dedicated Pages repository."""
    site_dir = site_dir.resolve()
    checkout_dir = checkout_dir.resolve()
    project_dir = (project_dir or site_dir.parent.parent).resolve()
    if not (site_dir / "index.html").is_file() or not (site_dir / "data/catalog.json").is_file():
        raise ValueError(f"网站目录不完整: {site_dir}")

    if (checkout_dir / ".git").is_dir():
        origin = _git(checkout_dir, "remote", "get-url", "origin").strip().rstrip("/")
        if _normalise_remote(origin) != _normalise_remote(repository):
            raise ValueError(f"发布目录指向了错误仓库: {origin}")
        _git(checkout_dir, "pull", "--ff-only", "origin", "main")
    else:
        if checkout_dir.exists() and any(checkout_dir.iterdir()):
            raise ValueError(f"发布目录非空且不是 Git 仓库: {checkout_dir}")
        checkout_dir.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", repository, str(checkout_dir)])

    for relative in MANAGED_PATHS:
        source = site_dir / relative
        target = checkout_dir / relative
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        if source.is_dir():
            shutil.copytree(source, target)
        elif source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    for source_relative, target_relative in PROJECT_PATHS:
        source = project_dir / source_relative
        target = checkout_dir / target_relative
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        elif source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    _git(checkout_dir, "add", "--all")
    if not _git(checkout_dir, "status", "--porcelain").strip():
        commit = _git(checkout_dir, "rev-parse", "HEAD").strip()
        return PublishResult(False, commit, repository)

    _git(checkout_dir, "config", "user.name", "Douban Books Automation")
    _git(checkout_dir, "config", "user.email", "actions@users.noreply.github.com")
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d")
    _git(checkout_dir, "commit", "-m", f"Publish book rankings ({stamp})")
    _git(checkout_dir, "push", "origin", "main")
    commit = _git(checkout_dir, "rev-parse", "HEAD").strip()
    return PublishResult(True, commit, repository)


def _normalise_remote(value: str) -> str:
    return value.removesuffix(".git").lower()


def _git(cwd: Path, *args: str) -> str:
    return _run(["git", "-C", str(cwd), *args])


def _run(command: list[str]) -> str:
    completed = subprocess.run(command, check=False, capture_output=True, text=True, encoding="utf-8")
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise OSError(f"命令执行失败 ({' '.join(command[:3])}): {detail}")
    return completed.stdout
