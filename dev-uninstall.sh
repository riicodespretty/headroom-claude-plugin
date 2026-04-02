#!/usr/bin/env bash
set -euo pipefail

MARKETPLACE_NAME="riicodespretty"
PLUGIN_NAME="headroom"
PLUGIN_VERSION="1.0.0"
CACHE_DIR="$HOME/.claude/plugins/cache/$MARKETPLACE_NAME/$PLUGIN_NAME/$PLUGIN_VERSION"
MARKETPLACE_DIR="$HOME/.claude/plugins/marketplaces/$MARKETPLACE_NAME"

echo "Uninstalling headroom plugin (dev mode)..."

# 1. Remove symlink from plugin cache
if [ -L "$CACHE_DIR" ]; then
  rm "$CACHE_DIR"
  echo "  ✓ Removed cache symlink $CACHE_DIR"
elif [ -e "$CACHE_DIR" ]; then
  echo "  ⚠ $CACHE_DIR exists but is not a symlink — skipping (manual removal needed)"
else
  echo "  ✓ Cache symlink already absent"
fi

# 2. Remove marketplace symlink
if [ -L "$MARKETPLACE_DIR" ]; then
  rm "$MARKETPLACE_DIR"
  echo "  ✓ Removed marketplace symlink $MARKETPLACE_DIR"
elif [ -e "$MARKETPLACE_DIR" ]; then
  echo "  ⚠ $MARKETPLACE_DIR exists but is not a symlink — skipping (manual removal needed)"
else
  echo "  ✓ Marketplace symlink already absent"
fi

# 3. Remove from known_marketplaces.json, enabledPlugins, and clear ANTHROPIC_BASE_URL
python3 - "$MARKETPLACE_NAME" "$PLUGIN_NAME" <<'PYEOF'
import json, os, sys
from pathlib import Path

marketplace_name, plugin_name = sys.argv[1], sys.argv[2]
plugin_key = f"{plugin_name}@{marketplace_name}"

# known_marketplaces.json
known_path = Path.home() / ".claude" / "plugins" / "known_marketplaces.json"
if known_path.exists():
    try:
        data = json.loads(known_path.read_text())
        if marketplace_name in data:
            del data[marketplace_name]
            tmp = known_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2))
            os.replace(tmp, known_path)
            print(f"  ✓ Removed {marketplace_name} from known_marketplaces.json")
        else:
            print(f"  ✓ {marketplace_name} not in known_marketplaces.json — nothing to remove")
    except (json.JSONDecodeError, OSError) as e:
        print(f"  ⚠ Could not update known_marketplaces.json: {e}", file=sys.stderr)

# settings.json — enabledPlugins and ANTHROPIC_BASE_URL
settings_path = Path.home() / ".claude" / "settings.json"
if not settings_path.exists():
    print(f"  ⚠ {settings_path} not found — skipping", file=sys.stderr)
    sys.exit(0)

settings = json.loads(settings_path.read_text())

plugins = settings.get("enabledPlugins", {})
if plugin_key in plugins:
    del plugins[plugin_key]
    settings["enabledPlugins"] = plugins
    print(f"  ✓ Removed {plugin_key} from enabledPlugins")
else:
    print(f"  ✓ {plugin_key} was not registered — nothing to remove")

env = settings.get("env", {})
if "ANTHROPIC_BASE_URL" in env:
    del env["ANTHROPIC_BASE_URL"]
    settings["env"] = env
    print("  ✓ Cleared ANTHROPIC_BASE_URL from env")
else:
    print("  ✓ ANTHROPIC_BASE_URL was not set — nothing to clear")

tmp = settings_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(settings, indent=2))
os.replace(tmp, settings_path)
PYEOF

# 4. Remove mcpServers.headroom from ~/.claude.json (reverting the command patch)
python3 - <<'PYEOF'
import json, os, sys
from pathlib import Path

claude_json = Path.home() / ".claude.json"
if not claude_json.exists():
    print("  ✓ ~/.claude.json not found — nothing to revert")
    sys.exit(0)

try:
    data = json.loads(claude_json.read_text())
except (json.JSONDecodeError, OSError) as e:
    print(f"  ⚠ Could not read ~/.claude.json: {e} — skipping", file=sys.stderr)
    sys.exit(0)

mcp_servers = data.get("mcpServers", {})
if "headroom" in mcp_servers:
    del mcp_servers["headroom"]
    data["mcpServers"] = mcp_servers
    tmp = claude_json.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, claude_json)
    print("  ✓ Removed mcpServers.headroom from ~/.claude.json")
else:
    print("  ✓ mcpServers.headroom not present in ~/.claude.json — nothing to remove")
PYEOF

# 5. Kill running proxy (if any) before removing state directory
PORT_FILE="$HOME/.headroom/proxy.port"
if [ -f "$PORT_FILE" ]; then
  PROXY_PORT="$(cat "$PORT_FILE" 2>/dev/null || true)"
  if [ -n "$PROXY_PORT" ]; then
    PROXY_PIDS="$(lsof -ti ":$PROXY_PORT" 2>/dev/null || true)"
    if [ -n "$PROXY_PIDS" ]; then
      echo "$PROXY_PIDS" | xargs kill -TERM 2>/dev/null || true
      echo "  ✓ Stopped proxy on port $PROXY_PORT"
    else
      echo "  ✓ No proxy process found on port $PROXY_PORT"
    fi
  fi
else
  echo "  ✓ No running proxy (port file absent)"
fi

# 6. Clean up runtime state directory
HEADROOM_DIR="$HOME/.headroom"
if [ -d "$HEADROOM_DIR" ]; then
  rm -rf "$HEADROOM_DIR"
  echo "  ✓ Removed runtime state directory $HEADROOM_DIR"
else
  echo "  ✓ Runtime state directory already absent"
fi

echo ""
echo "Done! Restart Claude Code to deactivate the headroom plugin."
