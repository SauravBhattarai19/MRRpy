#!/usr/bin/env bash
# =============================================================================
# build_windows_plugin.sh
# =============================================================================
# Builds a self-contained MRRpy_plugin.zip (any OS: Windows, macOS, Linux).
# When extracted, it produces a single "MRRpy_plugin/" folder that the user
# drops directly into their QGIS plugins directory. No extra steps needed.
#
# The core model ships as a vendored copy of the pip-installable package at
# MRRpy_plugin/_vendor/MRRpy — bridge.ensure_core() puts it on sys.path
# when the package is not already pip-installed in the QGIS interpreter.
# Its third-party dependencies (rasterio, geopandas, …) are NOT vendored; the
# plugin's Dependencies manager installs them into QGIS's Python.
#
# NOTE: remove any old "vsa_opm" / "vsa_opm_plugin" folder (earlier names of
# this plugin) before installing this build.
#
# QGIS plugins dir on Windows:
#   %APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\
#
# Usage:
#   chmod +x build_windows_plugin.sh
#   ./build_windows_plugin.sh
# =============================================================================

set -euo pipefail

OPM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$OPM_ROOT/_plugin_build"
PLUGIN_NAME="MRRpy_plugin"
PLUGIN_DIR="$BUILD_DIR/$PLUGIN_NAME"
TARGET_ZIP="$OPM_ROOT/MRRpy_plugin.zip"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   MRRpy_plugin — Plugin Package Builder          ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── Clean ─────────────────────────────────────────────────────────────────────
echo "▶ Cleaning old build..."
rm -rf "$BUILD_DIR" "$TARGET_ZIP"
mkdir -p "$PLUGIN_DIR"

# ── Copy the QGIS plugin structure ────────────────────────────────────────────
echo "▶ Copying plugin structure (bridge/, ui/, processing/, resources/)..."
cp -r "$OPM_ROOT/MRRpy_plugin/bridge"      "$PLUGIN_DIR/bridge"
cp -r "$OPM_ROOT/MRRpy_plugin/ui"          "$PLUGIN_DIR/ui"
cp -r "$OPM_ROOT/MRRpy_plugin/processing"  "$PLUGIN_DIR/processing"
cp -r "$OPM_ROOT/MRRpy_plugin/resources"   "$PLUGIN_DIR/resources"
cp    "$OPM_ROOT/MRRpy_plugin/__init__.py"  "$PLUGIN_DIR/__init__.py"
cp    "$OPM_ROOT/MRRpy_plugin/plugin.py"   "$PLUGIN_DIR/plugin.py"
cp    "$OPM_ROOT/MRRpy_plugin/metadata.txt" "$PLUGIN_DIR/metadata.txt"

# ── Vendor the core package into the plugin ───────────────────────────────────
echo "▶ Vendoring the MRRpy core package into _vendor/..."
mkdir -p "$PLUGIN_DIR/_vendor"
cp -r "$OPM_ROOT/MRRpy" "$PLUGIN_DIR/_vendor/MRRpy"

# Optional GEE service-account key: bundle it ONLY if the user placed one next
# to the repo.  It is git-ignored, so packaging it is a deliberate local choice.
if [[ -f "$OPM_ROOT/key.json" ]]; then
    cp "$OPM_ROOT/key.json" "$PLUGIN_DIR/_vendor/MRRpy/gee/key.json"
    echo "  + key.json  (GEE service-account credentials — bundled locally, NOT from git)"
else
    echo "  ℹ key.json not found — GEE features will need interactive auth or the GEE_PROJECT env var"
fi

# ── Remove __pycache__ ────────────────────────────────────────────────────────
echo "▶ Removing __pycache__ directories..."
find "$PLUGIN_DIR" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find "$PLUGIN_DIR" -type f -name "*.py[co]" -delete 2>/dev/null || true

# ── Sanity check: the vendored core must import from the plugin folder ────────
echo "▶ Checking the vendored core is importable..."
# Run from inside _vendor so the vendored copy wins over the repo checkout
# (cwd is first on sys.path), then confirm that's the copy that was imported.
( cd "$PLUGIN_DIR/_vendor" && PYTHONDONTWRITEBYTECODE=1 python3 -c \
    "import MRRpy, os, sys; assert MRRpy.__file__.startswith(os.getcwd()), MRRpy.__file__; print('  MRRpy', MRRpy.__version__, 'vendored OK')" ) \
    || echo "  ⚠ could not import the vendored MRRpy with python3 (missing deps on this machine?) — check before shipping"

# ── Show final structure ──────────────────────────────────────────────────────
echo ""
echo "▶ Final plugin structure:"
find "$PLUGIN_DIR" -type f | sort | sed "s|$PLUGIN_DIR/||"

# ── Zip ──────────────────────────────────────────────────────────────────────
echo ""
echo "▶ Creating zip: $TARGET_ZIP"
cd "$BUILD_DIR"
zip -r "$TARGET_ZIP" "$PLUGIN_NAME/"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                  BUILD COMPLETE ✅                           ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "  Zip file: $TARGET_ZIP"
echo "  $(du -sh "$TARGET_ZIP" | cut -f1) total size"
echo ""
echo "  To install (any OS):"
echo "  1. Remove any OLD 'vsa_opm' / 'vsa_opm_plugin' plugin (earlier names)."
echo "  2. QGIS → Plugins → Manage and Install Plugins → Install from ZIP"
echo "     → choose MRRpy_plugin.zip → Install Plugin."
echo "  (Or extract it and copy the '$PLUGIN_NAME' folder into your QGIS plugins"
echo "   directory, e.g. %%APPDATA%%\\QGIS\\QGIS3\\profiles\\default\\python\\plugins\\ on Windows.)"
echo ""
