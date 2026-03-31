# Headroom Claude Code Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code marketplace plugin that auto-starts the Headroom proxy on session start, routes all Claude API traffic through it, and tears it down when the last session exits.

**Architecture:** A Python `manager.py` script handles all lifecycle logic via `start`/`stop` subcommands. Two Claude Code hooks (`SessionStart`, `Stop`) invoke it. Runtime state lives in `~/.headroom/` (session PID files, port file, MCP sentinel, log). A `dev-install.sh` script symlinks the repo into the plugin cache for local development.

**Tech Stack:** Python 3 stdlib only (no external deps), `urllib.request` for health checks, `subprocess` for proxy launch, `socket` for port probing, `json` for settings.json editing.

---

## File Map

| File | Purpose |
|---|---|
| `.claude-plugin/plugin.json` | Marketplace metadata |
| `hooks/hooks.json` | Hook declarations for SessionStart + Stop |
| `scripts/manager.py` | All lifecycle logic: port finding, proxy management, session tracking, settings update |
| `tests/test_manager.py` | Unit tests for all manager functions |
| `dev-install.sh` | Local dev installer (symlink + settings.json registration) |
| `README.md` | Installation and usage docs |

---

## Task 0: Plugin Scaffold

**Goal:** Create all static config files and directory structure so the plugin is recognized by Claude Code.

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `hooks/hooks.json`
- Create: `scripts/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)
- Create: `README.md`

**Acceptance Criteria:**
- [ ] `.claude-plugin/plugin.json` has all required marketplace fields
- [ ] `hooks/hooks.json` declares `SessionStart` and `Stop` hooks with correct commands and timeouts
- [ ] `README.md` covers marketplace install, local dev install, and requirements

**Verify:** `python3 -c "import json; json.load(open('.claude-plugin/plugin.json')); json.load(open('hooks/hooks.json')); print('OK')"` → `OK`

**Steps:**

- [ ] **Step 1: Create `.claude-plugin/plugin.json`**

```json
{
  "name": "headroom",
  "displayName": "Headroom",
  "version": "1.0.0",
  "description": "Auto-starts the Headroom context optimization proxy and routes Claude API traffic through it.",
  "author": {
    "name": "TODO: your name",
    "url": "https://github.com/TODO/headroom-claude-plugin"
  },
  "repository": "https://github.com/TODO/headroom-claude-plugin",
  "license": "MIT",
  "keywords": ["headroom", "proxy", "context", "optimization", "anthropic"]
}
```

- [ ] **Step 2: Create `hooks/hooks.json`**

```json
{
  "description": "Headroom proxy lifecycle management",
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/manager.py start $$",
            "timeout": 30
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/manager.py stop $$",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 3: Create `scripts/__init__.py` and `tests/__init__.py`**

Both empty files. Just `touch scripts/__init__.py tests/__init__.py`.

- [ ] **Step 4: Create `README.md`**

```markdown
# Headroom Claude Code Plugin

Automatically starts the [Headroom](https://github.com/headroom-ai/headroom) context optimization proxy when Claude Code launches and routes all API traffic through it.

## Requirements

- macOS or Linux
- `headroom` installed at `~/.venv/bin/headroom`
  - Install: `python3 -m venv ~/.venv && ~/.venv/bin/pip install headroom`

## Marketplace Install

Add to `~/.claude/settings.json`:
```json
{
  "pluginSources": {
    "headroom-plugin": {
      "repo": "TODO/headroom-claude-plugin"
    }
  },
  "enabledPlugins": {
    "headroom@headroom-plugin": true
  }
}
```

## Local Dev Install

```bash
bash dev-install.sh
```

## How It Works

1. On session start: sources venv, runs `headroom mcp install` once, starts proxy (or reuses if running), writes session PID file, sets `ANTHROPIC_BASE_URL` in `~/.claude/settings.json`
2. On session stop: removes PID file, kills proxy only if no other sessions remain

## Runtime State

All state in `~/.headroom/`:
- `sessions/<pid>` — one file per active Claude Code session
- `proxy.port` — port the running proxy is bound to
- `.mcp_installed` — sentinel for one-time MCP registration
- `manager.log` — timestamped log for debugging
```

- [ ] **Step 5: Verify JSON validity**

```bash
python3 -c "import json; json.load(open('.claude-plugin/plugin.json')); json.load(open('hooks/hooks.json')); print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add .claude-plugin/ hooks/ scripts/__init__.py tests/__init__.py README.md
git commit -m "chore: plugin scaffold — metadata, hooks, readme"
```

---

## Task 1: manager.py Foundation — Arg Parsing, State Dir, Logging

**Goal:** `manager.py` parses `start <pid>` / `stop <pid>` args, creates `~/.headroom/` directory structure, and exposes a `log(msg)` helper that timestamps entries to `~/.headroom/manager.log`.

**Files:**
- Create: `scripts/manager.py`
- Create: `tests/test_manager.py`

**Acceptance Criteria:**
- [ ] `manager.py start 12345` and `manager.py stop 12345` parse without error
- [ ] `~/.headroom/sessions/` directory is created on first run if missing
- [ ] `log()` writes `[YYYY-MM-DD HH:MM:SS] message\n` to `~/.headroom/manager.log`
- [ ] Missing or invalid args exit with code 1 and print usage to stderr

**Verify:** `python3 scripts/manager.py start 99999 2>&1; echo "exit:$?"` → no traceback, `exit:0`; `python3 -m pytest tests/test_manager.py::test_log -v` → PASS

**Steps:**

- [ ] **Step 1: Write failing tests**

```python
# tests/test_manager.py
import os
import sys
import tempfile
import importlib
from pathlib import Path
from unittest.mock import patch

# We'll monkeypatch HEADROOM_DIR so tests don't touch ~/.headroom
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
```

Run: `python3 -m pytest tests/test_manager.py -v`
Expected: FAIL (ImportError — module doesn't exist yet)

- [ ] **Step 2: Write minimal `scripts/manager.py`**

```python
#!/usr/bin/env python3
"""Headroom proxy lifecycle manager for Claude Code."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths — monkeypatched in tests
# ---------------------------------------------------------------------------
HEADROOM_DIR: Path = Path.home() / ".headroom"
SESSIONS_DIR: Path = HEADROOM_DIR / "sessions"
PORT_FILE: Path = HEADROOM_DIR / "proxy.port"
MCP_SENTINEL: Path = HEADROOM_DIR / ".mcp_installed"
LOG_FILE: Path = HEADROOM_DIR / "manager.log"

VENV_BIN: Path = Path.home() / ".venv" / "bin"
HEADROOM_BIN: Path = VENV_BIN / "headroom"


def ensure_dirs() -> None:
    """Create ~/.headroom/sessions/ if it doesn't exist."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    """Append a timestamped line to manager.log."""
    ensure_dirs()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a") as f:
        f.write(f"[{timestamp}] {msg}\n")


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: manager.py <start|stop> <pid>", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    pid = sys.argv[2]

    if command == "start":
        cmd_start(pid)
    elif command == "stop":
        cmd_stop(pid)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


def cmd_start(pid: str) -> None:
    ensure_dirs()
    log(f"start called for pid={pid}")


def cmd_stop(pid: str) -> None:
    ensure_dirs()
    log(f"stop called for pid={pid}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_manager.py -v
```

Expected: all 4 tests PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/manager.py tests/test_manager.py
git commit -m "feat: manager.py foundation — arg parsing, state dirs, logging"
```

---

## Task 2: Port Finder + Proxy Health Check

**Goal:** Implement `find_free_port()` (probes 8787–8887 via socket) and `check_proxy_health(port)` (GET /health, returns bool).

**Files:**
- Modify: `scripts/manager.py`
- Modify: `tests/test_manager.py`

**Acceptance Criteria:**
- [ ] `find_free_port()` returns the first port in 8787–8887 not accepting connections
- [ ] `find_free_port()` raises `RuntimeError` if all 100 ports are occupied
- [ ] `check_proxy_health(port)` returns `True` when `/health` responds with `{"status": "healthy", ...}`
- [ ] `check_proxy_health(port)` returns `False` on connection error or non-healthy status

**Verify:** `python3 -m pytest tests/test_manager.py::test_find_free_port_returns_8787 tests/test_manager.py::test_check_proxy_health_true -v` → PASS

**Steps:**

- [ ] **Step 1: Write failing tests**

Add to `tests/test_manager.py`:

```python
import socket
import urllib.error
from unittest.mock import patch, MagicMock

def test_find_free_port_returns_8787(headroom_dir, monkeypatch):
    """When 8787 is free (connect fails), return 8787."""
    import scripts.manager as m
    def mock_connect(address):
        return 1  # non-zero = connection refused = port is free
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
    call_count = [0]
    def mock_connect_ex(address):
        call_count[0] += 1
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
    import json
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
    import json
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"status": "degraded"}).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_response):
        assert m.check_proxy_health(8787) is False
