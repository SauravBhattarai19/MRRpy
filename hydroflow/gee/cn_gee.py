"""
cn_gee.py
=========
SCS Curve Number raster from Google Earth Engine.

Downloads the GCN250 global curve-number dataset (Jaafar, Ahmad & El Beyrouthy,
2019 — "GCN250, new global gridded curve numbers for hydrologic modeling and
design", Scientific Data 6:145) pixel-aligned to the routing DEM.

The dataset ships three images, one per SCS Antecedent Moisture Condition:

    users/jaafarhadi/GCN250/GCN250Dry       — AMC I   (dry)
    users/jaafarhadi/GCN250/GCN250Average   — AMC II  (normal)
    users/jaafarhadi/GCN250/GCN250Wet       — AMC III (wet)

so choosing the AMC is simply choosing which image to pull — no CN-conversion
algebra is needed for this source.

Catalog / example:
    https://gee-community-catalog.org/projects/gcn250/

Authentication mirrors the rest of hydroflow.gee: lazy `import ee`, then
`auth.authenticate(project)` (GOOGLE_APPLICATION_CREDENTIALS → key.json →
GEE_PROJECT).  Everything degrades gracefully — a missing earthengine-api or a
failed download returns None so the caller can raise a clear, actionable error.
"""

import os
import logging

logger = logging.getLogger(__name__)

from .auth import authenticate as _authenticate  # noqa: E402
from .serves_gee import _download_aligned_image, _load_watershed_geometry  # noqa: E402

try:
    import ee
    GEE_AVAILABLE = True
except ImportError:
    GEE_AVAILABLE = False


# AMC code → GCN250 Earth Engine asset ID.
_GCN250_ASSETS = {
    'i':   "users/jaafarhadi/GCN250/GCN250Dry",
    'ii':  "users/jaafarhadi/GCN250/GCN250Average",
    'iii': "users/jaafarhadi/GCN250/GCN250Wet",
}


def download_cn_raster(dem_path, watershed_geojson_path, output_path,
                       amc="ii", project=None):
    """
    Download the GCN250 curve-number raster for the given Antecedent Moisture
    Condition, pixel-aligned to *dem_path* and clipped to the watershed.
    Cached to *output_path*.

    Parameters
    ----------
    dem_path              : path to the routing DEM (defines crs/transform/size)
    watershed_geojson_path: path to watershed.geojson (from the process_dem stage)
    output_path           : where to write the aligned CN GeoTIFF
    amc                   : 'i' (dry) | 'ii' (normal) | 'iii' (wet)
    project              : GEE project id (falls back to GEE_PROJECT env var)

    Returns the output path on success, or None on failure.
    """
    if os.path.isfile(output_path):
        logger.info("CN raster cached: %s", output_path)
        return output_path

    if not GEE_AVAILABLE:
        logger.warning("earthengine-api not installed")
        return None

    amc_key = str(amc).strip().lower()
    asset = _GCN250_ASSETS.get(amc_key)
    if asset is None:
        logger.warning("Unknown AMC '%s' for GCN250 (use 'i', 'ii' or 'iii')", amc)
        return None

    if not _authenticate(project):
        return None

    try:
        geometry = _load_watershed_geometry(watershed_geojson_path)
        cn_img = ee.Image(asset).rename('curve_number')

        result = _download_aligned_image(
            cn_img, dem_path, geometry, output_path, n_bands=1)
        logger.info("CN raster (GCN250 AMC-%s) downloaded: %s",
                    amc_key.upper(), output_path)
        return result

    except Exception as exc:
        logger.warning("GEE CN raster download failed: %s", exc)
        return None
