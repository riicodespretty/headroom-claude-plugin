# Headroom Plugin — Design Flow

**Date:** 2026-04-02
**Status:** Reference

---

## Components

| Component | Location | Role |
|-----------|----------|------|
| `hooks/hooks.json` | plugin root | Wires Claude Code lifecycle events to manager |
| `scripts/manager.py` | plugin root | Proxy lifecycle controller |
| `~/.headroom/` | runtime dir | Shared state: port, sessions, log, MCP sentinel |
| `~/.claude/settings.json` | Claude config | Receives `ANTHROPIC_BASE_URL` env injection |
| `headroom` binary | `~/.venv/bin/` | The actual proxy process (pre-installed by user) |

---

## SessionStart Flow

```
Claude Code process starts (PID=N)
│
└─► SessionStart hook fires
    └─► manager.py start N
        │
        ├─1─ ensure_dirs()
        │    └─► mkdir -p ~/.headroom/sessions/
        │
        ├─2─ ensure_mcp_installed()
        │    ├─ ~/.headroom/.mcp_installed exists?
        │    │   └─ YES → skip
        │    └─ NO → run: headroom mcp install
        │            ├─ rc=0 → touch .mcp_installed, log success
        │            └─ rc≠0 → log WARNING, continue (non-fatal)
        │
        ├─3─ Check proxy health
        │    ├─ ~/.headroom/proxy.port exists?
        │    │   ├─ NO → go to step 4
        │    │   └─ YES → read port, GET /health
        │    │           ├─ status=healthy → log "reusing", skip to step 5
        │    │           └─ unhealthy/error → kill_proxy(port)
        │    │                               + unlink proxy.port → go to step 4
        │    └─ (ValueError on port file) → go to step 4
        │
        ├─4─ Start proxy
        │    ├─ find_free_port() — probe 8787..8887 via TCP connect
        │    │   └─ all occupied → raise RuntimeError, exit non-zero
        │    ├─ start_proxy(port) — Popen detached, stdout/stderr /dev/null
        │    ├─ wait_for_proxy(port) — poll /health every 0.5s, 10s timeout
        │    │   └─ timeout → raise TimeoutError, exit non-zero
        │    └─ write port to ~/.headroom/proxy.port
        │
        ├─5─ register_session(N)
        │    └─ touch ~/.headroom/sessions/N
        │
        └─6─ update_anthropic_base_url(port)
             └─ atomic write to ~/.claude/settings.json
                settings["env"]["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:<port>"
```

---

## Stop Flow

```
Claude Code process exits (PID=N)
│
└─► Stop hook fires
    └─► manager.py stop N
        │
        ├─1─ cleanup_stale_sessions()
        │    └─ for each file in ~/.headroom/sessions/:
        │        ├─ os.kill(pid, 0) succeeds → alive, keep
        │        └─ ProcessLookupError / ValueError → dead, unlink
        │
        ├─2─ remove_session(N)
        │    └─ unlink ~/.headroom/sessions/N (no-op if missing)
        │
        └─3─ count_sessions() == 0?
             │
             ├─ YES (last session) ──────────────────────────────┐
             │                                                    │
             │   ├─ read ~/.headroom/proxy.port                  │
             │   ├─ kill_proxy(port)                             │
             │   │   └─ lsof -ti :<port> → SIGTERM each PID     │
             │   ├─ unlink proxy.port (finally block)            │
             │   └─ update_anthropic_base_url(None)              │
             │       └─ del settings["env"]["ANTHROPIC_BASE_URL"]│
             │           + atomic write to settings.json         │
             │                                                    │
             └─ NO (other sessions active) → log, exit ──────────┘
```

---

## State Machine: Proxy

```
ABSENT ──[start, no healthy port]──► STARTING
STARTING ──[/health ok]──► RUNNING
STARTING ──[timeout 10s]──► ABSENT (error logged, exit non-zero)
RUNNING ──[start, healthy port found]──► RUNNING (reuse, no-op)
RUNNING ──[last session stops]──► STOPPING
STOPPING ──[SIGTERM sent]──► ABSENT
```

---

## State Machine: Session

```
(none) ──[cmd_start(N)]──► REGISTERED  (~/.headroom/sessions/N exists)
REGISTERED ──[cmd_stop(N)]──► REMOVED
REGISTERED ──[process crash]──► STALE (cleaned at next start or stop)
STALE ──[cleanup_stale_sessions()]──► REMOVED
```

---

## Shared State Files

| File | Written by | Read by | Deleted by |
|------|-----------|---------|-----------|
| `~/.headroom/proxy.port` | `cmd_start` | `cmd_start`, `cmd_stop` | `cmd_stop` (last session) |
| `~/.headroom/sessions/<pid>` | `cmd_start` | `count_sessions`, `cleanup` | `cmd_stop`, `cleanup` |
| `~/.headroom/.mcp_installed` | `ensure_mcp_installed` | `ensure_mcp_installed` | `dev-uninstall.sh` |
| `~/.headroom/manager.log` | `log()` | humans | never (append-only) |
| `~/.claude/settings.json` | `update_anthropic_base_url` | Claude Code | `update_anthropic_base_url(None)` |

---

## Error Handling Summary

| Scenario | Behavior |
|----------|----------|
| `headroom` binary missing | `FileNotFoundError` → exit non-zero, logged |
| `headroom mcp install` fails | Warning logged, continues (non-fatal) |
| Proxy unhealthy on start | Restart on new port |
| All ports 8787–8887 occupied | `RuntimeError` → exit non-zero |
| Proxy startup timeout (10s) | `TimeoutError` → exit non-zero |
| `settings.json` missing on start | `FileNotFoundError` → exit non-zero |
| `settings.json` missing on stop | Exception caught, warning logged (non-fatal) |
| PID file is stale (crashed session) | Cleaned at next `start` or `stop` |
| Port file contains non-integer | Treated as absent, new proxy started |
| `kill_proxy` fails (lsof/SIGTERM) | Warning logged, port file still deleted |