```

Run: `python3 -m pytest tests/test_manager.py -k "port or health" -v`
Expected: FAIL (AttributeError — functions don't exist)

- [ ] **Step 2: Implement `find_free_port` and `check_proxy_health` in `scripts/manager.py`**

Add after the `log()` function:

```python
import json
import socket
import urllib.request


PORT_RANGE_START = 8787
PORT_RANGE_END = 8887


def find_free_port() -> int:
    """Probe ports 8787-8887; return first that is not accepting connections."""
    for port in range(PORT_RANGE_START, PORT_RANGE_END + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.1)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"No free port found in range {PORT_RANGE_START}-{PORT_RANGE_END}")


def check_proxy_health(port: int) -> bool:
    """Return True if the proxy at the given port reports healthy."""
    try:
        url = f"http://127.0.0.1:{port}/health"
        with urllib.request.urlopen(url, timeout=2) as resp:
            data = json.loads(resp.read())
            return data.get("status") == "healthy"
    except Exception:
        return False
```

- [ ] **Step 3: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_manager.py -k "port or health" -v
```

Expected: all 6 tests PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/manager.py tests/test_manager.py
git commit -m "feat: add find_free_port and check_proxy_health"
```

---

## Task 3: Proxy Start + Health Poll

**Goal:** Implement `start_proxy(port)` (launches detached subprocess) and `wait_for_proxy(port)` (polls /health up to 10s). Returns the port on success, raises on timeout.

**Files:**
- Modify: `scripts/manager.py`
- Modify: `tests/test_manager.py`

**Acceptance Criteria:**
- [ ] `start_proxy(port)` launches `headroom proxy --port <port>` with `start_new_session=True`
- [ ] `start_proxy(port)` prepends `~/.venv/bin` to `PATH` in subprocess env
- [ ] `wait_for_proxy(port)` returns `True` once `/health` responds healthy within 10s
- [ ] `wait_for_proxy(port)` raises `TimeoutError` after 10s with no healthy response
- [ ] `HEADROOM_BIN` not found → raises `FileNotFoundError`

**Verify:** `python3 -m pytest tests/test_manager.py::test_start_proxy_launches_detached tests/test_manager.py::test_wait_for_proxy_success -v` → PASS

**Steps:**

- [ ] **Step 1: Write failing tests**

Add to `tests/test_manager.py`:

```python
import subprocess
import time

