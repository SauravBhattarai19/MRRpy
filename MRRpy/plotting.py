# -*- coding: utf-8 -*-
"""
plotting.py
===========
Small, good-enough plotting helpers for common pipeline outputs, so a run's
results can be visualized in one call instead of hand-writing
matplotlib/rasterio/geopandas boilerplate every time.

Every function accepts *flexible input*: a path (to a file or an OUTPUT_DIR),
a pandas DataFrame (where applicable), a run_pipeline()/stage result dict, or
a Config object (its OUTPUT_DIR / derived-path attributes are used). Every
function returns ``(fig, ax)`` and accepts an optional ``ax=`` to draw into
caller-provided axes, matplotlib convention.

matplotlib/rasterio/geopandas/pandas are hard dependencies of MRRpy, so
these imports are unconditional — no optional-dependency handling needed.
"""

import os

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


def _get_fig_ax(ax):
    if ax is None:
        fig, ax = plt.subplots(figsize=(8, 5))
    else:
        fig = ax.figure
    return fig, ax


def _resolve_df(source, *, df_key, csv_key, cfg_attr, default_filename):
    """Resolve *source* to a DataFrame: DataFrame passthrough, dict (prefers
    an already-loaded DataFrame under df_key, else reads csv_key), a
    Config-like object (uses cfg_attr, falling back to OUTPUT_DIR/default),
    or a path (file, or a directory to join with default_filename)."""
    if isinstance(source, pd.DataFrame):
        return source
    if isinstance(source, dict):
        if df_key in source and isinstance(source[df_key], pd.DataFrame):
            return source[df_key]
        if csv_key in source:
            return pd.read_csv(source[csv_key])
        raise KeyError(
            f"dict source has neither '{df_key}' nor '{csv_key}' key; "
            f"pass a path, DataFrame, or Config object instead."
        )
    if hasattr(source, cfg_attr) or hasattr(source, "OUTPUT_DIR"):
        path = getattr(source, cfg_attr, None) or os.path.join(
            getattr(source, "OUTPUT_DIR", "."), default_filename)
        return pd.read_csv(path)
    path = str(source)
    if os.path.isdir(path):
        path = os.path.join(path, default_filename)
    return pd.read_csv(path)


def _resolve_path(source, *, key, cfg_attr, default_filename):
    """Resolve *source* to a file path: dict (looks up key), a Config-like
    object (uses cfg_attr, falling back to OUTPUT_DIR/default_filename), or
    a path (file, or a directory to join with default_filename)."""
    if isinstance(source, dict):
        if key in source:
            return source[key]
        raise KeyError(f"dict source has no '{key}' key.")
    if hasattr(source, cfg_attr):
        v = getattr(source, cfg_attr)
        if v:
            return v
    if hasattr(source, "OUTPUT_DIR"):
        return os.path.join(source.OUTPUT_DIR, default_filename)
    path = str(source)
    if os.path.isdir(path):
        return os.path.join(path, default_filename)
    return path


def plot_hydrograph(source, ax=None, *, label=None, annotate_peak=True,
                    color=None, **kwargs):
    """
    Plot outlet discharge Q(t) from a hydrograph.

    Parameters
    ----------
    source : str | os.PathLike | pandas.DataFrame | dict | Config
        Path to hydrograph.csv (or an OUTPUT_DIR containing it), an
        already-loaded DataFrame (time_hr, Q_m3s columns), a run_pipeline()
        result dict (uses 'hydrograph_df' if present, else 'hydrograph_csv'),
        or a Config object (uses HYDROGRAPH_CSV).
    ax : matplotlib.axes.Axes, optional
    label : str, optional legend label
    annotate_peak : bool, default True — mark peak Q with a dot + label
    color : str, optional line color

    Returns
    -------
    (fig, ax)
    """
    df = _resolve_df(source, df_key="hydrograph_df", csv_key="hydrograph_csv",
                     cfg_attr="HYDROGRAPH_CSV", default_filename="hydrograph.csv")
    fig, ax = _get_fig_ax(ax)
    ax.plot(df["time_hr"], df["Q_m3s"], label=label, color=color, **kwargs)

    if annotate_peak and len(df):
        i = df["Q_m3s"].idxmax()
        peak_t, peak_q = df["time_hr"].loc[i], df["Q_m3s"].loc[i]
        ax.plot(peak_t, peak_q, "o", color=color or "crimson", zorder=5)
        ax.annotate(f"peak {peak_q:.2f} m³/s\n@ t={peak_t:.2f} h",
                   (peak_t, peak_q), textcoords="offset points",
                   xytext=(10, -28), fontsize=9)

    ax.set_xlabel("Time (hours)")
    ax.set_ylabel("Discharge Q (m³/s)")
    ax.set_title("Outlet hydrograph")
    if label:
        ax.legend()
    return fig, ax


