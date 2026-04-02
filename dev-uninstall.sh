#!/usr/bin/env bash
set -euo pipefail

CACHE_DIR="$HOME/.claude/plugins/cache/local/headroom/1.0.0"

echo "Uninstalling headroom plugin (dev mode)..."

# 1. Remove symlink from plugin cache
if [ -L "$CACHE_DIR" ]; then
  rm "$CACHE_DIR"
  echo "  ✓ Removed symlink $CACHE_DIR"
elif [ -e "$CACHE_DIR" ]; then
  echo "  ⚠ $CACHE_DIR exists but is not a symlink — skipping (manual removal needed)"
else
  echo "  ✓ Symlink already absent"
fi

# 2. Remove from enabledPlugins and clear ANTHROPIC_BASE_URL using Python
python3 - <<'PYEOF'
import json, os, sys
from pathlib import Path

settings_path = Path.home() / ".claude" / "settings.json"
if not settings_path.exists():
    print(f"  ⚠ {settings_path} not found — nothing to update", file=sys.stderr)
    sys.exit(0)

settings = json.loads(settings_path.read_text())

# Remove from enabledPlugins
plugins = settings.get("enabledPlugins", {})
if "headroom@local" in plugins:
    del plugins["headroom@local"]
    settings["enabledPlugins"] = plugins
    print("  ✓ Removed headroom@local from enabledPlugins")
else:
    print("  ✓ headroom@local was not registered — nothing to remove")

# Clear ANTHROPIC_BASE_URL from env
env = settings.get("env", {})
if "ANTHROPIC_BASE_URL" in env:
    del env["ANTHROPIC_BASE_URL"]
    settings["env"] = env
    print("  ✓ Cleared ANTHROPIC_BASE_URL from env")
else:
    print("  ✓ ANTHROPIC_BASE_URL was not set — nothing to clear")

# Write back atomically
tmp = settings_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(settings, indent=2))
os.replace(tmp, settings_path)
PYEOF


# 3. Kill running proxy (if any) before removing state directory
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

# 4. Clean up runtime state directory
HEADROOM_DIR="$HOME/.headroom"
if [ -d "$HEADROOM_DIR" ]; then
  rm -rf "$HEADROOM_DIR"
  echo "  ✓ Removed runtime state directory $HEADROOM_DIR"
else
  echo "  ✓ Runtime state directory already absent"
fi

echo ""
echo "Done! Restart Claude Code to deactivate the headroom plugin."
