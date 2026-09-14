"""
generate_presentation_figures.py  — v2 (watershed-cropped, 16:9 optimised)
===========================================================================
All spatial figures are cropped to the watershed bounding box.
Sizes are tuned for 16:9 Reveal.js slides (1280×720).

Run from project root:  python tools/generate_presentation_figures.py
"""

import os, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors  as mcolors
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
from matplotlib.colors import LightSource, LinearSegmentedColormap
import matplotlib.ticker  as mticker
import pandas as pd
import rasterio, math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

OUT = "output/figures"
os.makedirs(OUT, exist_ok=True)

# ── Watershed crop constants (pre-computed) ───────────────────────────────────
R0, R1, C0, C1 = 291, 653, 159, 548   # pixel window (with ~5 % padding)

def crop(arr):
    """Crop 2-D array to watershed bounding box."""
    return arr[R0:R1, C0:C1]

def ws_extent(transform):
    """Geographic extent [left, right, bottom, top] for the cropped window."""
    t = transform
    return (t.c + C0*t.a,   # left
            t.c + C1*t.a,   # right
            t.f + R1*t.e,   # bottom  (t.e < 0)
            t.f + R0*t.e)   # top

# ── Shared palette ────────────────────────────────────────────────────────────
DARK    = "#0d1117"
PANEL   = "#161b22"
BORDER  = "#30363d"
TXT     = "#e6edf3"
TXT2    = "#8b949e"
BLUE    = "#58a6ff"
GREEN   = "#3fb950"
ORANGE  = "#f78166"
PURPLE  = "#d2a8ff"
GOLD    = "#ffa657"
CYAN    = "#79c0ff"

def dark_style():
    plt.rcParams.update({
        "figure.facecolor" : DARK,
        "axes.facecolor"   : PANEL,
        "axes.edgecolor"   : BORDER,
        "axes.labelcolor"  : TXT,
        "axes.titlecolor"  : TXT,
        "xtick.color"      : TXT2,
        "ytick.color"      : TXT2,
        "text.color"       : TXT,
        "grid.color"       : BORDER,
        "grid.linewidth"   : 0.5,
        "font.family"      : "DejaVu Sans",
        "font.size"        : 11,
        "figure.dpi"       : 150,
    })

dark_style()

def save(name):
    plt.savefig(f"{OUT}/{name}", dpi=150, bbox_inches='tight',
                facecolor=DARK, edgecolor='none')
    plt.close()
    kb = os.path.getsize(f"{OUT}/{name}") // 1024
    print(f"  ✓  {name}  ({kb} KB)")

# ── Load rasters once ─────────────────────────────────────────────────────────
with rasterio.open(config.ROUTING_DEM_PATH) as src:
    dem_full = src.read(1).astype(np.float64)
    nodata   = src.nodata
    transform = src.transform
    cell_m   = abs(src.transform.a)

with rasterio.open(config.ROUTING_FLOW_DIR_PATH) as src:
    fdir_full = src.read(1)

with rasterio.open(config.ROUTING_FLOW_ACCUM_PATH) as src:
    faccum_full = src.read(1).astype(np.float64)

with rasterio.open(config.ROUTING_WATERSHED_MASK_PATH) as src:
    ws_full = src.read(1) > 0

# Cropped versions
dem     = crop(dem_full);     dem[dem == nodata] = np.nan
fdir_c  = crop(fdir_full)
faccum  = crop(faccum_full);  faccum[~crop(ws_full)] = np.nan
ws_mask = crop(ws_full)
EXTENT  = ws_extent(transform)   # (left, right, bottom, top)
EXT     = [EXTENT[0], EXTENT[1], EXTENT[2], EXTENT[3]]  # for imshow extent=

# Custom colormaps
TERRAIN_CM = LinearSegmentedColormap.from_list("terrain_dark",
    ["#1a3a2a","#2d5a3d","#4a7c5e","#7aaa80",
     "#b8c99a","#d4c68a","#c4a97a","#a08060","#c8c8c8","#ffffff"])
BLUES_CM   = LinearSegmentedColormap.from_list("fa_blues",
    ["#0d2b45","#1a4a6b","#1f6ea0","#2d9bd1","#56c0e8","#e8f8ff"])
RED_CM     = LinearSegmentedColormap.from_list("red_runoff",
    ["#161b22","#7a1515","#f78166","#ffd700"])

# Hillshade
ls = LightSource(azdeg=315, altdeg=35)
dem_n = (dem - np.nanmin(dem)) / (np.nanmax(dem) - np.nanmin(dem) + 1e-9)
shade = ls.hillshade(np.where(np.isnan(dem_n), 0, dem_n), vert_exag=3)
shade[~ws_mask] = np.nan

# Helper: format axis in km offset from centre
def km_ticks(ax):
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: f"{(x-EXTENT[0])/1000:.0f}"))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda y, _: f"{(y-EXTENT[2])/1000:.0f}"))
    ax.set_xlabel("Easting offset [km]", fontsize=9, color=TXT2)
    ax.set_ylabel("Northing offset [km]", fontsize=9, color=TXT2)
    ax.tick_params(labelsize=8, colors=TXT2)


# ─────────────────────────────────────────────────────────────────────────────
# Fig 01 — DEM hillshade   (wide landscape, right-panel use)
# ─────────────────────────────────────────────────────────────────────────────
print("Fig 01 — DEM hillshade")
fig, ax = plt.subplots(figsize=(6.5, 6.0))
ax.imshow(np.where(ws_mask, dem, np.nan), cmap=TERRAIN_CM,
          extent=EXT, origin='upper', aspect='equal', alpha=0.9)