def plot_raster(source, ax=None, *, cmap="viridis", label=None,
                hillshade=False, **kwargs):
    """
    Generic single-band GeoTIFF viewer (DEM, Manning's n raster, flow
    accumulation, ...).

    Parameters
    ----------
    source : str | os.PathLike
        Path to a single-band GeoTIFF.
    ax : matplotlib.axes.Axes, optional
    cmap : str, colormap (ignored when hillshade=True)
    label : str, optional colorbar label
    hillshade : bool, default False — render as a shaded-relief RGB (no
        colorbar) instead of a flat colormap; intended for DEMs.

    Returns
    -------
    (fig, ax)
    """
    import rasterio
    from rasterio.plot import plotting_extent

    path = str(source)
    with rasterio.open(path) as src:
        arr = src.read(1, masked=True)
        ext = plotting_extent(src)

    fig, ax = _get_fig_ax(ax)

    if hillshade:
        from matplotlib.colors import LightSource
        ls = LightSource(azdeg=315, altdeg=45)
        filled = arr.filled(np.nanmin(arr) if arr.count() else 0.0)
        rgb = ls.shade(filled, cmap=plt.get_cmap(cmap), vert_exag=2,
                       blend_mode="soft")
        ax.imshow(rgb, extent=ext)
    else:
        im = ax.imshow(arr, extent=ext, cmap=cmap, **kwargs)
        fig.colorbar(im, ax=ax, label=label or "")

    ax.set_xlabel("Easting (m)")
    ax.set_ylabel("Northing (m)")
    return fig, ax


def plot_watershed(source, ax=None, *, cmap="terrain", boundary_color="crimson",
                   hillshade=True, **kwargs):
    """
    Plot the clipped DEM (optionally hillshaded) with the delineated
    watershed boundary overlaid.

    Parameters
    ----------
    source : dict | Config | str | os.PathLike
        A run_pipeline()/stage_process_dem result dict (uses 'clipped_dem'
        and 'watershed_geojson'), a Config object (uses ROUTING_DEM_PATH and
        WATERSHED_GEOJSON), or an OUTPUT_DIR path.
    ax : matplotlib.axes.Axes, optional
    cmap : str, DEM colormap (ignored when hillshade=True)
    boundary_color : str, watershed boundary line color
    hillshade : bool, default True

    Returns
    -------
    (fig, ax)
    """
    import geopandas as gpd

    dem_path = _resolve_path(source, key="clipped_dem",
                             cfg_attr="ROUTING_DEM_PATH",
                             default_filename="clipped_dem.tif")
    geojson_path = _resolve_path(source, key="watershed_geojson",
                                 cfg_attr="WATERSHED_GEOJSON",
                                 default_filename="watershed.geojson")

    fig, ax = plot_raster(dem_path, ax=ax, cmap=cmap, hillshade=hillshade, **kwargs)
    gpd.read_file(geojson_path).boundary.plot(ax=ax, color=boundary_color,
                                              linewidth=1.5)
    ax.set_title("Watershed")
    return fig, ax


