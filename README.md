# Headroom Claude Code Plugin

Automatically starts the [Headroom](https://github.com/headroom-ai/headroom) context optimization proxy when Claude Code launches and routes all API traffic through it.

## Requirements

- macOS or Linux
- `headroom` installed at `~/.venv/bin/headroom`
  - Install: `python3 -m venv ~/.venv && ~/.venv/bin/pip install headroom`

## Install

```
/plugin marketplace add https://github.com/riicodespretty/headroom-claude-plugin.git
/plugin install headroom@riicodespretty
```

## Local Dev Install

```bash
bash dev-install.sh
```

## How It Works

1. On session start: sources venv, runs `headroom mcp install` once, starts proxy (or reuses if running), writes session PID file, sets `ANTHROPIC_BASE_URL` in `~/.claude/settings.json`. If the proxy fails to become healthy within 30 s, it is killed by PID (not just by port, in case it hasn't bound yet) and the session exits non-zero.
2. On session stop or session end: removes PID file, kills proxy only if no other sessions remain, clears `ANTHROPIC_BASE_URL`

## Uninstalling

Run `/plugin uninstall headroom@riicodespretty` then **restart Claude Code**. There is no uninstall hook in the Claude Code plugin system, so the proxy is not automatically stopped on uninstall — it will be cleaned up when the current session ends normally. Starting a new session after uninstalling will not start a new proxy.

## Runtime State

All state in `~/.headroom/`:
- `sessions/<pid>` — one file per active Claude Code session
- `proxy.port` — port the running proxy is bound to
- `.mcp_installed` — sentinel for one-time MCP registration
- `manager.log` — timestamped log for debugging
