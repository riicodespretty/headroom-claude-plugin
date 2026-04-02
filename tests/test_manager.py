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


def test_start_proxy_raises_if_headroom_missing(headroom_dir, monkeypatch, tmp_path):
    """Raises FileNotFoundError when ~/.venv/bin/headroom doesn't exist."""
    import scripts.manager as m
    from pathlib import Path
    monkeypatch.setattr("scripts.manager.HEADROOM_BIN", Path("/nonexistent/headroom"))
    with pytest.raises(FileNotFoundError, match="headroom not found"):
        m.start_proxy(8787)

def test_start_proxy_launches_detached(headroom_dir, monkeypatch, tmp_path):
    """Calls subprocess.Popen with correct args and start_new_session=True."""
    import scripts.manager as m
    from unittest.mock import patch, MagicMock
    from pathlib import Path
    fake_bin = tmp_path / "headroom"
    fake_bin.touch()
    monkeypatch.setattr("scripts.manager.HEADROOM_BIN", fake_bin)
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        m.start_proxy(8790)
        call_kwargs = mock_popen.call_args
        args = call_kwargs[0][0]
        assert str(fake_bin) in args
        assert "--port" in args
        assert "8790" in args or 8790 in args
        assert call_kwargs[1].get("start_new_session") is True

def test_wait_for_proxy_returns_true_when_healthy(headroom_dir, monkeypatch):
    """Returns True once health check passes."""
    import scripts.manager as m
    from unittest.mock import patch
    with patch("scripts.manager.check_proxy_health", return_value=True):
        assert m.wait_for_proxy(8787) is True

def test_wait_for_proxy_raises_on_timeout(headroom_dir, monkeypatch):
    """Raises TimeoutError when health check never passes within timeout."""
    import scripts.manager as m
    from unittest.mock import patch
    with patch("scripts.manager.check_proxy_health", return_value=False), \
         patch("time.sleep"):
        with pytest.raises(TimeoutError, match="did not become healthy"):
            m.wait_for_proxy(8787, timeout=0.1)


