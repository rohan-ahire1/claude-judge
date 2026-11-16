import os
import stat

import pytest


@pytest.fixture(autouse=True)
def _block_real_claude_cli(tmp_path, monkeypatch):
    """Put a fake `claude` first on PATH so unmocked tests fail loudly."""
    bin_dir = tmp_path / "fake-claude-bin"
    bin_dir.mkdir()
    script = bin_dir / "claude"
    script.write_text("#!/bin/sh\necho 'real claude CLI called in tests'\nexit 99\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
