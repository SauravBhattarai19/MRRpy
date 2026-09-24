#!/usr/bin/env bash
# =============================================================================
# install_plugin.sh
# =============================================================================
# Installs (or refreshes) MRRpy_plugin by creating a symlink from the QGIS
# user plugin directory to this repository's MRRpy_plugin/ folder.
#
# A symlink means any edit you make to the source files is reflected
# immediately in QGIS — no zip-and-reinstall cycle needed during development.
#
# Usage
# -----
#   chmod +x install_plugin.sh
#   ./install_plugin.sh
#
# Then in QGIS:
#   Plugins → Manage and Install Plugins → Installed → enable "MRRpy_plugin"
#   (If it doesn't appear, run: Plugins → Reload all plugin icons)
#
# To uninstall
# ------------
#   ./install_plugin.sh --remove
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_SRC="$SCRIPT_DIR/MRRpy_plugin"
PLUGIN_NAME="MRRpy_plugin"   # must match the folder name QGIS sees

# ── Detect QGIS plugin directory ─────────────────────────────────────────────
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    QGIS_PLUGIN_DIR="$HOME/.local/share/QGIS/QGIS3/profiles/default/python/plugins"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    QGIS_PLUGIN_DIR="$HOME/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins"
else
    # Windows (Git Bash / WSL)
    QGIS_PLUGIN_DIR="$APPDATA/QGIS/QGIS3/profiles/default/python/plugins"
fi

TARGET="$QGIS_PLUGIN_DIR/$PLUGIN_NAME"

# ── Remove mode ───────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--remove" ]]; then
    if [[ -L "$TARGET" ]]; then
        rm "$TARGET"
        echo "✅  Symlink removed: $TARGET"
    elif [[ -d "$TARGET" ]]; then
        echo "⚠️   $TARGET is a real directory (not a symlink). Remove it manually."
        exit 1
    else
        echo "ℹ️   Plugin not installed at $TARGET — nothing to do."
    fi
    exit 0
fi

# ── Install ───────────────────────────────────────────────────────────────────
mkdir -p "$QGIS_PLUGIN_DIR"

if [[ -L "$TARGET" ]]; then
    echo "ℹ️   Existing symlink found. Updating …"
    rm "$TARGET"
elif [[ -d "$TARGET" ]]; then
    echo "⚠️   $TARGET is a real directory. Please remove it first:"
    echo "    rm -rf $TARGET"
    exit 1
fi

ln -s "$PLUGIN_SRC" "$TARGET"

echo ""
echo "✅  Plugin installed (symlink):"
echo "    $TARGET → $PLUGIN_SRC"
echo ""
echo "Next steps:"
echo "  1. Open QGIS."
echo "  2. Plugins → Manage and Install Plugins → Installed tab."
echo "  3. Find 'MRRpy_plugin' and tick the checkbox."
echo "  4. A toolbar button and Plugins menu entry will appear."
echo ""

# Older builds of this plugin used other folder names; they would load a
# second, outdated copy.  Point them out (never delete automatically).
for old in vsa_opm vsa_opm_plugin; do
    if [[ -e "$QGIS_PLUGIN_DIR/$old" || -L "$QGIS_PLUGIN_DIR/$old" ]]; then
        echo "⚠️   Old plugin copy found: $QGIS_PLUGIN_DIR/$old"
        echo "    Remove it so QGIS loads only MRRpy_plugin:  rm -r \"$QGIS_PLUGIN_DIR/$old\""
    fi
done
echo "Dependencies check (run in QGIS Python console or your env):"
echo "  import rasterio, pysheds, scipy, numpy, pandas"
echo "  # Optional GPU: import cupy"