def plot_mass_balance(source, ax=None, *, run_tag=None):
    """
    Bar chart of a run's mass-balance closure: total input (rainfall-derived
    runoff + boundary-condition inflow) vs outflow vs storage vs closure
    error, read from mass_balance.csv.

    Parameters
    ----------
    source : str | os.PathLike | pandas.DataFrame | dict | Config
        Path to mass_balance.csv (or an OUTPUT_DIR containing it), an
        already-loaded DataFrame, a run_pipeline() result dict (uses
        'mass_balance_csv'), or a Config object (uses MASS_BALANCE_CSV).
    ax : matplotlib.axes.Axes, optional
    run_tag : str, optional — select a specific RUN_TAG row; default: last row.

    Returns
    -------
    (fig, ax)
    """
    df = _resolve_df(source, df_key="mass_balance_df", csv_key="mass_balance_csv",
                     cfg_attr="MASS_BALANCE_CSV",
                     default_filename="mass_balance.csv")
    row = df[df["run_tag"] == run_tag].iloc[-1] if run_tag else df.iloc[-1]

    total_in = float(row["input_m3"]) + float(row["bc_inflow_m3"])
    values = [total_in, float(row["outflow_m3"]), float(row["storage_m3"]),
             float(row["error_m3"])]
    labels = ["Input\n(runoff+BC)", "Outflow", "Storage", "Error"]
    colors = ["#3b6ea5", "#e08214", "#7a7a7a", "#c0392b"]

    fig, ax = _get_fig_ax(ax)
    ax.bar(labels, values, color=colors)
    ax.set_ylabel("Volume (m³)")
    ax.set_title(f"Mass balance (rel. error {float(row['rel_error']):.2e})")
    return fig, ax


# ── Flow propagation from the saved fields (SAVE_FIELDS=True) ─────────────────

# Log colours for depth too: a storm leaves a few cm of sheet flow on every
# hillslope and metres in the rivers; on a linear scale the rivers vanish.
_FIELD_STYLE = {          # var → (label, colormap, default "wet" threshold, log colours)
    "depth":     ("Water depth",    "Blues",   0.01, True),
    "discharge": ("Discharge",      "viridis", 0.01, True),
    "velocity":  ("Velocity",       "magma",   0.01, False),
    "volume":    ("Stored water",   "Blues",   1.0,  True),
}
# Every hillslope cell carries a little flow; to make the river network stand
# out, these maps also hide values below this fraction of the run's peak.
_RELATIVE_FLOOR = {"discharge": 1e-3, "volume": 1e-3}


def _default_floor(var, values, min_value):
    """The 'dry' threshold: *min_value* if given, else the variable's default
    (for discharge/volume at least 0.1 % of the run's peak)."""
    if min_value is not None:
        return float(min_value)
    thr = _FIELD_STYLE.get(var, (None, None, 0.0, None))[2]
    rel = _RELATIVE_FLOOR.get(var)
    if rel:
        peak = float(np.nanmax(values)) if np.size(values) else 0.0
        thr = max(thr, rel * peak) if np.isfinite(peak) else thr
    return thr


def _fields_npz(source):
    """Resolve *source* to the fields.npz path: a run_pipeline() result dict
    ('fields_dir'), a Config (FIELD_OUTPUT_DIR, else OUTPUT_DIR/fields), the
    fields.npz file, its folder, or an OUTPUT_DIR that holds fields/."""
    if isinstance(source, dict):
        if "fields_dir" in source:
            path = source["fields_dir"]
        elif "hydrograph_csv" in source:
            path = os.path.join(os.path.dirname(source["hydrograph_csv"]), "fields")
        else:
            raise KeyError("dict source has no 'fields_dir' key — was SAVE_FIELDS on?")
    elif hasattr(source, "OUTPUT_DIR"):
        path = (getattr(source, "FIELD_OUTPUT_DIR", None)
                or os.path.join(source.OUTPUT_DIR, "fields"))
    else:
        path = str(source)
    if os.path.isdir(path):
        if os.path.isfile(os.path.join(path, "fields.npz")):
            path = os.path.join(path, "fields.npz")
        else:
            path = os.path.join(path, "fields", "fields.npz")
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"No saved maps found at {path}. Run the model with SAVE_FIELDS: true "
            "to record depth/discharge maps over time.")
    return path