ax.imshow(shade, cmap='gray', extent=EXT, origin='upper',
          aspect='equal', alpha=0.35)
cbar = fig.colorbar(
    plt.cm.ScalarMappable(cmap=TERRAIN_CM,
        norm=mcolors.Normalize(np.nanmin(dem), np.nanmax(dem))),
    ax=ax, fraction=0.035, pad=0.02)
cbar.set_label("Elevation [m]", color=TXT2, fontsize=8)
cbar.ax.tick_params(colors=TXT2, labelsize=7)
ax.set_title("Clipped DEM — Watershed Domain", fontsize=11,
             fontweight='bold', color=TXT, pad=8)
km_ticks(ax)
plt.tight_layout(pad=0.4)
save("01_dem_hillshade.png")

# ─────────────────────────────────────────────────────────────────────────────
# Fig 02 — Flow direction (cropped, right-panel use)
# ─────────────────────────────────────────────────────────────────────────────
print("Fig 02 — D8 flow direction")
D8_VALS  = [64,128,1,2,4,8,16,32]
D8_NAMES = ["N","NE","E","SE","S","SW","W","NW"]
fdir_idx = np.full_like(fdir_c, np.nan, dtype=float)
fdir_masked = np.where(ws_mask, fdir_c, -1)
for i, v in enumerate(D8_VALS):
    fdir_idx[fdir_masked == v] = i

fig, ax = plt.subplots(figsize=(6.5, 6.0))
cmap8 = plt.colormaps["Set1"].resampled(8)
im = ax.imshow(fdir_idx, cmap=cmap8, vmin=-0.5, vmax=7.5,
               extent=EXT, origin='upper', aspect='equal')
# mask outside watershed
mask_rgba = np.zeros((*ws_mask.shape, 4))
mask_rgba[~ws_mask, 3] = 1.0
mask_rgba[~ws_mask, :3] = np.array([0x0d,0x11,0x17])/255
ax.imshow(mask_rgba, extent=EXT, origin='upper', aspect='equal')
cbar = fig.colorbar(im, ax=ax, ticks=np.arange(8), fraction=0.035, pad=0.02)
cbar.ax.set_yticklabels(D8_NAMES, color=TXT2, fontsize=8)
cbar.ax.tick_params(colors=TXT2)
ax.set_title("D8 Flow Direction", fontsize=11, fontweight='bold', color=TXT, pad=8)
km_ticks(ax)
plt.tight_layout(pad=0.4)
save("02_flow_direction.png")

# ─────────────────────────────────────────────────────────────────────────────
# Fig 03 — Flow accumulation (cropped)
# ─────────────────────────────────────────────────────────────────────────────
print("Fig 03 — Flow accumulation")
faccum_log = np.log10(np.maximum(faccum, 1.0))

fig, ax = plt.subplots(figsize=(6.5, 6.0))
im = ax.imshow(faccum_log, cmap=BLUES_CM, extent=EXT,
               origin='upper', aspect='equal')
# mask outside
ax.imshow(mask_rgba, extent=EXT, origin='upper', aspect='equal')
cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
cbar.set_label("log₁₀(accum.) [cells]", color=TXT2, fontsize=8)
cbar.ax.tick_params(colors=TXT2, labelsize=7)
# Mark outlet
iy, ix = np.unravel_index(np.nanargmax(faccum), faccum.shape)
nrows_c, ncols_c = faccum.shape
ox = EXT[0] + (ix+0.5)*(EXT[1]-EXT[0])/ncols_c
oy = EXT[3] - (iy+0.5)*(EXT[3]-EXT[2])/nrows_c
ax.plot(ox, oy, 'o', color=ORANGE, markersize=9, zorder=5,
        markeredgecolor=DARK, markeredgewidth=1)
ax.annotate("Outlet", xy=(ox,oy),
            xytext=(ox+(EXT[1]-EXT[0])*0.12, oy+(EXT[3]-EXT[2])*0.08),
            color=ORANGE, fontsize=8,
            arrowprops=dict(arrowstyle='->', color=ORANGE, lw=1.5))
ax.set_title("Flow Accumulation (log scale)", fontsize=11,
             fontweight='bold', color=TXT, pad=8)
km_ticks(ax)
plt.tight_layout(pad=0.4)
save("03_flow_accumulation.png")

# ─────────────────────────────────────────────────────────────────────────────
# Fig 04 — Watershed overview: hillshade + boundary + hypsometry  (wide)
# ─────────────────────────────────────────────────────────────────────────────
print("Fig 04 — Watershed overview")
fig, axes = plt.subplots(1, 2, figsize=(13, 5.8),
                          gridspec_kw={'width_ratios':[1.05, 0.95]})
fig.patch.set_facecolor(DARK)

ax = axes[0]
ax.imshow(np.where(ws_mask, dem, np.nan), cmap=TERRAIN_CM,
          extent=EXT, origin='upper', aspect='equal', alpha=0.9)
ax.imshow(shade, cmap='gray', extent=EXT, origin='upper',
          aspect='equal', alpha=0.32)
ax.imshow(mask_rgba, extent=EXT, origin='upper', aspect='equal')
# watershed outline
ws_float = np.where(ws_mask, 1.0, 0.0).astype(float)
ax.contour(ws_float, levels=[0.5], colors=[BLUE], linewidths=[2],
           extent=EXT, origin='upper')
