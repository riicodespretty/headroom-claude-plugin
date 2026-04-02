#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CACHE_DIR="$HOME/.claude/plugins/cache/local/headroom/1.0.0"

echo "Installing headroom plugin (dev mode)..."

# 0. Verify headroom binary is available at the expected location
# manager.py hardcodes ~/.venv/bin/headroom — it must be there
if [ ! -x "$HOME/.venv/bin/headroom" ]; then
  echo "  ERROR: headroom not found at ~/.venv/bin/headroom." >&2
  echo "  Install it into your venv: pip install headroom" >&2
  exit 1
fi
echo "  ✓ headroom binary found at ~/.venv/bin/headroom"

# 1. Create symlink into plugin cache
mkdir -p "$(dirname "$CACHE_DIR")"
if [ -L "$CACHE_DIR" ]; then
  rm "$CACHE_DIR"
elif [ -e "$CACHE_DIR" ]; then
  echo "  ERROR: $CACHE_DIR exists and is not a symlink — remove it manually first." >&2
  exit 1
fi
ln -s "$REPO_DIR" "$CACHE_DIR"
echo "  ✓ Symlinked $REPO_DIR → $CACHE_DIR"

# 2. Register in enabledPlugins using Python for safe JSON editing
python3 - <<'PYEOF'
import json, os, sys
from pathlib import Path

settings_path = Path.home() / ".claude" / "settings.json"
if not settings_path.exists():
    print(f"  ERROR: {settings_path} not found. Start Claude Code at least once first.", file=sys.stderr)
    sys.exit(1)

settings = json.loads(settings_path.read_text())
settings.setdefault("enabledPlugins", {})
settings["enabledPlugins"]["headroom@local"] = True

tmp = settings_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(settings, indent=2))
os.replace(tmp, settings_path)
print("  ✓ Registered headroom@local in enabledPlugins")
PYEOF

echo ""
echo "Done! Restart Claude Code to activate the headroom plugin."
echo "Verify: ls -la $CACHE_DIR"