def _load_fields(source, var):
    """(archive, meta, values (T, N), npz path) for *var*, with a clear error
    when *var* was not recorded."""
    from .core.routing.fields import load_field_archive
    npz = _fields_npz(source)
    arch = load_field_archive(npz)
    meta = arch.get("meta", {})
    if var not in arch:
        have = [v for v in _FIELD_STYLE if v in arch]
        raise KeyError(f"'{var}' was not saved in {npz}; it has {have}. "
                       "Add it to FIELD_VARS and run again.")
    return arch, meta, arch[var], npz


def _sibling(npz, meta, key, filename):
    """A run output recorded in the meta (newer archives) or next to fields/."""
    path = meta.get(key)
    if path and os.path.isfile(path):
        return path
    for d in (os.path.dirname(os.path.dirname(npz)), os.path.dirname(npz)):
        p = os.path.join(d, filename)
        if os.path.isfile(p):
            return p
    return None


def _grid_extent(meta):
    a, _b, c, _d, e, f = meta["transform"]
    nrows, ncols = int(meta["nrows"]), int(meta["ncols"])
    return [c, c + a * ncols, f + e * nrows, f]


def _hillshade(ax, npz, meta):
    """Grey shaded relief of the routing DEM under the map (skipped if absent)."""
    import rasterio
    from matplotlib.colors import LightSource
    dem_path = _sibling(npz, meta, "dem_path", "clipped_dem.tif")
    if not dem_path:
        return
    with rasterio.open(dem_path) as src:
        dem = src.read(1, masked=True)
    if dem.shape != (int(meta["nrows"]), int(meta["ncols"])) or not dem.count():
        return
    filled = dem.filled(float(dem.min()))
    shade = LightSource(azdeg=315, altdeg=45).hillshade(
        filled, vert_exag=2, dx=float(meta["cell_size"]), dy=float(meta["cell_size"]))
    shade = np.ma.masked_where(np.ma.getmaskarray(dem), shade)
    # Muted greys (never pure black/white) so the water colours stay readable.
    ax.imshow(shade, extent=_grid_extent(meta), cmap="gray", vmin=-0.6, vmax=1.4,
              interpolation="nearest")


def _field_cmap(name):
    """Colormap for water on relief: sequential maps are cut at their pale end
    so even shallow water stands out from the grey relief."""
    from matplotlib.colors import ListedColormap
    base = plt.get_cmap(name)
    if name in ("Blues", "YlGnBu", "GnBu", "PuBu"):
        return ListedColormap(base(np.linspace(0.35, 1.0, 256)), name=f"{name}_cut")
    if name in ("viridis", "magma", "plasma", "inferno", "cividis"):   # drop near-black
        return ListedColormap(base(np.linspace(0.2, 1.0, 256)), name=f"{name}_cut")
    return base


def _map_axes(ax):
    """Plain metre tick labels (no offset), few enough not to overlap."""
    from matplotlib.ticker import MaxNLocator
    ax.ticklabel_format(useOffset=False, style="plain")
    ax.xaxis.set_major_locator(MaxNLocator(4))
    ax.yaxis.set_major_locator(MaxNLocator(5))
    ax.set_xlabel("Easting (m)")
    ax.set_ylabel("Northing (m)")


def _colorbar(fig, im, ax, label, unit):
    """Colour bar with plain numbers (0.01, 0.1, 1) rather than powers of ten."""
    from matplotlib.ticker import FuncFormatter
    cb = fig.colorbar(im, ax=ax, label=f"{label} ({unit})" if unit else label)
    cb.ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _pos: f"{v:g}"))
    return cb


def _field_norm(var, vmax, min_value, log):
    from matplotlib.colors import LogNorm, Normalize
    vmax = max(float(vmax), min_value * 10.0)
    return LogNorm(vmin=min_value, vmax=vmax) if log else Normalize(vmin=0.0, vmax=vmax)