cell_count = ws_mask.sum()
area_km2   = cell_count * cell_m**2 / 1e6
ax.text(0.03, 0.97,
        f"Cells: {cell_count:,}\nArea: {area_km2:.1f} km²\n"
        f"Δx = {cell_m:.0f} m",
        transform=ax.transAxes, fontsize=9, color=TXT, va='top',
        bbox=dict(facecolor=PANEL, edgecolor=BLUE, pad=4, alpha=0.9))
ax.set_title("Delineated Watershed", fontsize=12, fontweight='bold',
             color=TXT, pad=8)
km_ticks(ax)

ax2 = axes[1]
valid = dem[ws_mask].flatten()
ax2.hist(valid, bins=55, color=BLUE, edgecolor=DARK, linewidth=0.4, alpha=0.85)
mu, sig = np.nanmean(valid), np.nanstd(valid)
ax2.axvline(mu, color=ORANGE, lw=2, ls='--', label=f"Mean {mu:.0f} m")
ax2.axvline(mu-sig, color=PURPLE, lw=1.5, ls=':', alpha=0.8)
ax2.axvline(mu+sig, color=PURPLE, lw=1.5, ls=':', alpha=0.8,
            label=f"±1σ = {sig:.0f} m")
ax2.set_xlabel("Elevation [m a.s.l.]", fontsize=10, color=TXT)
ax2.set_ylabel("Cell Count", fontsize=10, color=TXT)
ax2.set_title("Hypsometric Distribution", fontsize=12,
              fontweight='bold', color=TXT, pad=8)
ax2.legend(fontsize=9, facecolor=PANEL, edgecolor=BORDER, labelcolor=TXT)
ax2.grid(True, alpha=0.25)
ax2.tick_params(colors=TXT2, labelsize=9)

plt.tight_layout(pad=0.5)
save("04_watershed_topo.png")

# ─────────────────────────────────────────────────────────────────────────────
# Fig 05 — Hydrograph  (wide, 16:9-friendly)
# ─────────────────────────────────────────────────────────────────────────────
print("Fig 05 — Hydrograph")
hyd  = pd.read_csv("output/hydrograph.csv")
t_hr = hyd["time_hr"].values
Q    = hyd["Q_m3s"].values
peak_Q = Q.max();  peak_t = t_hr[Q.argmax()]

fig, ax = plt.subplots(figsize=(13, 5.2))
ax.fill_between(t_hr, Q, alpha=0.15, color=BLUE)
ax.plot(t_hr, Q, color=BLUE, lw=2.5, label="Q_outlet [m³/s]")
ax.axvline(3.0, color=ORANGE, lw=1.5, ls='--', alpha=0.85, label="Rain end (3 h)")
ax.axvspan(0, 3.0, alpha=0.06, color=BLUE)
ax.plot(peak_t, peak_Q, 'o', color=ORANGE, ms=8, zorder=6)
ax.annotate(f"Peak: {peak_Q:.0f} m³/s\n@ t = {peak_t:.1f} h",
            xy=(peak_t, peak_Q), xytext=(peak_t-2.5, peak_Q*0.88),
            fontsize=9, color=ORANGE,
            arrowprops=dict(arrowstyle='->', color=ORANGE, lw=1.5))
ax.text(1.5, peak_Q*0.12, "Rising limb\n(VSA expansion)", fontsize=8.5,
        color=GREEN, ha='center')
ax.text(10.5, peak_Q*0.45, "Recession", fontsize=8.5, color=PURPLE, ha='center')
ax.set_xlabel("Simulation Time [hours]", fontsize=11)
ax.set_ylabel("Discharge Q [m³/s]", fontsize=11)
ax.set_title("Outlet Hydrograph — VSA-OPM Kinematic Wave Routing  "
             "(Thiessen precip · Manning n = 0.09 · Δt = 5 s)",
             fontsize=11, fontweight='bold', color=TXT)
ax.legend(fontsize=9, facecolor=PANEL, edgecolor=BORDER, labelcolor=TXT)
ax.grid(True, alpha=0.2); ax.set_xlim(0, t_hr.max()); ax.set_ylim(bottom=0)
ax.tick_params(labelsize=9, colors=TXT2)
plt.tight_layout(pad=0.5)
save("05_hydrograph.png")

# ─────────────────────────────────────────────────────────────────────────────
# Fig 06 — VSA evolution  (4-panel, wide)
# ─────────────────────────────────────────────────────────────────────────────
print("Fig 06 — VSA evolution")
vsa     = pd.read_csv("output/vsa_opm_results.csv")
t_vsa   = vsa["time_s"].values / 3600.0
SD_max  = vsa["SD_max_t"].values
At_m2   = vsa["A_t_m2"].values
VSA_km2 = vsa["VSA_m2"].values / 1e6

fig, axes = plt.subplots(1, 4, figsize=(16, 4.2))
fig.patch.set_facecolor(DARK)
plt.subplots_adjust(wspace=0.38, left=0.06, right=0.98, top=0.88, bottom=0.14)

# 1. SD_max
ax = axes[0]
ax.fill_between(t_vsa, SD_max*1e3, alpha=0.2, color=PURPLE)
ax.plot(t_vsa, SD_max*1e3, color=PURPLE, lw=2)
ax.axhline(1.0, color=ORANGE, ls='--', lw=1.2, alpha=0.7, label="SD_min")
ax.set_xlabel("Time [h]", fontsize=9); ax.set_ylabel("SD_max [mm]", fontsize=9)
ax.set_title("Max Soil Deficit SD_max(t)", fontsize=9.5, fontweight='bold', color=TXT)
ax.legend(fontsize=8, facecolor=PANEL, edgecolor=BORDER, labelcolor=TXT)
ax.grid(True, alpha=0.2); ax.set_ylim(0); ax.tick_params(labelsize=8, colors=TXT2)

