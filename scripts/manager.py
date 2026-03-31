#!/usr/bin/env python3
"""Headroom proxy lifecycle manager for Claude Code."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
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

CLAUDE_SETTINGS: Path = Path.home() / ".claude" / "settings.json"

VENV_BIN: Path = Path.home() / ".venv" / "bin"
HEADROOM_BIN: Path = VENV_BIN / "headroom"

PORT_RANGE_START = 8787
PORT_RANGE_END = 8887


def ensure_dirs() -> None:
    """Create ~/.headroom/sessions/ if it doesn't exist."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    """Append a timestamped line to manager.log."""
    ensure_dirs()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a") as f:
        f.write(f"[{timestamp}] {msg}\n")


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


def ensure_mcp_installed() -> None:
    """Run 'headroom mcp install' once. Non-fatal if it fails."""
    ensure_dirs()
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


if __name__ == "__main__":
    main()