def _frame(values, meta, arch, i, min_value):
    """2-D masked map of frame *i* (or of the peak when i is None); cells that
    stay below *min_value* (dry) are masked so the relief shows through."""
    from .core.routing.fields import field_to_2d
    v = values.max(axis=0) if i is None else values[i]
    grid = field_to_2d(v, arch)
    return np.ma.masked_where(~np.isfinite(grid) | (grid < min_value), grid)


def _frame_index(times_s, time):
    """'peak' → None; 'last' → final frame; int → that frame; float → nearest hour."""
    if time is None or time == "peak":
        return None
    if time == "last":
        return len(times_s) - 1
    if isinstance(time, (int, np.integer)) and not isinstance(time, bool):
        return int(time)
    return int(np.argmin(np.abs(times_s / 3600.0 - float(time))))


# ── River lines: discharge drawn along the D8 network, thicker where it is larger ─

_LINE_WIDTH = (0.4, 4.5)       # line width [points] at the dry threshold → at the run's peak


def _flow_segments(npz, meta, arch, values, floor):
    """Line segments joining each cell that ever carries more than *floor* to
    its downstream neighbour (read from flow_direction.tif next to the run).
    Returns (segments (M, 2, 2), cell indices (M,)) or None if the flow
    directions cannot be found."""
    from affine import Affine
    from .core.routing.terrain import D8_MOVE, _read_on_grid
    fdir_path = _sibling(npz, meta, "fdir_path", "flow_direction.tif")
    if not fdir_path:
        return None
    nrows, ncols = int(meta["nrows"]), int(meta["ncols"])
    try:
        fdir, _ = _read_on_grid(fdir_path, (nrows, ncols), Affine(*meta["transform"]))
    except ValueError:                       # not on the routing grid
        return None
    idx = np.nonzero(values.max(axis=0) >= floor)[0]
    rows = np.asarray(arch["s_rows"])[idx]
    cols = np.asarray(arch["s_cols"])[idx]
    d = fdir[rows, cols]
    dr = np.zeros(idx.size)
    dc = np.zeros(idx.size)
    for code, (r_, c_) in D8_MOVE.items():
        m = d == code
        dr[m], dc[m] = r_, c_
    # An exit cell's line runs half a cell towards the edge; a pit is a dot.
    a, _b, c0, _d, e, f0 = meta["transform"]
    rn, cn = rows + dr, cols + dc
    out = (rn < 0) | (rn >= nrows) | (cn < 0) | (cn >= ncols)
    rn = np.where(out, rows + dr / 2.0, rn)
    cn = np.where(out, cols + dc / 2.0, cn)
    x0, y0 = c0 + (cols + 0.5) * a, f0 + (rows + 0.5) * e
    x1, y1 = c0 + (cn + 0.5) * a, f0 + (rn + 0.5) * e
    segs = np.stack([np.column_stack([x0, y0]), np.column_stack([x1, y1])], axis=1)
    return segs, idx


def _line_style(q, floor, peak):
    """(masked colour values, line widths): width grows with log(flow) from
    the dry threshold to the run's peak; cells below the threshold vanish."""
    q = np.asarray(q, dtype=np.float64)
    wet = np.isfinite(q) & (q >= floor)
    lo, hi = np.log(max(floor, 1e-12)), np.log(max(peak, floor * 10.0))
    frac = np.clip((np.log(np.maximum(q, 1e-12)) - lo) / (hi - lo), 0.0, 1.0)
    # frac**1.5: big rivers stand out from mid-sized tributaries.
    widths = np.where(wet, _LINE_WIDTH[0] + frac ** 1.5 * (_LINE_WIDTH[1] - _LINE_WIDTH[0]), 0.0)
    return np.ma.masked_where(~wet, q), widths


def _add_flow_lines(ax, segs, q, floor, peak, cmap, norm):
    from matplotlib.collections import LineCollection
    cmap = cmap.with_extremes(bad=(0, 0, 0, 0))     # below threshold → invisible
    arr, widths = _line_style(q, floor, peak)
    lc = LineCollection(segs, cmap=cmap, norm=norm, linewidths=widths,
                        capstyle="round", joinstyle="round", zorder=3)
    lc.set_array(arr)
    ax.add_collection(lc)
    return lc