# 2. A_t (log)
ax = axes[1]
ax.semilogy(t_vsa, At_m2, color=GREEN, lw=2)
ax.fill_between(t_vsa, At_m2, alpha=0.15, color=GREEN)
ax.set_xlabel("Time [h]", fontsize=9); ax.set_ylabel("A_t [m²]", fontsize=9)
ax.set_title("Threshold Area A_t(t) — log", fontsize=9.5, fontweight='bold', color=TXT)
ax.grid(True, alpha=0.2, which='both'); ax.tick_params(labelsize=8, colors=TXT2)

# 3. VSA area
ax = axes[2]
ax.fill_between(t_vsa, VSA_km2, alpha=0.2, color=BLUE)
ax.plot(t_vsa, VSA_km2, color=BLUE, lw=2)
ax.axvline(3.0, color=ORANGE, lw=1.5, ls='--', alpha=0.7, label="Rain stop")
ax.set_xlabel("Time [h]", fontsize=9); ax.set_ylabel("VSA [km²]", fontsize=9)
ax.set_title("Variable Source Area VSA(t)", fontsize=9.5, fontweight='bold', color=TXT)
ax.legend(fontsize=8, facecolor=PANEL, edgecolor=BORDER, labelcolor=TXT)
ax.grid(True, alpha=0.2); ax.set_ylim(0); ax.tick_params(labelsize=8, colors=TXT2)

# 4. Phase diagram
ax = axes[3]
sc = ax.scatter(SD_max*1e3, VSA_km2, c=t_vsa, cmap='plasma', s=25, zorder=5)
cb = fig.colorbar(sc, ax=ax, pad=0.02)
cb.set_label("Time [h]", color=TXT2, fontsize=8); cb.ax.tick_params(colors=TXT2, labelsize=7)
ax.set_xlabel("SD_max [mm]", fontsize=9); ax.set_ylabel("VSA [km²]", fontsize=9)
ax.set_title("Phase: VSA vs SD_max", fontsize=9.5, fontweight='bold', color=TXT)
ax.invert_xaxis(); ax.grid(True, alpha=0.2); ax.tick_params(labelsize=8, colors=TXT2)

fig.suptitle("OPM State Variables — Pradhan & Ogden (2010)  "
             f"[SD_max₀=100 mm · Q_max=0.5 m³/s · φ=0.35 · K=44 m/day]",
             fontsize=10.5, fontweight='bold', color=TXT, y=0.99)
save("06_vsa_evolution.png")

# ─────────────────────────────────────────────────────────────────────────────
# Fig 07 — Sandbox schematic  (landscape)
# ─────────────────────────────────────────────────────────────────────────────
print("Fig 07 — Sandbox schematic")
fig, ax = plt.subplots(figsize=(13, 5.0))
ax.set_facecolor(DARK); ax.set_xlim(0, 13); ax.set_ylim(-0.8, 5.5)
ax.axis('off')
ax.set_title("OPM Sandbox (Hillslope Column) — Darcy Drainage + Water Table Rise  [Eq. 12]",
             fontsize=12, fontweight='bold', color=TXT, pad=10)

# Sky
sky = mpatches.FancyBboxPatch((0,4.1),13,1.4,boxstyle="square,pad=0",
      facecolor="#0d2b3e",edgecolor='none'); ax.add_patch(sky)
# Soil block (trapezoid: left side higher)
xs=[1,12,12,1]; ys=[3.8,1.5,-0.8,-0.8]
ax.fill(xs,ys,color="#3a2010",alpha=0.85,zorder=2)
ax.plot(xs+[xs[0]],ys+[ys[0]],color="#5a3820",lw=1.5,zorder=3)
# Ground surface
ax.plot([1,12],[3.8,1.5],color="#6aaa50",lw=3.5,zorder=4)
# Saturated zone
z_h = 1.05
wt_xs=[1,12,12,1]; wt_ys=[3.8-z_h,1.5-z_h,-0.8,-0.8]
ax.fill(wt_xs,wt_ys,color="#1a4a8a",alpha=0.60,zorder=3)
ax.plot([1,12],[3.8-z_h,1.5-z_h],color=BLUE,lw=2.5,zorder=5)
# z(t) brace
ax.annotate("",xy=(12.4,1.5-z_h),xytext=(12.4,1.5),
            arrowprops=dict(arrowstyle='<->',color=BLUE,lw=2))
ax.text(12.55,1.5-z_h/2,"z(t)",fontsize=10,color=BLUE,va='center',fontweight='bold')
# SD_max brace
ax.annotate("",xy=(0.5,3.8-z_h),xytext=(0.5,3.8),
            arrowprops=dict(arrowstyle='<->',color=PURPLE,lw=2))
ax.text(-0.05,3.8-z_h/2,"SD_max(t)",fontsize=8.5,color=PURPLE,
        va='center',ha='right',fontweight='bold')
# Zone labels
ax.text(6.5,2.9,"Unsaturated Zone  (vadose / capillary fringe)",
        ha='center',fontsize=9.5,color=TXT,alpha=0.9,zorder=6,
        bbox=dict(facecolor=PANEL,edgecolor=BORDER,pad=3,alpha=0.8))
ax.text(6.5,0.3,"Saturated Zone  —  z(t) rises as rainfall infiltrates",
        ha='center',fontsize=9,color=BLUE,zorder=6)
