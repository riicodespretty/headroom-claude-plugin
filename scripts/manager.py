#!/usr/bin/env python3
"""Headroom proxy lifecycle manager for Claude Code."""

from __future__ import annotations

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