def _update_flow_lines(lc, q, floor, peak):
    arr, widths = _line_style(q, floor, peak)
    lc.set_array(arr)
    lc.set_linewidths(widths)


def _wants_lines(var, lines):
    return var == "discharge" if lines is None else bool(lines)


def _set_map_limits(ax, meta):
    """Lines don't set the axes limits the way an image does: use the grid's."""
    x0, x1, y0, y1 = _grid_extent(meta)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")


def plot_field(source, var="depth", time="peak", ax=None, *, min_value=None,
               cmap=None, log=None, hillshade=True, lines=None):
    """
    Map of one saved field (water depth, discharge, velocity) over the
    shaded relief — at one moment, or its peak over the whole run.

    Parameters
    ----------
    source : dict | Config | str | os.PathLike
        A run_pipeline() result dict, a Config, an OUTPUT_DIR, the fields/
        folder or the fields.npz file (needs a run with SAVE_FIELDS=True).
    var : 'depth' | 'discharge' | 'velocity' | 'volume'
    time : 'peak' (default: the highest value each cell reached), 'last',
        an int (saved-map index) or a float (hours; the nearest saved map).
    ax : matplotlib.axes.Axes, optional
    min_value : cells below this are treated as dry and left transparent
        (default 0.01 m or 0.01 m/s; for discharge 0.1 % of the run's peak,
        at least 0.01 m³/s, so the river network stands out).
    cmap : colormap name (defaults per variable)
    log : log colour scale (default: True for depth, discharge and volume,
        so rivers and thin sheet flow both show)
    hillshade : bool, draw the relief from clipped_dem.tif underneath.
    lines : draw the field as river lines along the flow network whose width
        and colour both grow with the value (default: True for discharge;
        needs flow_direction.tif next to the run, else falls back to cells).

    Returns
    -------
    (fig, ax)
    """
    arch, meta, values, npz = _load_fields(source, var)
    label, cm, _thr, lg = _FIELD_STYLE.get(var, (var, "viridis", 0.0, False))
    min_value = _default_floor(var, values, min_value)
    log = lg if log is None else log
    unit = meta.get("units", {}).get(var, "")

    i = _frame_index(arch["times_s"], time)
    grid = _frame(values, meta, arch, i, min_value)

    fig, ax = _get_fig_ax(ax)
    if hillshade:
        _hillshade(ax, npz, meta)
    vmax = grid.max() if grid.count() else 1.0
    norm = _field_norm(var, vmax, min_value, log)
    flow = _flow_segments(npz, meta, arch, values, min_value) if _wants_lines(var, lines) else None
    if flow is not None:
        segs, idx = flow
        v = values.max(axis=0) if i is None else values[i]
        im = _add_flow_lines(ax, segs, v[idx], min_value, float(vmax),
                             _field_cmap(cmap or cm), norm)
        _set_map_limits(ax, meta)
    else:
        im = ax.imshow(grid, extent=_grid_extent(meta), cmap=_field_cmap(cmap or cm),
                       norm=norm, interpolation="nearest")
    _colorbar(fig, im, ax, label, unit)
    when = ("peak over the run" if i is None
            else f"t = {arch['times_s'][i] / 3600.0:.2f} h")
    ax.set_title(f"{label}, {when}")
    _map_axes(ax)
    return fig, ax


