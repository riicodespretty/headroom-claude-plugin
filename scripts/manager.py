#!/usr/bin/env python3
"""Headroom proxy lifecycle manager for Claude Code."""

from __future__ import annotations

import json
import os
import signal
import socket
import sys
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


def cmd_start(pid: str) -> None:
    ensure_dirs()
    log(f"start called for pid={pid}")


def cmd_stop(pid: str) -> None:
    ensure_dirs()
    log(f"stop called for pid={pid}")


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
