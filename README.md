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
