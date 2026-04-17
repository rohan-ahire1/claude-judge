import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from claude_judge.git_correlator import GitCorrelator


def _run(repo: Path, *args: str, env_extra: dict | None = None) -> str:
    env = {
        "GIT_AUTHOR_NAME": "tester",
        "GIT_AUTHOR_EMAIL": "t@x.com",
        "GIT_COMMITTER_NAME": "tester",
        "GIT_COMMITTER_EMAIL": "t@x.com",
        "HOME": str(repo),
        "PATH": __import__("os").environ["PATH"],
    }
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        ["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True
    )
    return result.stdout


def _commit(repo: Path, filename: str, content: str, ts: datetime, msg: str) -> str:
    (repo / filename).write_text(content)
    _run(repo, "add", filename)
    iso = ts.isoformat()
    env = {"GIT_AUTHOR_DATE": iso, "GIT_COMMITTER_DATE": iso}
    _run(repo, "commit", "-m", msg, env_extra=env)
    sha = _run(repo, "rev-parse", "HEAD").strip()
    return sha


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init", "-q", "-b", "main")
    return repo


def test_window_returns_commits_within_timerange(git_repo: Path) -> None:
    t0 = datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc)
    _commit(git_repo, "a.py", "v1", t0 - timedelta(hours=2), "before window")
    sha_mid = _commit(git_repo, "a.py", "v2", t0 + timedelta(minutes=10), "in window")
    _commit(git_repo, "a.py", "v3", t0 + timedelta(hours=2), "after window")

    window = GitCorrelator(git_repo).window(
        since=t0, until=t0 + timedelta(hours=1)
    )
    assert len(window.commits) == 1
    assert window.commits[0].sha == sha_mid
    assert window.commits[0].subject == "in window"


def test_window_counts_reverts_by_subject_prefix(git_repo: Path) -> None:
    t0 = datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc)
    _commit(git_repo, "a.py", "v1", t0 + timedelta(minutes=1), "add thing")
    _commit(git_repo, "a.py", "v2", t0 + timedelta(minutes=2), 'Revert "add thing"')
    _commit(git_repo, "b.py", "bb", t0 + timedelta(minutes=3), "fix something")

    window = GitCorrelator(git_repo).window(
        since=t0, until=t0 + timedelta(hours=1)
    )
    assert len(window.commits) == 3
    assert window.reverts_matched == 1


def test_window_empty_when_no_commits_in_range(git_repo: Path) -> None:
    t0 = datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc)
    _commit(git_repo, "a.py", "v1", t0 - timedelta(days=1), "old")

    window = GitCorrelator(git_repo).window(
        since=t0, until=t0 + timedelta(hours=1)
    )
    assert window.commits == []
    assert window.reverts_matched == 0


def test_commits_include_changed_files(git_repo: Path) -> None:
    t0 = datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc)
    (git_repo / "a.py").write_text("x")
    (git_repo / "b.py").write_text("y")
    _run(git_repo, "add", "a.py", "b.py")
    iso = t0.isoformat()
    _run(
        git_repo,
        "commit",
        "-m",
        "two files",
        env_extra={"GIT_AUTHOR_DATE": iso, "GIT_COMMITTER_DATE": iso},
    )

    window = GitCorrelator(git_repo).window(
        since=t0 - timedelta(minutes=1), until=t0 + timedelta(minutes=1)
    )
    assert len(window.commits) == 1
    assert set(window.commits[0].files_changed) == {"a.py", "b.py"}


def test_non_repo_returns_empty_window(tmp_path: Path) -> None:
    non_repo = tmp_path / "not-a-repo"
    non_repo.mkdir()
    window = GitCorrelator(non_repo).window(
        since=datetime(2026, 4, 17, tzinfo=timezone.utc),
        until=datetime(2026, 4, 18, tzinfo=timezone.utc),
    )
    assert window.commits == []
    assert window.reverts_matched == 0
