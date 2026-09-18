#!/usr/bin/env bash
# Install (or refresh) the Siril MCP bridge into Siril's user scripts folder
# so it appears under Scripts → Start MCP Bridge.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRIDGE_SRC="$ROOT/bridge/bridge.py"
WRAPPER_NAME="Start_MCP_Bridge.py"

# Siril user scripts on macOS typically live here (created after first run / prefs).
CANDIDATES=(
  "$HOME/Library/Application Support/org.siril.Siril/scripts"
  "$HOME/Library/Application Support/siril/scripts"
  "$HOME/.siril/scripts"
)

DEST_DIR="${SIRIL_SCRIPTS_DIR:-}"
if [[ -z "$DEST_DIR" ]]; then
  for d in "${CANDIDATES[@]}"; do
    if [[ -d "$d" ]]; then
      DEST_DIR="$d"
      break
    fi
  done
fi

if [[ -z "$DEST_DIR" ]]; then
  DEST_DIR="${CANDIDATES[0]}"
  mkdir -p "$DEST_DIR"
  echo "Created scripts directory: $DEST_DIR"
fi

WRAPPER="$DEST_DIR/$WRAPPER_NAME"
cat > "$WRAPPER" <<EOF
#version = 1.3.0
# Siril MCP Bridge launcher (installed by siril-mcp)
# Starts the long-lived bridge that Cursor's siril-mcp server talks to.

import runpy
runpy.run_path(r"${BRIDGE_SRC}", run_name="__main__")
EOF

chmod 644 "$WRAPPER"
echo "Installed launcher: $WRAPPER"
echo "Bridge source:      $BRIDGE_SRC"
echo
echo "In Siril:"
echo "  1. Scripts → Get Scripts / refresh if needed"
echo "  2. Run: pyscript -async $WRAPPER"
echo "     or pick '$WRAPPER_NAME' from the Scripts menu (use async if prompted)"
echo "  3. Confirm log shows: [siril-mcp] listening on .../bridge.sock"