def animate_fields(source, var="depth", out_path=None, *, fps=8, every=1,
                   min_value=None, cmap=None, log=None, hillshade=True,
                   hydrograph=True, dpi=100, lines=None):
    """
    Animation of how the water spreads: one frame per saved map, colours on a
    fixed scale (up to the run's peak) so frames compare directly, the time
    written in the title, and (optionally) the hydrograph with a moving
    time marker beside the maps.

    Parameters
    ----------
    source : see :func:`plot_field` (needs a run with SAVE_FIELDS=True).
    var : 'depth' | 'discharge' | 'velocity' | 'volume', or a list of them
        to animate side by side, e.g. ``["depth", "discharge"]`` shows where
        the water is and how much is flowing in the same frame.
    out_path : '.gif' (default, ``<var>_animation.gif`` next to fields/) or
        '.mp4' (needs ffmpeg).
    fps : frames per second.
    every : use every Nth saved map (shorter, smaller file).
    min_value, cmap, log, hillshade : as in :func:`plot_field`; when given,
        they apply to every map.
    hydrograph : show hydrograph.csv beside the maps when it is available.
    dpi : resolution of the frames.
    lines : draw as river lines that get wider and brighter as the flow
        grows (default: True for discharge; see :func:`plot_field`).

    Returns
    -------
    str — the path written.
    """
    import matplotlib.animation as animation

    names = [var] if isinstance(var, str) else list(var)
    if not names:
        raise ValueError("var is empty — name at least one saved quantity, e.g. 'depth'.")
    panels = []
    for name in names:
        arch, meta, values, npz = _load_fields(source, name)
        label, cm, _thr, lg = _FIELD_STYLE.get(name, (name, "viridis", 0.0, False))
        panels.append(dict(
            name=name, values=values, label=label, cmap=_field_cmap(cmap or cm),
            min_value=_default_floor(name, values, min_value),
            log=lg if log is None else log, unit=meta.get("units", {}).get(name, "")))
    times_h = np.asarray(arch["times_s"]) / 3600.0
    frames = list(range(0, len(times_h), max(1, int(every))))

    if out_path is None:
        out_path = os.path.join(os.path.dirname(os.path.dirname(npz)),
                                f"{'_'.join(names)}_animation.gif")
    out_path = str(out_path)

    hyd_path = _sibling(npz, meta, "hydrograph_csv", "hydrograph.csv") if hydrograph else None
    n_ax = len(panels) + (1 if hyd_path else 0)
    ratios = [1.3] * len(panels) + ([1.0] if hyd_path else [])
    fig, axes = plt.subplots(1, n_ax, figsize=(6.2 * len(panels) + (5.0 if hyd_path else 0.6), 5.2),
                             gridspec_kw={"width_ratios": ratios}, squeeze=False)
    axes = list(axes[0])
    axh = axes.pop() if hyd_path else None

    for ax, p in zip(axes, panels):
        if hillshade:
            _hillshade(ax, npz, meta)
        peak = p["values"].max()
        p["peak"] = float(peak) if np.isfinite(peak) else 1.0
        norm = _field_norm(None, p["peak"], p["min_value"], p["log"])
        flow = (_flow_segments(npz, meta, arch, p["values"], p["min_value"])
                if _wants_lines(p["name"], lines) else None)
        if flow is not None:
            p["segs_idx"] = flow[1]
            p["lc"] = p["im"] = _add_flow_lines(
                ax, flow[0], p["values"][frames[0]][flow[1]], p["min_value"],
                p["peak"], p["cmap"], norm)
            _set_map_limits(ax, meta)
        else:
            p["lc"] = None
            p["im"] = ax.imshow(_frame(p["values"], meta, arch, frames[0], p["min_value"]),
                                extent=_grid_extent(meta), cmap=p["cmap"], norm=norm,
                                interpolation="nearest")
        _colorbar(fig, p["im"], ax, p["label"], p["unit"])
        _map_axes(ax)
        p["title"] = ax.set_title("")

    cursor = None
    if axh is not None:
        df = pd.read_csv(hyd_path)
        whole = "Q_total_outflow_m3s" in df
        axh.plot(df["time_hr"], df["Q_m3s"], color="#1f4e79",
                 label="Main exit (largest river)" if whole else "Outlet")
        if whole:
            axh.plot(df["time_hr"], df["Q_total_outflow_m3s"], color="#e08214",
                     linestyle="--", label="All water leaving the DEM")
            axh.legend(loc="upper right", fontsize=8)
        axh.set_xlabel("Time (hours)")
        axh.set_ylabel("Discharge Q (m³/s)")
        axh.set_title("Hydrograph")
        cursor = axh.axvline(times_h[frames[0]], color="black", linewidth=1.2)
    fig.tight_layout()

    def update(k):
        i = frames[k]
        artists = []
        for p in panels:
            if p["lc"] is not None:
                _update_flow_lines(p["lc"], p["values"][i][p["segs_idx"]],
                                   p["min_value"], p["peak"])
            else:
                p["im"].set_data(_frame(p["values"], meta, arch, i, p["min_value"]))
            p["title"].set_text(f"{p['label']} at t = {times_h[i]:.2f} h")
            artists += [p["im"], p["title"]]
        if cursor is not None:
            cursor.set_xdata([times_h[i], times_h[i]])
            artists.append(cursor)
        return artists

    anim = animation.FuncAnimation(fig, update, frames=len(frames),
                                   interval=1000.0 / fps, blit=False)
    if out_path.lower().endswith(".mp4"):
        if not animation.FFMpegWriter.isAvailable():
            plt.close(fig)
            raise RuntimeError("Writing .mp4 needs ffmpeg, which was not found. "
                               "Install ffmpeg, or save a .gif instead.")
        writer = animation.FFMpegWriter(fps=fps)
    else:
        writer = animation.PillowWriter(fps=fps)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    anim.save(out_path, writer=writer, dpi=dpi)
    plt.close(fig)
    print(f"Animation saved to: {out_path}  ({len(frames)} frames)")
    return out_path


