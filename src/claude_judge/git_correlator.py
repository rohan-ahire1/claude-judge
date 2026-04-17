"""Wraps `git log` for session-window correlation.

Given a repo root + time window, returns the commits made in that window,
their changed files, and a count of revert-commits (subject starts with
'Revert '). Slice 6+ can extend this to match reverts to specific undone
commits by SHA.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class GitCommit:
    sha: str
    timestamp: datetime
    subject: str
    files_changed: list[str] = field(default_factory=list)


@dataclass
class GitWindow:
    commits: list[GitCommit] = field(default_factory=list)
    reverts_matched: int = 0


_SENTINEL = "\x1e"  # record separator — safe to use inside commit messages
_FIELD = "\x1f"  # unit separator


class GitCorrelator:
    def __init__(self, repo_root: Path) -> None:
        self._root = Path(repo_root)

    def window(self, since: datetime, until: datetime) -> GitWindow:
        if not (self._root / ".git").exists() and not _is_git_worktree(self._root):
            return GitWindow()

        # Sentinel goes at the START of each record so the file list (emitted
        # by --name-only AFTER the pretty-format line) is cleanly associated
        # with its parent commit.
        fmt = _SENTINEL + _FIELD.join(["%H", "%aI", "%s"])
        try:
            raw = subprocess.run(
                [
                    "git",
                    "log",
                    "--name-only",
                    f"--since={since.isoformat()}",
                    f"--until={until.isoformat()}",
                    f"--pretty=format:{fmt}",
                    "--all",
                ],
                cwd=self._root,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return GitWindow()
        if raw.returncode != 0:
            return GitWindow()

        commits = list(_parse_log(raw.stdout))
        reverts = sum(1 for c in commits if c.subject.startswith("Revert "))
        return GitWindow(commits=commits, reverts_matched=reverts)


def _is_git_worktree(path: Path) -> bool:
    # Worktrees have a `.git` *file* (not dir) pointing at the shared gitdir.
    git_path = path / ".git"
    return git_path.exists()


def _parse_log(raw: str) -> list[GitCommit]:
    if not raw.strip():
        return []
    records = [r for r in raw.split(_SENTINEL) if r.strip()]
    out: list[GitCommit] = []
    for rec in records:
        header, _, file_block = rec.partition("\n")
        parts = header.split(_FIELD)
        if len(parts) != 3:
            continue
        sha, ts_iso, subject = parts
        try:
            ts = datetime.fromisoformat(ts_iso)
        except ValueError:
            continue
        files = [line for line in file_block.splitlines() if line.strip()]
        out.append(GitCommit(sha=sha.strip(), timestamp=ts, subject=subject, files_changed=files))
    return out
