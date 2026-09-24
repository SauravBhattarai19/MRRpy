#!/usr/bin/env bash
# =============================================================================
# setup_qgis_linux.sh
# =============================================================================
# Full setup script for the MRRpy_plugin QGIS plugin on Ubuntu 22.04 LTS.
# Run this yourself in your SSH terminal (needs sudo password interactively).
#
# What this does:
#   Step 1 - Ensure X11 forwarding tools are present
#   Step 2 - Install QGIS 3.x (LTS) from the official QGIS apt repository
#   Step 3 - Make QGIS see your 'opm' conda environment's packages
#   Step 4 - Install MRRpy_plugin (symlink)
#   Step 5 - Verify everything works
#
# Usage:
#   chmod +x setup_qgis_linux.sh
#   ./setup_qgis_linux.sh
# =============================================================================

set -euo pipefail

OPM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPM_ENV="opm"   # your conda environment name
PLUGIN_NAME="MRRpy_plugin"   # folder name QGIS sees

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   MRRpy_plugin — Ubuntu 22.04 Installer          ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── Step 1: X11 forwarding tools ──────────────────────────────────────────────
echo "▶ Step 1/5: Installing X11 forwarding tools …"
sudo apt-get install -y --no-install-recommends \
    xauth \
    x11-utils \
    x11-apps   # includes xeyes — useful for testing X11 forwarding

echo "  ✓ X11 tools installed."
echo ""

# ── Step 2: Install QGIS from official QGIS apt repository ───────────────────
echo "▶ Step 2/5: Installing QGIS 3.x LTS …"

# Add QGIS GPG key
sudo mkdir -p /etc/apt/keyrings
sudo wget -qO /etc/apt/keyrings/qgis-archive-keyring.gpg \
    https://download.qgis.org/downloads/qgis-archive-keyring.gpg

# Add QGIS apt source (Ubuntu 22.04 / Jammy LTS)
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/qgis-archive-keyring.gpg] \
https://qgis.org/ubuntu-ltr jammy main" \
    | sudo tee /etc/apt/sources.list.d/qgis.list

sudo apt-get update -q
sudo apt-get install -y qgis python3-qgis qgis-plugin-grass

QGIS_PYTHON=$(python3 -c "import sys; print(sys.executable)" 2>/dev/null || echo "python3")
echo "  ✓ QGIS installed."
echo "  QGIS Python: $(qgis --version 2>&1 | head -1)"
echo ""

# ── Step 3: Install MRRpy dependencies into QGIS's Python ──────────────────────
echo "▶ Step 3/5: Installing MRRpy dependencies into QGIS system Python …"

# QGIS on Ubuntu 22.04 uses the system Python 3.10 (/usr/bin/python3).
# We cannot link the 'opm' conda env directly because it uses Python 3.11,
# and C-extensions (numpy, scipy, rasterio) are incompatible across versions.
# Instead, we install them directly for the system Python using pip.

sudo apt-get install -y python3-pip
sudo /usr/bin/python3 -m pip install --upgrade pip
# Keep in step with MRRpy_plugin/bridge/dependencies.py::REQUIRED.
sudo /usr/bin/python3 -m pip install "numpy<2" pandas scipy rasterio pyflwdir pysheds numba \
    geopandas shapely pyproj matplotlib pyyaml

echo "  ✓ Dependencies installed into QGIS Python."
echo ""

# Verify key packages are visible from system Python (what QGIS uses)
echo "  Verifying package imports via system Python …"
/usr/bin/python3 -c "
ok = []
fail = []
for pkg in ['numpy', 'pandas', 'scipy', 'rasterio', 'pyflwdir', 'pysheds', 'numba',
            'geopandas', 'shapely', 'pyproj', 'matplotlib', 'yaml']:
    try:
        __import__(pkg)
        ok.append(pkg)
    except ImportError as e:
        fail.append(f'{pkg} ({e})')
print('  ✓ OK:  ', ', '.join(ok))
if fail:
    print('  ✗ FAIL:', ', '.join(fail))
"

# CuPy check
echo "  Checking for GPU support (CuPy) …"
/usr/bin/python3 -c "
try:
    import cupy as cp
    cp.cuda.Device(0).id
    print('  ✓ CuPy GPU: available (will enable GPU backend in QGIS)')
except Exception as e:
    print(f'  ℹ CuPy: {e} (CPU mode will be used)')
"
echo ""

# ── Step 4: Install the plugin (symlink) ──────────────────────────────────────
echo "▶ Step 4/5: Installing MRRpy_plugin (symlink) …"

QGIS_PLUGIN_DIR="$HOME/.local/share/QGIS/QGIS3/profiles/default/python/plugins"
mkdir -p "$QGIS_PLUGIN_DIR"

TARGET="$QGIS_PLUGIN_DIR/$PLUGIN_NAME"
if [[ -L "$TARGET" ]]; then
    rm "$TARGET"
    echo "  Removed old symlink."
fi

ln -s "$OPM_ROOT/MRRpy_plugin" "$TARGET"
echo "  ✓ Plugin symlinked: $TARGET → $OPM_ROOT/MRRpy_plugin"
echo ""

# ── Step 5: Verify ────────────────────────────────────────────────────────────
echo "▶ Step 5/5: Verification …"

# Check plugin metadata.txt exists
if [[ -f "$TARGET/metadata.txt" ]]; then
    echo "  ✓ Plugin files present."
else
    echo "  ✗ metadata.txt missing in plugin directory!"
fi

# Run the config bridge tests (no QGIS needed)
echo "  Running unit tests …"
conda run -n "$OPM_ENV" python -m pytest \
    "$OPM_ROOT/MRRpy_plugin/tests/test_config_bridge.py" -q 2>&1 | tail -3
echo ""

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                    SETUP COMPLETE ✅                         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "  How to open QGIS with X11 forwarding:"
echo "    1. In your MobaXterm / SSH -X terminal:"
echo "       qgis &"
echo ""
echo "    2. In QGIS:"
echo "       Plugins → Manage and Install Plugins"
echo "       → Installed tab → tick 'MRRpy_plugin'"
echo ""
echo "  If QGIS appears slow over X11, consider using NoMachine or"
echo "  TigerVNC + a VNC viewer on Windows for better performance."
echo ""