def test_update_anthropic_base_url_sets_env(tmp_path, monkeypatch):
    import scripts.manager as m
    import json
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"other": "value"}))
    monkeypatch.setattr("scripts.manager.CLAUDE_SETTINGS", settings_file)
    m.update_anthropic_base_url(8787)
    result = json.loads(settings_file.read_text())
    assert result["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8787"
    assert result["other"] == "value"  # preserved

def test_update_anthropic_base_url_creates_env_block(tmp_path, monkeypatch):
    import scripts.manager as m
    import json
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}")
    monkeypatch.setattr("scripts.manager.CLAUDE_SETTINGS", settings_file)
    m.update_anthropic_base_url(9000)
    result = json.loads(settings_file.read_text())
    assert result["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:9000"

def test_update_anthropic_base_url_overwrites_existing(tmp_path, monkeypatch):
    import scripts.manager as m
    import json
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"}}))
    monkeypatch.setattr("scripts.manager.CLAUDE_SETTINGS", settings_file)
    m.update_anthropic_base_url(8788)
    result = json.loads(settings_file.read_text())
    assert result["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8788"

def test_update_anthropic_base_url_clears_when_none(tmp_path, monkeypatch):
    import scripts.manager as m
    import json
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787", "OTHER": "value"}}))
    monkeypatch.setattr("scripts.manager.CLAUDE_SETTINGS", settings_file)
    m.update_anthropic_base_url(None)
    result = json.loads(settings_file.read_text())
    assert "ANTHROPIC_BASE_URL" not in result["env"]
    assert result["env"]["OTHER"] == "value"

def test_update_anthropic_base_url_raises_if_no_settings(tmp_path, monkeypatch):
    import scripts.manager as m
    monkeypatch.setattr("scripts.manager.CLAUDE_SETTINGS", tmp_path / "nonexistent.json")
    with pytest.raises(FileNotFoundError):
        m.update_anthropic_base_url(8787)


def test_ensure_mcp_skips_if_sentinel_exists(headroom_dir, monkeypatch):
    import scripts.manager as m
    from unittest.mock import patch
    m.ensure_dirs()
    sentinel = headroom_dir / ".mcp_installed"
    sentinel.touch()
    monkeypatch.setattr("scripts.manager.MCP_SENTINEL", sentinel)
    with patch("subprocess.run") as mock_run:
        m.ensure_mcp_installed()
        mock_run.assert_not_called()

def test_ensure_mcp_runs_install_when_absent(headroom_dir, monkeypatch, tmp_path):
    import scripts.manager as m
    from unittest.mock import patch, MagicMock
    fake_bin = tmp_path / "headroom"
    fake_bin.touch()
    sentinel = headroom_dir / ".mcp_installed"
    monkeypatch.setattr("scripts.manager.HEADROOM_BIN", fake_bin)
    monkeypatch.setattr("scripts.manager.MCP_SENTINEL", sentinel)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        m.ensure_mcp_installed()
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "mcp" in call_args
        assert "install" in call_args

def test_ensure_mcp_creates_sentinel_on_success(headroom_dir, monkeypatch, tmp_path):
    import scripts.manager as m
    from unittest.mock import patch, MagicMock
    fake_bin = tmp_path / "headroom"
    fake_bin.touch()
    sentinel = headroom_dir / ".mcp_installed"
    monkeypatch.setattr("scripts.manager.HEADROOM_BIN", fake_bin)
    monkeypatch.setattr("scripts.manager.MCP_SENTINEL", sentinel)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        m.ensure_mcp_installed()
        assert sentinel.exists()

def test_ensure_mcp_does_not_raise_on_failure(headroom_dir, monkeypatch, tmp_path):
    import scripts.manager as m
    from unittest.mock import patch, MagicMock
    fake_bin = tmp_path / "headroom"
    fake_bin.touch()
    sentinel = headroom_dir / ".mcp_installed"
    monkeypatch.setattr("scripts.manager.HEADROOM_BIN", fake_bin)
    monkeypatch.setattr("scripts.manager.MCP_SENTINEL", sentinel)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        m.ensure_mcp_installed()  # must not raise
        assert not sentinel.exists()


def test_cmd_start_full_flow_new_proxy(headroom_dir, monkeypatch, tmp_path):
    """cmd_start launches proxy, registers session, updates settings when no proxy running."""
    import scripts.manager as m
    import json
    from unittest.mock import patch, MagicMock
    fake_bin = tmp_path / "headroom"
    fake_bin.touch()
    sentinel = headroom_dir / ".mcp_installed"
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}")
    monkeypatch.setattr("scripts.manager.HEADROOM_BIN", fake_bin)
    monkeypatch.setattr("scripts.manager.MCP_SENTINEL", sentinel)
    monkeypatch.setattr("scripts.manager.CLAUDE_SETTINGS", settings_file)
    with patch("scripts.manager.check_proxy_health", return_value=False), \
         patch("scripts.manager.find_free_port", return_value=8787), \
         patch("scripts.manager.start_proxy") as mock_start, \
         patch("scripts.manager.wait_for_proxy", return_value=True), \
         patch("subprocess.run", return_value=MagicMock(returncode=0)):
        m.cmd_start("42")
    assert (headroom_dir / "sessions" / "42").exists()
    assert (headroom_dir / "proxy.port").read_text() == "8787"
    result = json.loads(settings_file.read_text())
    assert result["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8787"
    mock_start.assert_called_once_with(8787)

def test_cmd_start_reuses_running_proxy(headroom_dir, monkeypatch, tmp_path):
    """cmd_start skips start_proxy when proxy already healthy."""
    import scripts.manager as m
    from unittest.mock import patch, MagicMock
    (headroom_dir / "proxy.port").parent.mkdir(parents=True, exist_ok=True)
    (headroom_dir / "proxy.port").write_text("8787")
    (headroom_dir / ".mcp_installed").touch()
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}")
    monkeypatch.setattr("scripts.manager.CLAUDE_SETTINGS", settings_file)
    with patch("scripts.manager.check_proxy_health", return_value=True), \
         patch("scripts.manager.start_proxy") as mock_start:
        m.cmd_start("43")
    mock_start.assert_not_called()
    assert (headroom_dir / "sessions" / "43").exists()

def test_cmd_stop_kills_proxy_when_last_session(headroom_dir, monkeypatch, tmp_path):
    """cmd_stop kills proxy and removes port file when no sessions remain."""
    import scripts.manager as m
    from unittest.mock import patch
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}")
    monkeypatch.setattr("scripts.manager.CLAUDE_SETTINGS", settings_file)
    m.ensure_dirs()
    m.register_session("99")
    (headroom_dir / "proxy.port").write_text("8787")
    with patch("scripts.manager.kill_proxy") as mock_kill:
        m.cmd_stop("99")
    mock_kill.assert_called_once_with(8787)
    assert not (headroom_dir / "proxy.port").exists()

def test_cmd_stop_leaves_proxy_when_sessions_remain(headroom_dir, monkeypatch):
    """cmd_stop does not kill proxy when other sessions are still running."""
    import scripts.manager as m
    import os
    from unittest.mock import patch
    m.ensure_dirs()
    m.register_session(str(os.getpid()))  # live session
    m.register_session("88")
    (headroom_dir / "proxy.port").write_text("8787")
    with patch("scripts.manager.kill_proxy") as mock_kill:
        m.cmd_stop("88")
    mock_kill.assert_not_called()
    m.remove_session(str(os.getpid()))  # cleanup

def test_cmd_stop_clears_anthropic_base_url_when_last_session(headroom_dir, monkeypatch, tmp_path):
    """cmd_stop clears ANTHROPIC_BASE_URL when last session exits."""
    import scripts.manager as m
    import json
    from unittest.mock import patch
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"}}))
    monkeypatch.setattr("scripts.manager.CLAUDE_SETTINGS", settings_file)
    m.ensure_dirs()
    m.register_session("99")
    (headroom_dir / "proxy.port").write_text("8787")
    with patch("scripts.manager.kill_proxy"):
        m.cmd_stop("99")
    result = json.loads(settings_file.read_text())
    assert "ANTHROPIC_BASE_URL" not in result.get("env", {})