def test_start_proxy_raises_if_headroom_missing(headroom_dir, monkeypatch):
    """Raises FileNotFoundError when ~/.venv/bin/headroom doesn't exist."""
    import scripts.manager as m
    monkeypatch.setattr("scripts.manager.HEADROOM_BIN", Path("/nonexistent/headroom"))
    with pytest.raises(FileNotFoundError, match="headroom not found"):
        m.start_proxy(8787)

def test_start_proxy_launches_detached(headroom_dir, monkeypatch, tmp_path):
    """Calls subprocess.Popen with correct args and start_new_session=True."""
    import scripts.manager as m
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
    with patch("scripts.manager.check_proxy_health", return_value=True):
        assert m.wait_for_proxy(8787) is True

def test_wait_for_proxy_raises_on_timeout(headroom_dir, monkeypatch):
    """Raises TimeoutError when health check never passes within timeout."""
    import scripts.manager as m
    with patch("scripts.manager.check_proxy_health", return_value=False):
        with patch("time.sleep"):  # skip actual sleeping
            with pytest.raises(TimeoutError, match="did not become healthy"):
                m.wait_for_proxy(8787, timeout=0.1)
```

Run: `python3 -m pytest tests/test_manager.py -k "proxy" -v`
Expected: FAIL

- [ ] **Step 2: Implement `start_proxy` and `wait_for_proxy`**

Add to `scripts/manager.py` (after `check_proxy_health`):

```python
import subprocess
import time