# Rain arrows
for xp in [2.5,4.2,6.0,7.8,9.5,11.0]:
    frac = (xp-1)/11.0; yb = 3.8 - frac*2.3
    ax.annotate("",xy=(xp,yb),xytext=(xp,yb+0.75),
                arrowprops=dict(arrowstyle='->',color=CYAN,lw=2.0,mutation_scale=14))
ax.text(6.5,5.0,"P  [m/s]  Precipitation at divide cell",
        ha='center',fontsize=10,color=CYAN,fontweight='bold',zorder=7)
# Darcy arrow
ax.annotate("",xy=(0.2,0.4),xytext=(2.0,0.4),
            arrowprops=dict(arrowstyle='->',color=GREEN,lw=2.5,mutation_scale=18))
ax.text(0.1,0.85,"q_b = K·i·z·b\n[m³/s]",fontsize=9,color=GREEN,fontweight='bold')
ax.text(0.1,-0.05,"Darcy lateral\noutflow",fontsize=7.5,color=GREEN,alpha=0.8)
# Slope indicator
ax.plot([1,12],[3.8,1.5],'--',color=TXT2,lw=0.8,alpha=0.5)
ax.text(9.5,2.4,"slope  i",fontsize=8.5,color=TXT2,rotation=-12,alpha=0.8)
# Labels
ax.text(0.8,-0.6,"← Divide",fontsize=8.5,color=TXT2)
ax.text(10.5,-0.6,"Outlet →",fontsize=8.5,color=TXT2)

plt.tight_layout(pad=0.3)
save("07_sandbox_schematic.png")

# ─────────────────────────────────────────────────────────────────────────────
# Fig 08 — A_t sensitivity + VSA fraction  (wide, 2-panel)
# ─────────────────────────────────────────────────────────────────────────────
print("Fig 08 — A_t sensitivity")
SD_MIN_v=0.001; Q_MIN_v=0.001
Q_max_v  = float(config.VSA_Q_MAX)
SD_max_0 = float(config.VSA_SD_MAX_INITIAL)
faccum_ws = np.where(crop(ws_full), faccum_full[R0:R1,C0:C1], 0)
A_outlet  = float(faccum_ws.max()) * cell_m**2
A_1_v     = cell_m**2
A_t_i     = A_outlet/(1-math.log(Q_MIN_v/Q_max_v))
Rf0       = SD_MIN_v/SD_max_0
H_a       = (A_t_i/(A_t_i-A_1_v))*math.log(Rf0)

SD_sw = np.linspace(SD_MIN_v*1.005, SD_max_0, 500)
Rf_sw = SD_MIN_v/SD_sw
den   = H_a - np.log(Rf_sw)
At_sw = np.where(np.abs(den)>1e-12, H_a*A_1_v/den, A_t_i)
At_sw = np.clip(At_sw, A_1_v, A_outlet)

fig, axes = plt.subplots(1,2,figsize=(13,5.0))
fig.patch.set_facecolor(DARK)

ax = axes[0]
ax.plot(SD_sw*1e3, At_sw/1e6, color=GREEN, lw=2.5)
ax.fill_between(SD_sw*1e3, At_sw/1e6, alpha=0.15, color=GREEN)
ax.scatter([SD_max_0*1e3],[A_t_i/1e6],color=ORANGE,s=90,zorder=6,
           label=f"Initial: A_t={A_t_i/1e6:.1f} km²")
ax.axhline(A_1_v/1e6, color=PURPLE, ls='--', lw=1.2, alpha=0.7,
           label=f"A₁ = {A_1_v:.0f} m² (single cell)")
