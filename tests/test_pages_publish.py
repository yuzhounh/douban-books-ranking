from pathlib import Path

import pytest

import douban_books.pages_publish as publisher


def _prepare_site(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    (site / "index.html").write_text("new site", encoding="utf-8")
    (site / "data" / "catalog.json").write_text("{}", encoding="utf-8")
    return site


@pytest.mark.parametrize("branch", ["feature", ""])
def test_publish_rejects_non_main_before_pull_or_file_changes(tmp_path, monkeypatch, branch):
    site = _prepare_site(tmp_path)
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    (checkout / "index.html").write_text("original site", encoding="utf-8")
    calls = []

    def fake_git(_cwd, *args):
        calls.append(args)
        if args == ("remote", "get-url", "origin"):
            return publisher.DEFAULT_REPOSITORY
        if args == ("branch", "--show-current"):
            return branch
        pytest.fail(f"Unexpected Git operation before branch rejection: {args}")

    monkeypatch.setattr(publisher, "_git", fake_git)
    with pytest.raises(ValueError, match="main"):
        publisher.publish_pages(site, checkout, project_dir=tmp_path / "project")

    assert calls == [("remote", "get-url", "origin"), ("branch", "--show-current")]
    assert (checkout / "index.html").read_text("utf-8") == "original site"
    assert not (checkout / "data").exists()


@pytest.mark.parametrize("existing_checkout", [True, False])
def test_publish_uses_main_for_existing_and_new_checkouts(tmp_path, monkeypatch, existing_checkout):
    site = _prepare_site(tmp_path)
    checkout = tmp_path / "checkout"
    if existing_checkout:
        (checkout / ".git").mkdir(parents=True)
    calls = []
    clone_calls = []

    def fake_git(_cwd, *args):
        calls.append(args)
        if args == ("remote", "get-url", "origin"):
            return publisher.DEFAULT_REPOSITORY
        if args == ("branch", "--show-current"):
            return "main"
        if args == ("status", "--porcelain"):
            return " M index.html\n"
        if args == ("rev-parse", "HEAD"):
            return "mock-main-commit"
        return ""

    def fake_run(command):
        clone_calls.append(command)
        assert command == [
            "git", "clone", "--branch", "main", publisher.DEFAULT_REPOSITORY, str(checkout)
        ]
        (checkout / ".git").mkdir(parents=True)
        return ""

    monkeypatch.setattr(publisher, "_git", fake_git)
    monkeypatch.setattr(publisher, "_run", fake_run)
    result = publisher.publish_pages(site, checkout, project_dir=tmp_path / "project")

    assert result.changed and result.commit == "mock-main-commit"
    assert (checkout / "index.html").read_text("utf-8") == "new site"
    assert ("push", "origin", "main") in calls
    if existing_checkout:
        assert calls.index(("branch", "--show-current")) < calls.index(("pull", "--ff-only", "origin", "main"))
        assert not clone_calls
    else:
        assert len(clone_calls) == 1
