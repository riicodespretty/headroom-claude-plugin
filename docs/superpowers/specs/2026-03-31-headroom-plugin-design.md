# Headroom Claude Code Plugin — Design

**Date:** 2026-03-31
**Status:** Approved

## Overview

A Claude Code marketplace plugin that automatically starts and manages the [Headroom](https://github.com/headroom-ai/headroom) optimization proxy on session start, sets `ANTHROPIC_BASE_URL` so all Claude API traffic routes through it, and tears it down gracefully when the last session exits.

## Plugin Structure

```
~/Code/projects/headroom-claude-plugin/
├── .claude-plugin/
│   └── plugin.json          # marketplace metadata
├── hooks/
│   └── hooks.json           # SessionStart + Stop hook declarations
├── scripts/
│   └── manager.py           # Python lifecycle manager
├── README.md
└── dev-install.sh           # local dev only: symlinks into cache + registers source
```

Runtime state directory `~/.headroom/`:
```
~/.headroom/
├── sessions/
│   └── <claude-pid>         # one empty file per active Claude Code session
├── proxy.port               # port number the running proxy is bound to
├── .mcp_installed           # sentinel: headroom mcp install has been run
└── manager.log              # error/info log for debugging
```

## Installation

### Marketplace (primary)
1. Add the plugin's GitHub repo as a source in `~/.claude/settings.json` `pluginSources`
2. Claude Code caches it under `~/.claude/plugins/cache/<registry>/headroom/<version>/`
3. Enable via `"headroom@<registry>": true` in `enabledPlugins`

### Local dev
Run `dev-install.sh`, which:
1. Creates `~/.claude/plugins/cache/local/headroom/1.0.0/` as a symlink to `~/Code/projects/headroom-claude-plugin/`
2. Adds `"headroom@local": true` to `enabledPlugins` in `~/.claude/settings.json`

## plugin.json

Full marketplace metadata: `name`, `version`, `description`, `author`, `repository`, `license`, `keywords`. No `mcpServers` entry — the MCP is registered by `headroom mcp install` at runtime, not statically by the plugin.

## hooks/hooks.json

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

The shell PID (`$$`) is passed as `sys.argv[1]` to `manager.py`. This is used as the session identity for the session tracking file.

## manager.py — Subcommands

### `manager.py start`

1. **Venv activation** — prepend `~/.venv/bin` to `PATH` and set `VIRTUAL_ENV` directly in the subprocess environment. Python doesn't need `source`; setting `PATH` is sufficient to find `headroom`.

2. **One-time MCP install** — check for `~/.headroom/.mcp_installed`. If absent:
   - Run `headroom mcp install`
   - On success, create the sentinel file
   - On failure, log to `manager.log` and continue (non-fatal)

3. **Proxy health check** — if `~/.headroom/proxy.port` exists, read the port and `GET http://127.0.0.1:<port>/health`. If response is `{"status": "healthy", ...}`, the proxy is already up — skip to step 5.

4. **Start proxy** — find a free port:
   - Probe ports 8787–8887 via `socket.connect_ex`; take the first that fails to connect (i.e., is free)
   - If all 100 are occupied, log error and exit non-zero
   - Launch `headroom proxy --port <port>` as a detached subprocess (`start_new_session=True`)
   - Poll `GET /health` every 0.5s for up to 10 seconds. If never healthy, log and exit non-zero
   - Write the port to `~/.headroom/proxy.port`

5. **Register session** — create empty file `~/.headroom/sessions/<shell-pid>`

6. **Update settings.json** — atomic JSON update of `env.ANTHROPIC_BASE_URL`:
   - Read `~/.claude/settings.json`
   - Set `env.ANTHROPIC_BASE_URL = "http://127.0.0.1:<port>"`
   - Write to a temp file, then `os.replace()` into place

### `manager.py stop`

1. **Stale session cleanup** — scan `~/.headroom/sessions/`; for each file, parse the PID from the filename and check `os.kill(pid, 0)`. Remove any files whose process is no longer running.

2. **Remove own session** — delete `~/.headroom/sessions/<shell-pid>`

3. **Count remaining sessions** — list `~/.headroom/sessions/`. If any remain, exit (proxy stays up).

4. **Kill proxy** — read port from `~/.headroom/proxy.port`, find the process via `lsof -ti :<port>`, send `SIGTERM`. Delete `~/.headroom/proxy.port`.

## Error Handling

| Scenario | Behavior |
|---|---|
| `~/.venv/bin/headroom` not found | Log error, exit non-zero — surfaces in Claude Code UI |
| Proxy startup timeout (>10s) | Log error, exit non-zero |
| `settings.json` write failure | Log error, exit non-zero |
| `headroom mcp install` failure | Log warning, continue (non-fatal) |
| Stale PID files from crash | Cleaned up at next `start` via `os.kill(pid, 0)` |
| All ports 8787–8887 occupied | Log error, exit non-zero |
| Proxy already healthy on start | Reuse it, skip launch |

All errors logged to `~/.headroom/manager.log` with timestamps.

## Data Flow

```
Claude Code starts
  → SessionStart hook → manager.py start
    → venv PATH set
    → mcp install (once)
    → proxy health check
      → healthy? reuse port
      → not healthy? find free port, launch proxy, poll health
    → write sessions/<pid>
    → update settings.json ANTHROPIC_BASE_URL
  → Claude session runs, all API calls → proxy → Anthropic

Claude Code exits
  → Stop hook → manager.py stop
    → cleanup stale sessions
    → remove sessions/<pid>
    → if sessions/ empty → kill proxy, delete proxy.port
```

## Out of Scope

- Proxy configuration flags (mode, cache, rate-limit) — user can configure headroom separately
- Multiple simultaneous proxies — one proxy per machine, shared across sessions
- Windows support — macOS/Linux only (`lsof`, `os.kill`)