def export_peak_maps(source, vars=None, out_dir=None, *, min_value=None):
    """
    GeoTIFFs of the highest value each cell reached and when, for QGIS or any
    GIS: ``max_<var>.tif`` and ``time_of_max_<var>_hours.tif``.

    Parameters
    ----------
    source : see :func:`plot_field` (needs a run with SAVE_FIELDS=True).
    vars : which saved quantities (default: depth, discharge and velocity,
        those that were recorded).
    out_dir : folder to write to (default: the run's OUTPUT_DIR).
    min_value : cells whose peak stays below this are "never wet": their
        time-of-peak is left empty (defaults as in :func:`plot_field`).

    Returns
    -------
    dict {filename stem: path}
    """
    import rasterio
    from affine import Affine
    from .core.routing.fields import field_to_2d, load_field_archive

    npz = _fields_npz(source)
    arch = load_field_archive(npz)
    meta = arch.get("meta", {})
    if vars is None:
        vars = [v for v in ("depth", "discharge", "velocity") if v in arch]
    elif isinstance(vars, str):
        vars = [vars]
    out_dir = out_dir or os.path.dirname(os.path.dirname(npz))
    os.makedirs(out_dir, exist_ok=True)

    profile = dict(driver="GTiff", height=int(meta["nrows"]), width=int(meta["ncols"]),
                   count=1, dtype="float32", nodata=-9999.0,
                   transform=Affine(*meta["transform"]), crs=meta.get("crs") or None,
                   compress="deflate")
    times_h = np.asarray(arch["times_s"]) / 3600.0
    written = {}
    for var in vars:
        if var not in arch:
            raise KeyError(f"'{var}' was not saved in {npz}. Add it to FIELD_VARS and run again.")
        thr = _FIELD_STYLE.get(var, (None, None, 0.0, None))[2] if min_value is None else float(min_value)
        vals = arch[var]
        peak = vals.max(axis=0)
        t_peak = np.where(peak >= thr, times_h[vals.argmax(axis=0)], np.nan)
        for stem, data in ((f"max_{var}", peak), (f"time_of_max_{var}_hours", t_peak)):
            grid = field_to_2d(data, arch, fill=np.nan)
            path = os.path.join(out_dir, f"{stem}.tif")
            with rasterio.open(path, "w", **profile) as dst:
                dst.write(np.where(np.isfinite(grid), grid, -9999.0).astype("float32"), 1)
            written[stem] = path
            print(f"Saved {path}")
    return written
