#!/usr/bin/env python3
"""Headroom proxy lifecycle manager for Claude Code."""

from __future__ import annotations

import fcntl
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
LOCK_FILE: Path = HEADROOM_DIR / "manager.lock"

CLAUDE_SETTINGS: Path = Path.home() / ".claude" / "settings.json"
CLAUDE_JSON: Path = Path.home() / ".claude.json"

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
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("status") == "healthy"
    except Exception:
        return False


def start_proxy(port: int) -> int:
    """Launch headroom proxy as a detached background process. Returns the PID."""
    if not HEADROOM_BIN.exists():
        raise FileNotFoundError(f"headroom not found at {HEADROOM_BIN}")

    env = os.environ.copy()
    env["PATH"] = str(VENV_BIN) + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = str(VENV_BIN.parent)

    proc = subprocess.Popen(
        [str(HEADROOM_BIN), "proxy", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return proc.pid


def wait_for_proxy(port: int, timeout: float = 30.0, interval: float = 0.5) -> None:
    """Poll /health until healthy or timeout. Raises TimeoutError on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check_proxy_health(port):
            return
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
        except (ValueError, ProcessLookupError):
            f.unlink(missing_ok=True)
        except PermissionError:
            pass  # Process exists but owned by another user — keep the session file


def count_sessions() -> int:
    """Return number of active session files."""
    return sum(1 for _ in SESSIONS_DIR.iterdir())


def update_anthropic_base_url(port: int | None) -> None:
    """Atomically set or clear env.ANTHROPIC_BASE_URL in ~/.claude/settings.json.

    If port is None, clears the ANTHROPIC_BASE_URL variable.
    """
    if not CLAUDE_SETTINGS.exists():
        raise FileNotFoundError(f"Claude settings not found at {CLAUDE_SETTINGS}")

    settings = json.loads(CLAUDE_SETTINGS.read_text())
    settings.setdefault("env", {})

    if port is None:
        # Clear the variable
        if "ANTHROPIC_BASE_URL" in settings["env"]:
            del settings["env"]["ANTHROPIC_BASE_URL"]
    else:
        # Set the variable
        settings["env"]["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"

    tmp = CLAUDE_SETTINGS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(settings, indent=2))
    os.replace(tmp, CLAUDE_SETTINGS)


def _patch_claude_json_headroom_command() -> None:
    """Rewrite mcpServers.headroom.command in ~/.claude.json to the full venv path.

    headroom mcp install writes a bare "headroom" command, but Claude Code spawns
    MCP servers without the venv on PATH, so we must use the absolute binary path.
    Non-fatal: logs a warning and returns if the file is missing or malformed.
    """
    if not CLAUDE_JSON.exists():
        log("WARNING: ~/.claude.json not found, skipping command patch")
        return
    try:
        data = json.loads(CLAUDE_JSON.read_text())
    except (json.JSONDecodeError, OSError) as e:
        log(f"WARNING: could not read ~/.claude.json: {e}")
        return

    mcp_servers = data.get("mcpServers", {})
    headroom_entry = mcp_servers.get("headroom", {})
    current_command = headroom_entry.get("command", "")

    if current_command == str(HEADROOM_BIN):
        return  # Already patched

    headroom_entry["command"] = str(HEADROOM_BIN)
    mcp_servers["headroom"] = headroom_entry
    data["mcpServers"] = mcp_servers

    tmp = CLAUDE_JSON.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, CLAUDE_JSON)
        log(f"Patched ~/.claude.json mcpServers.headroom.command → {HEADROOM_BIN}")
    except OSError as e:
        log(f"WARNING: could not write ~/.claude.json: {e}")
        tmp.unlink(missing_ok=True)


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
            _patch_claude_json_headroom_command()
        else:
            log(f"WARNING: headroom mcp install failed (rc={result.returncode}): {result.stderr.strip()}")
    except Exception as e:
        log(f"WARNING: headroom mcp install raised exception: {e}")


def kill_proxy(port: int, grace_period: float = 3.0) -> None:
    """Find, SIGTERM, and wait for the process listening on the given port."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True,
        )
        pid_str = result.stdout.strip()
        if not pid_str:
            return
        pids = []
        for pid in pid_str.splitlines():
            try:
                os.kill(int(pid), signal.SIGTERM)
                pids.append(int(pid))
                log(f"Sent SIGTERM to proxy PID {pid} on port {port}")
            except ProcessLookupError:
                pass
        # Wait for processes to exit; SIGKILL if still alive after grace period
        deadline = time.monotonic() + grace_period
        for pid in pids:
            while time.monotonic() < deadline:
                try:
                    os.kill(pid, 0)
                    time.sleep(0.1)
                except ProcessLookupError:
                    break
            else:
                # Grace period expired — force-kill
                try:
                    os.kill(pid, signal.SIGKILL)
                    log(f"Sent SIGKILL to proxy PID {pid} (did not exit within {grace_period}s)")
                except ProcessLookupError:
                    pass
    except Exception as e:
        log(f"WARNING: failed to kill proxy on port {port}: {e}")


def cmd_start(pid: str) -> None:
    ensure_dirs()
    log(f"start called for pid={pid}")

    # 1. One-time MCP install
    ensure_mcp_installed()

    # 2. Check if proxy is already running (serialized with flock to prevent
    #    concurrent starts from racing to find_free_port and launching two
    #    proxies on the same port)
    with LOCK_FILE.open("a") as _lock:
        fcntl.flock(_lock, fcntl.LOCK_EX)
        port: int | None = None
        if PORT_FILE.exists():
            try:
                port = int(PORT_FILE.read_text().strip())
            except ValueError:
                port = None

        if port and check_proxy_health(port):
            log(f"Proxy already healthy on port {port}, reusing")
        else:
            # Kill stale proxy and remove port file before starting a fresh one
            if port:
                log(f"Proxy on port {port} is unhealthy, stopping it")
                kill_proxy(port)
                PORT_FILE.unlink(missing_ok=True)
            # 3. Find free port and start proxy
            port = find_free_port()
            proxy_pid = start_proxy(port)
            try:
                wait_for_proxy(port)
            except TimeoutError:
                # Kill by PID directly: the process may not have bound the port
                # yet, so lsof-based kill_proxy() would find nothing.
                try:
                    os.kill(proxy_pid, signal.SIGTERM)
                    log(f"Sent SIGTERM to proxy PID {proxy_pid} after timeout")
                except ProcessLookupError:
                    pass
                # Also attempt port-based kill as belt-and-suspenders
                kill_proxy(port)
                raise
            PORT_FILE.write_text(str(port))
            log(f"Proxy started on port {port}")

        # 4. Register this session
        register_session(pid)

        # 5. Update ANTHROPIC_BASE_URL in settings.json (inside lock to prevent
        #    concurrent processes from racing on the same .json.tmp path)
        try:
            settings = json.loads(CLAUDE_SETTINGS.read_text())
        except (FileNotFoundError, json.JSONDecodeError) as e:
            log(f"WARNING: could not read {CLAUDE_SETTINGS}: {e} — skipping URL update")
            return
        current_url = settings.get("env", {}).get("ANTHROPIC_BASE_URL")
        expected_url = f"http://127.0.0.1:{port}"
        if current_url != expected_url:
            update_anthropic_base_url(port)
            log(f"ANTHROPIC_BASE_URL set to {expected_url}")
        else:
            log(f"ANTHROPIC_BASE_URL already correct ({expected_url}), skipping write")


def cmd_stop(pid: str) -> None:
    ensure_dirs()
    log(f"stop called for pid={pid}")

    # 1. Clean stale sessions
    cleanup_stale_sessions()

    # 2. Remove own session
    remove_session(pid)

    # 3. Kill proxy only if no sessions remain
    remaining = count_sessions()
    if remaining == 0:
        if PORT_FILE.exists():
            try:
                port = int(PORT_FILE.read_text().strip())
                kill_proxy(port)
            except Exception as e:
                log(f"WARNING: error reading port file: {e}")
            finally:
                PORT_FILE.unlink(missing_ok=True)
        # Clear ANTHROPIC_BASE_URL now that proxy is down
        try:
            update_anthropic_base_url(None)
            log("Cleared ANTHROPIC_BASE_URL")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            log(f"WARNING: failed to clear ANTHROPIC_BASE_URL: {e}")
        log("No sessions remaining, proxy shut down")
    else:
        log(f"{remaining} session(s) still active, proxy kept running")


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