# Arrow showing storm direction
mid = len(SD_sw)//3
ax.annotate("",xy=(SD_sw[mid//2]*1e3,At_sw[mid//2]/1e6),
            xytext=(SD_sw[mid]*1e3,At_sw[mid]/1e6),
            arrowprops=dict(arrowstyle='->',color=GREEN,lw=2))
ax.text(SD_sw[mid]*1e3*1.05, At_sw[mid]/1e6*0.55,
        "Storm →\n(soil filling)", fontsize=8, color=GREEN, alpha=0.9)
ax.set_xlabel("SD_max [mm]", fontsize=10); ax.set_ylabel("A_t [km²]", fontsize=10)
ax.set_title("Eq. 5 — A_t as Function of SD_max", fontsize=11,
             fontweight='bold', color=TXT)
ax.legend(fontsize=8.5, facecolor=PANEL, edgecolor=BORDER, labelcolor=TXT)
ax.grid(True, alpha=0.2); ax.set_xlim(0); ax.tick_params(labelsize=9, colors=TXT2)

ax2 = axes[1]
color_map = plt.cm.plasma(np.linspace(0.15,0.92,len(t_vsa)))
for i in range(len(t_vsa)-1):
    ax2.plot(t_vsa[i:i+2], VSA_km2[i:i+2]/VSA_km2.max()*100,
             color=color_map[i], lw=2.5)
ax2.axvline(3.0, color=ORANGE, lw=1.5, ls='--', alpha=0.8, label="Rain stop")
sm = plt.cm.ScalarMappable(cmap='plasma',
     norm=mcolors.Normalize(0, t_vsa.max()))
cb = fig.colorbar(sm, ax=ax2, pad=0.02)
cb.set_label("Time [h]", color=TXT2, fontsize=8); cb.ax.tick_params(colors=TXT2, labelsize=7)
ax2.set_xlabel("Simulation Time [h]", fontsize=10)
ax2.set_ylabel("VSA / Total Watershed [%]", fontsize=10)
ax2.set_title("Dynamic VSA Coverage (% of Watershed)", fontsize=11,
              fontweight='bold', color=TXT)
ax2.legend(fontsize=8.5, facecolor=PANEL, edgecolor=BORDER, labelcolor=TXT)
ax2.grid(True, alpha=0.2); ax2.set_ylim(0,105); ax2.set_xlim(0)
ax2.tick_params(labelsize=9, colors=TXT2)

plt.tight_layout(pad=0.5)
save("08_at_sensitivity.png")

# ─────────────────────────────────────────────────────────────────────────────
# Fig 09 — VSA mask concept  (3-panel matrix operation)
# ─────────────────────────────────────────────────────────────────────────────
print("Fig 09 — VSA mask concept")
np.random.seed(42)
N=8
up_g = np.random.rand(N,N)*1e6
A_t_d = 4.5e5
pre_g = np.random.uniform(6,14,(N,N))
vsa_b = (up_g > A_t_d).astype(float)
run_g = pre_g*vsa_b

P_CM = LinearSegmentedColormap.from_list("p",["#0d2b45","#1f6ea0","#79c0ff"])
V_CM = LinearSegmentedColormap.from_list("v",["#1a1a2e","#1a4a8a","#58a6ff"])
R_CM = LinearSegmentedColormap.from_list("r",["#1a1a1a","#7a1515","#f78166"])

def annotate_g(ax, data, fmt):
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            ax.text(j, i, fmt.format(data[i,j]), ha='center', va='center',
                    fontsize=8, color=TXT, fontweight='bold')

fig, axes = plt.subplots(1, 3, figsize=(13, 5.2),
                          gridspec_kw={'wspace':0.08})
fig.patch.set_facecolor(DARK)
fig.text(0.36, 0.50, "×", ha='center', va='center',
         fontsize=46, color=TXT, fontweight='bold', transform=fig.transFigure)
fig.text(0.645, 0.50, "=", ha='center', va='center',
         fontsize=46, color=TXT, fontweight='bold', transform=fig.transFigure)

im1 = axes[0].imshow(pre_g, cmap=P_CM, vmin=0, aspect='equal')
annotate_g(axes[0], pre_g, "{:.1f}")
axes[0].set_title("P(i,j)  [mm/hr]\nPrecipitation Field",
                  fontsize=10, fontweight='bold', color=TXT)
fig.colorbar(im1, ax=axes[0], fraction=0.04, pad=0.02).ax.tick_params(colors=TXT2, labelsize=7)
axes[0].set_xticks([]); axes[0].set_yticks([])

im2 = axes[1].imshow(vsa_b, cmap=V_CM, vmin=0, vmax=1, aspect='equal')
annotate_g(axes[1], vsa_b, "{:.0f}")
axes[1].set_title(f"VSA Mask M(i,j) ∈ {{0,1}}\nA_t = {A_t_d/1e3:.0f} × 10³ m²",
                  fontsize=10, fontweight='bold', color=TXT)
fig.colorbar(im2, ax=axes[1], fraction=0.04, pad=0.02).ax.tick_params(colors=TXT2, labelsize=7)
p0 = mpatches.Patch(color='#1a1a2e', label='Unsaturated (0)')
p1 = mpatches.Patch(color=BLUE, label='VSA — saturated (1)')
axes[1].legend(handles=[p0,p1], fontsize=7, loc='lower right',
               facecolor=PANEL, edgecolor=BORDER, labelcolor=TXT)
axes[1].set_xticks([]); axes[1].set_yticks([])

im3 = axes[2].imshow(run_g, cmap=R_CM, vmin=0, aspect='equal')
annotate_g(axes[2], run_g, "{:.1f}")
axes[2].set_title("Q_eff(i,j) = P × M  [mm/hr]\nDirect Runoff (VSA cells only)",
                  fontsize=10, fontweight='bold', color=TXT)
fig.colorbar(im3, ax=axes[2], fraction=0.04, pad=0.02).ax.tick_params(colors=TXT2, labelsize=7)
axes[2].set_xticks([]); axes[2].set_yticks([])

fig.suptitle("VSA Matrix Operation — Effective Runoff = Precipitation × Binary VSA Mask",
             fontsize=11.5, fontweight='bold', color=TXT, y=1.01)
plt.tight_layout(pad=0.4)
save("09_vsa_mask_concept.png")

# ─────────────────────────────────────────────────────────────────────────────
# Fig 10 — System pipeline  (very wide)
# ─────────────────────────────────────────────────────────────────────────────
print("Fig 10 — System pipeline")
fig, ax = plt.subplots(figsize=(14, 3.8))
ax.set_facecolor(DARK); ax.set_xlim(0,14); ax.set_ylim(0,4)
ax.axis('off')

boxes = [
    (1.2,  "process_dem.py\n──────────────\nDEM ingest · fill sinks\nD8 flow direction\nFlow accumulation\nWatershed mask",  PURPLE),
    (3.8,  "precip_input.py\n───────────────\nPrecipEngine\nUniform / Thiessen\nIDW weights\n→ rain_1d [m/s]",               BLUE),
    (6.4,  "runoff_input.py\n───────────────\nRunoffEngine\nSandbox Eq.12\nA_t(t) Eq.5\nVSA mask [0/1]",                     GREEN),
    (9.0,  "kinematic_wave\n_router.py\n───────────────\nTopo order\nManning Q_out\nCFL limiter",                              ORANGE),
    (11.8, "Output\n─────────────\nHydrograph CSV\nAnimation GIF\nVSA results",                                               GOLD),
]
BW, BH = 2.2, 3.3
for (xc, lbl, clr) in boxes:
    ax.add_patch(mpatches.FancyBboxPatch((xc-BW/2,0.35),BW,BH,
        boxstyle="round,pad=0.10",linewidth=2,edgecolor=clr,facecolor=PANEL,zorder=3))
    ax.add_patch(mpatches.FancyBboxPatch((xc-BW/2,BH+0.25),BW,0.38,
        boxstyle="round,pad=0.04",linewidth=0,edgecolor='none',
        facecolor=clr,alpha=0.30,zorder=4))
    ax.text(xc, 2.0, lbl, ha='center', va='center', fontsize=8.2,
            color=TXT, zorder=5, linespacing=1.5)

arrs = [(2.31,2.69),(4.91,5.29),(7.51,7.89),(10.11,10.69)]
lbls = ["rasters", "rain_1d\n[m/s]", "source_1d\n[m/s]", "hydrogr."]
for (x0,x1),lb in zip(arrs,lbls):
    ax.annotate("",xy=(x1,2.0),xytext=(x0,2.0),
                arrowprops=dict(arrowstyle='->',color=TXT2,lw=1.8,mutation_scale=14),zorder=5)
    ax.text((x0+x1)/2, 2.35, lb, ha='center', fontsize=7.5, color=TXT2)

ax.text(6.4, 0.12,
        "Modes:  'none'  ·  'coefficient'  ·  'raster'  ·  'scs_cn'  ·  'physical'",
        ha='center', fontsize=8, color=GREEN, alpha=0.9)
ax.set_title("End-to-End Processing Pipeline",
             fontsize=12, fontweight='bold', color=TXT, pad=6)
plt.tight_layout(pad=0.3)
save("10_system_pipeline.png")

# ─────────────────────────────────────────────────────────────────────────────
# Fig 11 — DEM + flow accum side-by-side  (for DEM slide, both cropped)
# ─────────────────────────────────────────────────────────────────────────────
print("Fig 11 — DEM + accum pair")
fig, axes = plt.subplots(1, 2, figsize=(13, 5.8))
fig.patch.set_facecolor(DARK)

ax = axes[0]
ax.imshow(np.where(ws_mask, dem, np.nan), cmap=TERRAIN_CM,
          extent=EXT, origin='upper', aspect='equal', alpha=0.9)
ax.imshow(shade, cmap='gray', extent=EXT, origin='upper',
          aspect='equal', alpha=0.32)
ax.imshow(mask_rgba, extent=EXT, origin='upper', aspect='equal')
ax.contour(ws_float, levels=[0.5], colors=[BLUE], linewidths=[1.8],
           extent=EXT, origin='upper')
ax.set_title("Hillshade DEM (watershed)", fontsize=11,
             fontweight='bold', color=TXT, pad=8)
km_ticks(ax)

ax2 = axes[1]
im2 = ax2.imshow(faccum_log, cmap=BLUES_CM, extent=EXT,
                 origin='upper', aspect='equal')
ax2.imshow(mask_rgba, extent=EXT, origin='upper', aspect='equal')
ax2.plot(ox, oy, 'o', color=ORANGE, ms=8, zorder=5,
         markeredgecolor=DARK, markeredgewidth=1, label="Outlet")
ax2.legend(fontsize=8, facecolor=PANEL, edgecolor=BORDER, labelcolor=TXT)
fig.colorbar(im2, ax=ax2, fraction=0.035, pad=0.02,
             label="log₁₀(cells)").ax.tick_params(colors=TXT2, labelsize=7)
ax2.set_title("Flow Accumulation (log scale)", fontsize=11,
              fontweight='bold', color=TXT, pad=8)
km_ticks(ax2)

plt.tight_layout(pad=0.5)
save("11_dem_accum_pair.png")

# ─────────────────────────────────────────────────────────────────────────────
# Fig 12 — UNCLIPPED flow direction (full raster extent)
# ─────────────────────────────────────────────────────────────────────────────
print("Fig 12 — Flow direction (unclipped, full raster)")

# Full-raster geographic extent
nrows_f, ncols_f = fdir_full.shape
EXT_FULL = [
    transform.c,
    transform.c + ncols_f * transform.a,
    transform.f + nrows_f * transform.e,   # bottom (e < 0)
    transform.f,                            # top
]

D8_VALS  = [64, 128, 1, 2, 4, 8, 16, 32]
D8_NAMES = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
cmap8 = plt.colormaps["Set1"].resampled(8)

fdir_idx_full = np.full(fdir_full.shape, np.nan, dtype=float)
for i, v in enumerate(D8_VALS):
    fdir_idx_full[fdir_full == v] = i

fig, ax = plt.subplots(figsize=(9, 9))
im = ax.imshow(fdir_idx_full, cmap=cmap8, vmin=-0.5, vmax=7.5,
               extent=EXT_FULL, origin='upper', aspect='equal',
               interpolation='nearest')

# Watershed outline on top
ws_float_full = ws_full.astype(float)
ax.contour(ws_float_full, levels=[0.5], colors=[ORANGE],
           linewidths=[2.0], extent=EXT_FULL, origin='upper')
ax.text(0.02, 0.97, "Watershed\nboundary", transform=ax.transAxes,
        fontsize=9, color=ORANGE, va='top',
        bbox=dict(facecolor=PANEL, edgecolor=ORANGE, pad=3, alpha=0.85))

# Inset box showing watershed crop region
crop_left   = transform.c + C0 * transform.a
crop_right  = transform.c + C1 * transform.a
crop_top    = transform.f + R0 * transform.e
crop_bottom = transform.f + R1 * transform.e
rect = mpatches.Rectangle(
    (crop_left, crop_bottom),
    crop_right - crop_left, crop_top - crop_bottom,
    linewidth=2, edgecolor=CYAN, facecolor='none',
    linestyle='--', zorder=5
)
ax.add_patch(rect)
ax.text(crop_right + (EXT_FULL[1]-EXT_FULL[0])*0.01, (crop_top+crop_bottom)/2,
        "Cropped\nregion", fontsize=8, color=CYAN, va='center',
        bbox=dict(facecolor=PANEL, edgecolor=CYAN, pad=2, alpha=0.8))

cbar = fig.colorbar(im, ax=ax, ticks=np.arange(8),
                    fraction=0.03, pad=0.02, shrink=0.75)
cbar.ax.set_yticklabels(D8_NAMES, color=TXT2, fontsize=8)
cbar.ax.tick_params(colors=TXT2)
cbar.set_label("Flow direction", color=TXT2, fontsize=8)

ax.set_title("D8 Flow Direction — Full Raster Extent\n"
             "(orange = watershed boundary · cyan dashed = crop window used in other figures)",
             fontsize=11, fontweight='bold', color=TXT, pad=8)
ax.set_xlabel("Easting [m]", fontsize=9, color=TXT2)
ax.set_ylabel("Northing [m]", fontsize=9, color=TXT2)
ax.ticklabel_format(style='sci', axis='both', scilimits=(5, 5))
ax.tick_params(labelsize=8, colors=TXT2)

plt.tight_layout(pad=0.5)
save("12_flow_dir_unclipped.png")

# ─────────────────────────────────────────────────────────────────────────────
# Fig 13 — UNCLIPPED flow accumulation from output/flow_accumulation.tif
# ─────────────────────────────────────────────────────────────────────────────
print("Fig 13 — Flow accumulation (unclipped, output/flow_accumulation.tif)")

with rasterio.open("output/flow_accumulation.tif") as src:
    fa_unc     = src.read(1).astype(np.float64)
    fa_nd      = src.nodata
    fa_tr      = src.transform
    fa_nrows, fa_ncols = fa_unc.shape

# Replace nodata with NaN; mask zeros (no upstream area)
if fa_nd is not None:
    fa_unc[fa_unc == fa_nd] = np.nan
fa_unc[fa_unc <= 0] = np.nan

fa_log = np.log10(np.maximum(fa_unc, 1.0))

# Geographic extent of this raster
fa_ext = [
    fa_tr.c,
    fa_tr.c + fa_ncols * fa_tr.a,
    fa_tr.f + fa_nrows * fa_tr.e,   # bottom
    fa_tr.f,                         # top
]

fig, ax = plt.subplots(figsize=(9, 9))
im = ax.imshow(fa_log, cmap=BLUES_CM,
               extent=fa_ext, origin='upper', aspect='equal',
               interpolation='nearest')

# Watershed boundary (reproject ws_full to this raster's grid — same grid assumed)
ax.contour(ws_full.astype(float), levels=[0.5], colors=[ORANGE],
           linewidths=[2.0], extent=fa_ext, origin='upper')

# Mark outlet (cell with maximum accumulation)
iy_u, ix_u = np.unravel_index(np.nanargmax(fa_unc), fa_unc.shape)
ox_u = fa_ext[0] + (ix_u + 0.5) * (fa_ext[1] - fa_ext[0]) / fa_ncols
oy_u = fa_ext[3] - (iy_u + 0.5) * (fa_ext[3] - fa_ext[2]) / fa_nrows
ax.plot(ox_u, oy_u, 'o', color=ORANGE, ms=10, zorder=6,
        markeredgecolor=DARK, markeredgewidth=1.5)
ax.annotate("Outlet", xy=(ox_u, oy_u),
            xytext=(ox_u + (fa_ext[1]-fa_ext[0])*0.06,
                    oy_u + (fa_ext[3]-fa_ext[2])*0.04),
            color=ORANGE, fontsize=9, fontweight='bold',
            arrowprops=dict(arrowstyle='->', color=ORANGE, lw=1.8))

cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02, shrink=0.80)
cbar.set_label("log₁₀(flow accumulation) [cells]", color=TXT2, fontsize=9)
cbar.ax.tick_params(colors=TXT2, labelsize=8)

leg_handles = [
    mpatches.Patch(color=ORANGE, label="Watershed boundary"),
    mpatches.Patch(color='none',  label=f"Raster: {fa_nrows}×{fa_ncols} cells"),
]
ax.legend(handles=leg_handles, fontsize=8, loc='lower right',
          facecolor=PANEL, edgecolor=BORDER, labelcolor=TXT)

ax.set_title("Flow Accumulation — Unclipped Full Raster\n"
             "source: output/flow_accumulation.tif  (log₁₀ scale)",
             fontsize=11, fontweight='bold', color=TXT, pad=10)
ax.set_xlabel("Easting [m]", fontsize=9, color=TXT2)
ax.set_ylabel("Northing [m]", fontsize=9, color=TXT2)
ax.ticklabel_format(style='sci', axis='both', scilimits=(5, 5))
ax.tick_params(labelsize=8, colors=TXT2)

plt.tight_layout(pad=0.5)
save("13_flow_accum_unclipped.png")

print("\nAll figures written to output/figures/")
for f in sorted(os.listdir(OUT)):
    kb = os.path.getsize(f"{OUT}/{f}")//1024
    print(f"  {f:45s}  {kb:4d} KB")
