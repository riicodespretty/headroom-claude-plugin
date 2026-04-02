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

echo ""
echo "Done! Restart Claude Code to deactivate the headroom plugin."
