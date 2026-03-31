import os
import sys
import tempfile
import importlib
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def headroom_dir(tmp_path, monkeypatch):
    d = tmp_path / ".headroom"
    monkeypatch.setattr("scripts.manager.HEADROOM_DIR", d)
    monkeypatch.setattr("scripts.manager.SESSIONS_DIR", d / "sessions")
    monkeypatch.setattr("scripts.manager.PORT_FILE", d / "proxy.port")
    monkeypatch.setattr("scripts.manager.MCP_SENTINEL", d / ".mcp_installed")
    monkeypatch.setattr("scripts.manager.LOG_FILE", d / "manager.log")
    return d


def test_log_creates_file_and_writes_timestamp(headroom_dir, monkeypatch):
    import scripts.manager as m
    m.ensure_dirs()
    m.log("hello world")
    log_content = (headroom_dir / "manager.log").read_text()
    assert "hello world" in log_content
    assert "20" in log_content  # year present in timestamp


def test_ensure_dirs_creates_sessions(headroom_dir, monkeypatch):
    import scripts.manager as m
    m.ensure_dirs()
    assert (headroom_dir / "sessions").is_dir()


def test_missing_args_exits_nonzero():
    result = os.system("python3 scripts/manager.py 2>/dev/null")
    assert result != 0


def test_invalid_command_exits_nonzero():
    result = os.system("python3 scripts/manager.py badcmd 123 2>/dev/null")
    assert result != 0
