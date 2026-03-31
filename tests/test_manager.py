import json
import socket
import subprocess
import urllib.error
from unittest.mock import MagicMock, patch

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
    result = subprocess.run(
        ["python3", "scripts/manager.py"],
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )
    assert result.returncode != 0


def test_invalid_command_exits_nonzero():
    result = subprocess.run(
        ["python3", "scripts/manager.py", "badcmd", "123"],
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )
    assert result.returncode != 0


def test_find_free_port_returns_8787(headroom_dir, monkeypatch):
    """When 8787 is free (connect fails), return 8787."""
    import scripts.manager as m

    with patch("socket.socket") as mock_sock_cls:
        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_sock.connect_ex.return_value = 1  # free
        mock_sock_cls.return_value = mock_sock
        result = m.find_free_port()
    assert result == 8787


def test_find_free_port_skips_occupied(headroom_dir, monkeypatch):
    """When 8787 is occupied (connect succeeds), try 8788."""
    import scripts.manager as m

    def mock_connect_ex(address):
        if address[1] == 8787:
            return 0  # occupied
        return 1  # free

    with patch("socket.socket") as mock_sock_cls:
        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_sock.connect_ex.side_effect = mock_connect_ex
        mock_sock_cls.return_value = mock_sock
        result = m.find_free_port()
    assert result == 8788


def test_find_free_port_raises_when_all_occupied(headroom_dir, monkeypatch):
    """Raises RuntimeError when all ports 8787-8887 are occupied."""
    import scripts.manager as m

    with patch("socket.socket") as mock_sock_cls:
        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_sock.connect_ex.return_value = 0  # all occupied
        mock_sock_cls.return_value = mock_sock
        with pytest.raises(RuntimeError, match="No free port"):
            m.find_free_port()


def test_check_proxy_health_true(headroom_dir, monkeypatch):
    """Returns True when /health responds with status=healthy."""
    import scripts.manager as m

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"status": "healthy"}).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_response):
        assert m.check_proxy_health(8787) is True


def test_check_proxy_health_false_on_error(headroom_dir, monkeypatch):
    """Returns False on connection error."""
    import scripts.manager as m

    with patch("urllib.request.urlopen", side_effect=Exception("refused")):
        assert m.check_proxy_health(8787) is False


def test_check_proxy_health_false_on_unhealthy(headroom_dir, monkeypatch):
    """Returns False when status is not 'healthy'."""
    import scripts.manager as m

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"status": "degraded"}).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_response):
        assert m.check_proxy_health(8787) is False


def test_register_session_creates_file(headroom_dir, monkeypatch):
    import scripts.manager as m
    m.ensure_dirs()
    m.register_session("42")
    assert (headroom_dir / "sessions" / "42").exists()


def test_remove_session_deletes_file(headroom_dir, monkeypatch):
    import scripts.manager as m
    m.ensure_dirs()
    m.register_session("42")
    m.remove_session("42")
    assert not (headroom_dir / "sessions" / "42").exists()


def test_remove_session_no_error_if_missing(headroom_dir, monkeypatch):
    import scripts.manager as m
    m.ensure_dirs()
    m.remove_session("99999")  # should not raise


def test_count_sessions(headroom_dir, monkeypatch):
    import scripts.manager as m
    m.ensure_dirs()
    assert m.count_sessions() == 0
    m.register_session("1")
    m.register_session("2")
    assert m.count_sessions() == 2
    m.remove_session("1")
    assert m.count_sessions() == 1


def test_cleanup_stale_sessions_removes_dead_pids(headroom_dir, monkeypatch):
    import scripts.manager as m
    m.ensure_dirs()
    # PID 99999999 is extremely unlikely to be running
    m.register_session("99999999")
    m.cleanup_stale_sessions()
    assert not (headroom_dir / "sessions" / "99999999").exists()


def test_cleanup_stale_sessions_keeps_live_pids(headroom_dir, monkeypatch):
    import scripts.manager as m
    import os
    m.ensure_dirs()
    my_pid = str(os.getpid())
    m.register_session(my_pid)
    m.cleanup_stale_sessions()
    assert (headroom_dir / "sessions" / my_pid).exists()
    m.remove_session(my_pid)  # cleanup
