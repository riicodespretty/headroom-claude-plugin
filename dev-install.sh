#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MARKETPLACE_NAME="riicodespretty"
PLUGIN_NAME="headroom"
PLUGIN_VERSION="1.0.0"
CACHE_DIR="$HOME/.claude/plugins/cache/$MARKETPLACE_NAME/$PLUGIN_NAME/$PLUGIN_VERSION"
MARKETPLACE_DIR="$HOME/.claude/plugins/marketplaces/$MARKETPLACE_NAME"
KNOWN_MARKETPLACES="$HOME/.claude/plugins/known_marketplaces.json"

echo "Installing headroom plugin (dev mode)..."

# 0. Verify headroom binary is available at the expected location
# manager.py hardcodes ~/.venv/bin/headroom — it must be there
if [ ! -x "$HOME/.venv/bin/headroom" ]; then
  echo "  ERROR: headroom not found at ~/.venv/bin/headroom." >&2
  echo "  Install it into your venv: pip install headroom" >&2
  exit 1
fi
echo "  ✓ headroom binary found at ~/.venv/bin/headroom"

# 1. Symlink repo into plugin cache
mkdir -p "$(dirname "$CACHE_DIR")"
if [ -L "$CACHE_DIR" ]; then
  rm "$CACHE_DIR"
elif [ -e "$CACHE_DIR" ]; then
  echo "  ERROR: $CACHE_DIR exists and is not a symlink — remove it manually first." >&2
  exit 1
fi
ln -s "$REPO_DIR" "$CACHE_DIR"
echo "  ✓ Symlinked $REPO_DIR → $CACHE_DIR"

# 2. Symlink repo as the marketplace directory so Claude Code can resolve it
mkdir -p "$(dirname "$MARKETPLACE_DIR")"
if [ -L "$MARKETPLACE_DIR" ]; then
  rm "$MARKETPLACE_DIR"
elif [ -e "$MARKETPLACE_DIR" ]; then
  echo "  ERROR: $MARKETPLACE_DIR exists and is not a symlink — remove it manually first." >&2
  exit 1
fi
ln -s "$REPO_DIR" "$MARKETPLACE_DIR"
echo "  ✓ Symlinked $REPO_DIR → $MARKETPLACE_DIR"

# 3. Register in known_marketplaces.json so Claude Code recognises the marketplace
python3 - "$REPO_DIR" "$MARKETPLACE_NAME" "$MARKETPLACE_DIR" <<'PYEOF'
import json, os, sys
from pathlib import Path
from datetime import datetime, timezone

repo_dir, marketplace_name, marketplace_dir = sys.argv[1], sys.argv[2], sys.argv[3]

known_path = Path.home() / ".claude" / "plugins" / "known_marketplaces.json"
known_path.parent.mkdir(parents=True, exist_ok=True)

data = {}
if known_path.exists():
    try:
        data = json.loads(known_path.read_text())
    except (json.JSONDecodeError, OSError):
        pass

data[marketplace_name] = {
    "source": {"source": "directory", "path": repo_dir},
    "installLocation": marketplace_dir,
    "lastUpdated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    "autoUpdate": False,
}

tmp = known_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(data, indent=2))
os.replace(tmp, known_path)
print(f"  ✓ Registered {marketplace_name} in known_marketplaces.json")
PYEOF

# 4. Enable the plugin and clear any stale ANTHROPIC_BASE_URL in settings.json
python3 - "$MARKETPLACE_NAME" "$PLUGIN_NAME" <<'PYEOF'
import json, os, sys
from pathlib import Path

marketplace_name, plugin_name = sys.argv[1], sys.argv[2]
plugin_key = f"{plugin_name}@{marketplace_name}"

settings_path = Path.home() / ".claude" / "settings.json"
if not settings_path.exists():
    print(f"  ERROR: {settings_path} not found. Start Claude Code at least once first.", file=sys.stderr)
    sys.exit(1)

settings = json.loads(settings_path.read_text())
settings.setdefault("enabledPlugins", {})[plugin_key] = True

tmp = settings_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(settings, indent=2))
os.replace(tmp, settings_path)
print(f"  ✓ Enabled {plugin_key} in enabledPlugins")
PYEOF

echo ""
echo "Done! Restart Claude Code to activate the headroom plugin."
echo "Verify: ls -la $CACHE_DIR"