def start_proxy(port: int) -> None:
    """Launch headroom proxy as a detached background process."""
    if not HEADROOM_BIN.exists():
        raise FileNotFoundError(f"headroom not found at {HEADROOM_BIN}")

    env = os.environ.copy()
    env["PATH"] = str(VENV_BIN) + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = str(VENV_BIN.parent)

    subprocess.Popen(
        [str(HEADROOM_BIN), "proxy", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def wait_for_proxy(port: int, timeout: float = 10.0, interval: float = 0.5) -> bool:
    """Poll /health until healthy or timeout. Raises TimeoutError on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check_proxy_health(port):
            return True
        time.sleep(interval)
    raise TimeoutError(f"Headroom proxy on port {port} did not become healthy within {timeout}s")
```

- [ ] **Step 3: Run tests**

```bash
python3 -m pytest tests/test_manager.py -k "proxy" -v
```

Expected: all 4 proxy tests PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/manager.py tests/test_manager.py
git commit -m "feat: add start_proxy and wait_for_proxy"
```

---

## Task 4: Session Tracking

**Goal:** Implement `register_session(pid)`, `remove_session(pid)`, `cleanup_stale_sessions()`, and `count_sessions()`.

**Files:**
- Modify: `scripts/manager.py`
- Modify: `tests/test_manager.py`

**Acceptance Criteria:**
- [ ] `register_session(pid)` creates `~/.headroom/sessions/<pid>` as an empty file
- [ ] `remove_session(pid)` deletes it (no error if already missing)
- [ ] `cleanup_stale_sessions()` removes files whose PID is not a running process
- [ ] `count_sessions()` returns the number of remaining files in `sessions/`

**Verify:** `python3 -m pytest tests/test_manager.py -k "session" -v` → PASS

**Steps:**

- [ ] **Step 1: Write failing tests**

Add to `tests/test_manager.py`:

```python
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
    m.ensure_dirs()
    # Use current process PID — definitely alive
    my_pid = str(os.getpid())
    m.register_session(my_pid)
    m.cleanup_stale_sessions()
    assert (headroom_dir / "sessions" / my_pid).exists()
    m.remove_session(my_pid)  # cleanup
```

Run: `python3 -m pytest tests/test_manager.py -k "session" -v`
Expected: FAIL

- [ ] **Step 2: Implement session functions**

Add to `scripts/manager.py`:

```python
import signal


def register_session(pid: str) -> None:
    """Create an empty sentinel file for this session PID."""
    (SESSIONS_DIR / pid).touch()


def remove_session(pid: str) -> None:
    """Remove this session's sentinel file. No-op if already gone."""
    try:
        (SESSIONS_DIR / pid).unlink()
    except FileNotFoundError:
        pass


def cleanup_stale_sessions() -> None:
    """Remove session files whose PID is no longer a running process."""
    for f in SESSIONS_DIR.iterdir():
        try:
            pid = int(f.name)
            os.kill(pid, 0)  # 0 = check existence only, raises if dead
        except (ValueError, ProcessLookupError, PermissionError):
            f.unlink(missing_ok=True)


def count_sessions() -> int:
    """Return number of active session files."""
    return sum(1 for _ in SESSIONS_DIR.iterdir())
```

- [ ] **Step 3: Run tests**

```bash
python3 -m pytest tests/test_manager.py -k "session" -v
```

Expected: all 6 session tests PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/manager.py tests/test_manager.py
git commit -m "feat: add session tracking — register, remove, cleanup, count"
```

---

## Task 5: settings.json Updater

**Goal:** Implement `update_anthropic_base_url(port)` — atomically reads `~/.claude/settings.json`, sets `env.ANTHROPIC_BASE_URL`, and writes it back via temp file + `os.replace()`.

**Files:**
- Modify: `scripts/manager.py`
- Modify: `tests/test_manager.py`

**Acceptance Criteria:**
- [ ] Sets `env.ANTHROPIC_BASE_URL` to `http://127.0.0.1:<port>`
- [ ] Creates `env` dict if it doesn't exist in settings
- [ ] Preserves all other settings.json content
- [ ] Uses atomic write (temp file + `os.replace`)
- [ ] Raises `FileNotFoundError` if `~/.claude/settings.json` doesn't exist

**Verify:** `python3 -m pytest tests/test_manager.py -k "settings" -v` → PASS

**Steps:**

- [ ] **Step 1: Write failing tests**

Add to `tests/test_manager.py`:

```python
def test_update_anthropic_base_url_sets_env(tmp_path, monkeypatch):
    import scripts.manager as m
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"other": "value"}))
    monkeypatch.setattr("scripts.manager.CLAUDE_SETTINGS", settings_file)
    m.update_anthropic_base_url(8787)
    result = json.loads(settings_file.read_text())
    assert result["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8787"
    assert result["other"] == "value"  # preserved

def test_update_anthropic_base_url_creates_env_block(tmp_path, monkeypatch):
    import scripts.manager as m
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}")
    monkeypatch.setattr("scripts.manager.CLAUDE_SETTINGS", settings_file)
    m.update_anthropic_base_url(9000)
    result = json.loads(settings_file.read_text())
    assert result["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:9000"

def test_update_anthropic_base_url_overwrites_existing(tmp_path, monkeypatch):
    import scripts.manager as m
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"}}))
    monkeypatch.setattr("scripts.manager.CLAUDE_SETTINGS", settings_file)
    m.update_anthropic_base_url(8788)
    result = json.loads(settings_file.read_text())
    assert result["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8788"

def test_update_anthropic_base_url_raises_if_no_settings(tmp_path, monkeypatch):
    import scripts.manager as m
    monkeypatch.setattr("scripts.manager.CLAUDE_SETTINGS", tmp_path / "nonexistent.json")
    with pytest.raises(FileNotFoundError):
        m.update_anthropic_base_url(8787)
```

Run: `python3 -m pytest tests/test_manager.py -k "settings" -v`
Expected: FAIL

- [ ] **Step 2: Implement `update_anthropic_base_url`**

Add to `scripts/manager.py` (add `CLAUDE_SETTINGS` constant near the top with other paths, and the function body):

```python
# Add near other path constants:
CLAUDE_SETTINGS: Path = Path.home() / ".claude" / "settings.json"
```

```python
def update_anthropic_base_url(port: int) -> None:
    """Atomically set env.ANTHROPIC_BASE_URL in ~/.claude/settings.json."""
    if not CLAUDE_SETTINGS.exists():
        raise FileNotFoundError(f"Claude settings not found at {CLAUDE_SETTINGS}")

    settings = json.loads(CLAUDE_SETTINGS.read_text())
    settings.setdefault("env", {})
    settings["env"]["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"

    tmp = CLAUDE_SETTINGS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(settings, indent=2))
    os.replace(tmp, CLAUDE_SETTINGS)
```

- [ ] **Step 3: Run tests**

```bash
python3 -m pytest tests/test_manager.py -k "settings" -v
```

Expected: all 4 settings tests PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/manager.py tests/test_manager.py
git commit -m "feat: add update_anthropic_base_url with atomic write"
```

---

## Task 6: MCP One-Time Installer

**Goal:** Implement `ensure_mcp_installed()` — checks sentinel, runs `headroom mcp install`, creates sentinel. Non-fatal on failure.

**Files:**
- Modify: `scripts/manager.py`
- Modify: `tests/test_manager.py`

**Acceptance Criteria:**
- [ ] Does nothing if `~/.headroom/.mcp_installed` exists
- [ ] Runs `headroom mcp install` if sentinel is absent
- [ ] Creates sentinel on successful install
- [ ] Does NOT raise if `headroom mcp install` fails — logs warning and returns

**Verify:** `python3 -m pytest tests/test_manager.py -k "mcp" -v` → PASS

**Steps:**

- [ ] **Step 1: Write failing tests**

Add to `tests/test_manager.py`:

```python
def test_ensure_mcp_skips_if_sentinel_exists(headroom_dir, monkeypatch):
    import scripts.manager as m
    m.ensure_dirs()
    MCP_SENTINEL = headroom_dir / ".mcp_installed"
    MCP_SENTINEL.touch()
    monkeypatch.setattr("scripts.manager.MCP_SENTINEL", MCP_SENTINEL)
    with patch("subprocess.run") as mock_run:
        m.ensure_mcp_installed()
        mock_run.assert_not_called()

def test_ensure_mcp_runs_install_when_absent(headroom_dir, monkeypatch, tmp_path):
    import scripts.manager as m
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
    fake_bin = tmp_path / "headroom"
    fake_bin.touch()
    sentinel = headroom_dir / ".mcp_installed"
    monkeypatch.setattr("scripts.manager.HEADROOM_BIN", fake_bin)
    monkeypatch.setattr("scripts.manager.MCP_SENTINEL", sentinel)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        m.ensure_mcp_installed()  # must not raise
        assert not sentinel.exists()
```

Run: `python3 -m pytest tests/test_manager.py -k "mcp" -v`
Expected: FAIL

- [ ] **Step 2: Implement `ensure_mcp_installed`**

Add to `scripts/manager.py`:

```python
def ensure_mcp_installed() -> None:
    """Run 'headroom mcp install' once. Non-fatal if it fails."""
    if MCP_SENTINEL.exists():
        return

    env = os.environ.copy()
    env["PATH"] = str(VENV_BIN) + os.pathsep + env.get("PATH", "")

    try:
        result = subprocess.run(
            [str(HEADROOM_BIN), "mcp", "install"],
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            MCP_SENTINEL.touch()
            log("headroom mcp install succeeded")
        else:
            log(f"WARNING: headroom mcp install failed (rc={result.returncode}): {result.stderr.strip()}")
    except Exception as e:
        log(f"WARNING: headroom mcp install raised exception: {e}")
```

- [ ] **Step 3: Run tests**

```bash
python3 -m pytest tests/test_manager.py -k "mcp" -v
```

Expected: all 4 MCP tests PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/manager.py tests/test_manager.py
git commit -m "feat: add ensure_mcp_installed with sentinel"
```

---

## Task 7: Wire cmd_start and cmd_stop End-to-End

**Goal:** Fill in `cmd_start(pid)` and `cmd_stop(pid)` to call all the functions in the right order. Integration tests validate the full flow with mocks.

**Files:**
- Modify: `scripts/manager.py`
- Modify: `tests/test_manager.py`

**Acceptance Criteria:**
- [ ] `cmd_start`: runs MCP install → checks proxy health → starts if needed → writes session → writes port file → updates settings
- [ ] `cmd_stop`: cleans stale sessions → removes own session → kills proxy + deletes port file if no sessions remain
- [ ] `cmd_start` with proxy already healthy skips launch and reuses port
- [ ] `cmd_stop` with remaining sessions leaves proxy running
- [ ] On proxy kill: reads `proxy.port`, kills via `lsof -ti :<port>`, deletes `proxy.port`

**Verify:** `python3 -m pytest tests/test_manager.py -k "cmd_" -v` → PASS

**Steps:**

- [ ] **Step 1: Write integration tests**

Add to `tests/test_manager.py`:

```python
def test_cmd_start_full_flow_new_proxy(headroom_dir, monkeypatch, tmp_path):
    """cmd_start launches proxy, registers session, updates settings when no proxy running."""
    import scripts.manager as m
    fake_bin = tmp_path / "headroom"
    fake_bin.touch()
    sentinel = headroom_dir / ".mcp_installed"
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}")
    monkeypatch.setattr("scripts.manager.HEADROOM_BIN", fake_bin)
    monkeypatch.setattr("scripts.manager.MCP_SENTINEL", sentinel)
    monkeypatch.setattr("scripts.manager.CLAUDE_SETTINGS", settings_file)
    with patch("scripts.manager.check_proxy_health", return_value=False) as mock_health, \
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

def test_cmd_stop_kills_proxy_when_last_session(headroom_dir, monkeypatch):
    """cmd_stop kills proxy and removes port file when no sessions remain."""
    import scripts.manager as m
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
    m.ensure_dirs()
    m.register_session(str(os.getpid()))  # live session
    m.register_session("88")
    (headroom_dir / "proxy.port").write_text("8787")
    with patch("scripts.manager.kill_proxy") as mock_kill:
        m.cmd_stop("88")
    mock_kill.assert_not_called()
    m.remove_session(str(os.getpid()))  # cleanup
```

Run: `python3 -m pytest tests/test_manager.py -k "cmd_" -v`
Expected: FAIL

- [ ] **Step 2: Implement `kill_proxy`, `cmd_start`, `cmd_stop`**

Add `kill_proxy` to `scripts/manager.py`:

```python
def kill_proxy(port: int) -> None:
    """Find and SIGTERM the process listening on the given port."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True,
        )
        pid_str = result.stdout.strip()
        if pid_str:
            for pid in pid_str.splitlines():
                try:
                    os.kill(int(pid), signal.SIGTERM)
                    log(f"Sent SIGTERM to proxy PID {pid} on port {port}")
                except ProcessLookupError:
                    pass
    except Exception as e:
        log(f"WARNING: failed to kill proxy on port {port}: {e}")
```

Replace the stub `cmd_start` and `cmd_stop`:

```python
def cmd_start(pid: str) -> None:
    ensure_dirs()
    log(f"start called for pid={pid}")

    # 1. One-time MCP install
    ensure_mcp_installed()

    # 2. Check if proxy is already running
    port: int | None = None
    if PORT_FILE.exists():
        try:
            port = int(PORT_FILE.read_text().strip())
        except ValueError:
            port = None

    if port and check_proxy_health(port):
        log(f"Proxy already healthy on port {port}, reusing")
    else:
        # 3. Find free port and start proxy
        port = find_free_port()
        start_proxy(port)
        wait_for_proxy(port)
        PORT_FILE.write_text(str(port))
        log(f"Proxy started on port {port}")

    # 4. Register this session
    register_session(pid)

    # 5. Update ANTHROPIC_BASE_URL in settings.json
    update_anthropic_base_url(port)
    log(f"ANTHROPIC_BASE_URL set to http://127.0.0.1:{port}")


def cmd_stop(pid: str) -> None:
    ensure_dirs()
    log(f"stop called for pid={pid}")

    # 1. Clean stale sessions
    cleanup_stale_sessions()

    # 2. Remove own session
    remove_session(pid)

    # 3. Kill proxy only if no sessions remain
    if count_sessions() == 0:
        if PORT_FILE.exists():
            try:
                port = int(PORT_FILE.read_text().strip())
                kill_proxy(port)
            except (ValueError, Exception) as e:
                log(f"WARNING: error reading port file: {e}")
            finally:
                PORT_FILE.unlink(missing_ok=True)
        log("No sessions remaining, proxy shut down")
    else:
        log(f"{count_sessions()} session(s) still active, proxy kept running")
```

- [ ] **Step 3: Run all tests**

```bash
python3 -m pytest tests/test_manager.py -v
```

Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/manager.py tests/test_manager.py
git commit -m "feat: wire cmd_start and cmd_stop end-to-end"
```

---

## Task 8: dev-install.sh

**Goal:** Write `dev-install.sh` to symlink the repo into the plugin cache and register it in `~/.claude/settings.json`.

**Files:**
- Create: `dev-install.sh`

**Acceptance Criteria:**
- [ ] Creates `~/.claude/plugins/cache/local/headroom/1.0.0/` as a symlink to the repo root
- [ ] Adds `"headroom@local": true` to `enabledPlugins` in `~/.claude/settings.json`
- [ ] Is idempotent — safe to run multiple times
- [ ] Prints a success message at the end

**Verify:** `bash dev-install.sh && ls -la ~/.claude/plugins/cache/local/headroom/1.0.0` → symlink to repo

**Steps:**

- [ ] **Step 1: Create `dev-install.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CACHE_DIR="$HOME/.claude/plugins/cache/local/headroom/1.0.0"
SETTINGS="$HOME/.claude/settings.json"

echo "Installing headroom plugin (dev mode)..."

# 1. Create symlink into plugin cache
mkdir -p "$(dirname "$CACHE_DIR")"
if [ -L "$CACHE_DIR" ]; then
  rm "$CACHE_DIR"
fi
ln -s "$REPO_DIR" "$CACHE_DIR"
echo "  ✓ Symlinked $REPO_DIR → $CACHE_DIR"

# 2. Register in enabledPlugins using Python for safe JSON editing
python3 - <<'PYEOF'
import json, os, sys
from pathlib import Path

settings_path = Path.home() / ".claude" / "settings.json"
if not settings_path.exists():
    print(f"  ERROR: {settings_path} not found. Start Claude Code at least once first.", file=sys.stderr)
    sys.exit(1)

settings = json.loads(settings_path.read_text())
settings.setdefault("enabledPlugins", {})
settings["enabledPlugins"]["headroom@local"] = True

tmp = settings_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(settings, indent=2))
os.replace(tmp, settings_path)
print("  ✓ Registered headroom@local in enabledPlugins")
PYEOF

echo ""
echo "Done! Restart Claude Code to activate the headroom plugin."
echo "Verify: ls -la $CACHE_DIR"
```

- [ ] **Step 2: Make executable and run**

```bash
chmod +x dev-install.sh
bash dev-install.sh
```

Expected output:
```
Installing headroom plugin (dev mode)...
  ✓ Symlinked /Users/<you>/Code/projects/headroom-claude-plugin → ~/.claude/plugins/cache/local/headroom/1.0.0
  ✓ Registered headroom@local in enabledPlugins

Done! Restart Claude Code to activate the headroom plugin.
```

- [ ] **Step 3: Verify symlink and settings**

```bash
ls -la ~/.claude/plugins/cache/local/headroom/1.0.0
python3 -c "import json; s=json.load(open('$HOME/.claude/settings.json')); print(s['enabledPlugins'].get('headroom@local'))"
```

Expected: symlink shown, `True` printed.

- [ ] **Step 4: Commit**

```bash
git add dev-install.sh
git commit -m "feat: add dev-install.sh for local plugin registration"
```

---

## Task 9: Full Integration Smoke Test

**Goal:** Manually verify the plugin works end-to-end: session start activates the proxy and sets `ANTHROPIC_BASE_URL`; session stop (with no other sessions) kills it.

**Files:** No code changes — this is a manual verification task.

**Acceptance Criteria:**
- [ ] After running `manager.py start $$`, proxy responds healthy at the logged port
- [ ] `~/.claude/settings.json` has `env.ANTHROPIC_BASE_URL` set
- [ ] After running `manager.py stop $$`, proxy is no longer responding
- [ ] `~/.headroom/manager.log` contains timestamped entries for both operations
- [ ] `~/.headroom/.mcp_installed` sentinel exists after first start

**Verify:** See steps below.

**Steps:**

- [ ] **Step 1: Run full test suite one final time**

```bash
python3 -m pytest tests/ -v --tb=short
```

Expected: all tests PASS

- [ ] **Step 2: Smoke test start**

```bash
python3 scripts/manager.py start $$
curl -s http://127.0.0.1:$(cat ~/.headroom/proxy.port)/health | python3 -m json.tool
python3 -c "import json; s=json.load(open('$HOME/.claude/settings.json')); print(s['env']['ANTHROPIC_BASE_URL'])"
cat ~/.headroom/manager.log | tail -10
```

Expected: `/health` returns `{"status": "healthy", ...}`, `ANTHROPIC_BASE_URL` is set, log has entries.

- [ ] **Step 3: Smoke test stop**

```bash
python3 scripts/manager.py stop $$
curl -s http://127.0.0.1:8787/health 2>&1 || echo "proxy gone"
cat ~/.headroom/manager.log | tail -5
```

Expected: `proxy gone` (connection refused), log shows shutdown.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: all tasks complete — headroom plugin v1.0.0"
```
