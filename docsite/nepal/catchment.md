# Catchment numbers from the DEM

Every official Nepali formula starts from a few numbers that describe the
catchment: its area, the part of it below 3,000 m, the snow area, the length
and slope of its longest flow path. In practice these numbers are measured by
hand in a GIS, and small differences between two people's measurements turn into
differences in the design flood. MRRpy-Nepal measures all of them from the DEM
in the same way every time, with `MRRpy.nepal.measure_catchment`. You can also
type them in.

## The numbers and who uses them

| Number | Symbol | Unit | Used by |
|---|---|---|---|
| Total catchment area | $A$ | km² | MHSP 1997, Modified Dickens, specific discharge, Rational, area ratio, comparison formulas, monthly flows |
| Area below 3,000 m | $A_{3000}$ | km² | WECS/DHM 1990, DHM 2004, the `wecs_nepal` / `dhm2004_nepal` bankfull presets |
| Area below 5,000 m | $A_{5000}$ | km² | WECS/DHM monthly flows |
| Permanent-snow area | $a$ | km² | Modified Dickens (the snow term in $p$) |
| Longest flow path | $L$ | km | Kirpich time of concentration (Rational method), length of the physics run |
| Slope of the longest flow path | $S$ | m/m | Kirpich time of concentration |
| Slope between 10 % and 85 % of $L$ | $S_{10\text{–}85}$ | m/m | reported only (some manuals use it instead of $S$) |
| Distance to the centroid | $L_c$ | km | reported only (Snyder-type lag formulas) |
| Lowest, mean, highest elevation | $z_{min}$, $\bar z$, $z_{max}$ | m | river class (warnings) |
| Outlet position | lat, lon; $x$, $y$ | °; m | where the design-storm rain gauge is placed |

## How each number is measured

`measure_catchment(source)` reads the four rasters written by the
[`process_dem`](../manual/terrain.md) stage: `clipped_dem.tif`,
`flow_direction.tif` (D8), `clipped_flow_accumulation.tif` and `watershed.tif`.
`source` can be a results folder, a config file (its [[OUTPUT_DIR]] is used) or
a `Config` object.

**1. Order the cells.** The watershed cells are put in upstream-first order
(the same topological order the router uses). The **outlet** is the cell with
the largest flow accumulation. In a whole-DEM run, which has many exits, this is
the main exit, so it is that exit's catchment that gets measured.

**2. Distance along the flow.** Every cell gets its distance to the outlet,
following the D8 directions. Starting at the outlet ($d = 0$), one pass goes
upstream:

$$
d_i = d_{j} + \Delta_i, \qquad
\Delta_i = \begin{cases} \Delta x & \text{cardinal step (N, E, S, W)}\\
\sqrt{2}\,\Delta x & \text{diagonal step} \end{cases}
$$

where $j$ is the downstream neighbour of cell $i$ and $\Delta x$ the cell size
(m). A cell is part of the catchment only if its chain of downstream neighbours
reaches the outlet.

**3. Areas.** Each cell covers $\Delta x^2$, so with $N$ the number of
catchment cells:

$$
A = \frac{N\,\Delta x^2}{10^6}, \quad
A_{3000} = \frac{N_{z<3000}\,\Delta x^2}{10^6}, \quad
A_{5000} = \frac{N_{z<5000}\,\Delta x^2}{10^6}, \quad
a = \frac{N_{z\ge 5000}\,\Delta x^2}{10^6}
$$

in km². "Below 3,000 m" means a cell elevation strictly under 3,000 m. The
permanent-snow area is taken to be the area at or above 5,000 m. That is a
simplification of real glacier and snow maps, and the
[Modified Dickens](regional-formulas.md#modified-dickens) notes say so.

**4. Longest flow path.** $L$ is the largest $d_i$, the distance from the cell
farthest upstream (along the flow, not in a straight line) to the outlet. The
path is then traced down cell by cell.

**5. Slope of the longest flow path.** The fall over the length:

$$
S = \frac{z_{start} - z_{outlet}}{L}
$$

with $z$ from `clipped_dem.tif`, the filled DEM that the model routes on.

**6. 10–85 slope.** The elevations at 10 % and 85 % of $L$, measured from the
outlet and interpolated linearly along the path, give

$$
S_{10\text{–}85} = \frac{z_{85} - z_{10}}{0.75\,L}
$$

which leaves out the steep head and the flat reach near the outlet.

**7. Distance to the centroid.** The centroid is the mean $(x, y)$ of the
catchment cells. $L_c$ is the distance along the longest path from the outlet to
the path cell nearest the centroid.

**8. The rest.** The minimum, mean and maximum of the catchment elevations, the
outlet's latitude and longitude, its map coordinates (used to place the
design-storm gauge) and the CRS.

!!! example "Measured: the small test basin"
    The synthetic 30 × 30-cell valley (30 m cells) in MRRpy's test suite,
    delineated and measured:

    | Quantity | Value |
    |---|---|
    | A, A₃₀₀₀, A₅₀₀₀ | 0.108 km² (120 cells × 900 m²) |
    | Permanent snow | 0 km² |
    | L | 0.594 km |
    | S (H/L) and S₁₀₋₈₅ | 0.0707 m/m |
    | L_c | 0.297 km |
    | Elevations | 11 – 34.3 – 53 m |
    | River class | III (highest point below 1,500 m) |

## Typed numbers and the defaults

Without a DEM, type the numbers. Only $A$ is required:

=== "Python"

    ```python
    from MRRpy.nepal import CatchmentDescriptors, measure_catchment

    site = CatchmentDescriptors(area_km2=420, area_below_3000_km2=260,
                                area_below_5000_km2=380, flow_length_km=48,
                                flow_path_slope=0.06, max_elevation_m=5900,
                                name="Snow-fed river")
    site.table()          # quantity / value / unit, with the river class
    site.assumptions()    # [] here: nothing had to be assumed

    measured = measure_catchment("results/")     # or from the DEM
    ```

=== "Command line"

    ```bash
    MRRpy nepal estimate --area 420 --area-below-3000 260 --area-below-5000 380 \
        --length-km 48 --slope 0.06 --max-elevation 5900
    MRRpy nepal estimate --results results/        # measured from the DEM
    ```

=== "Notebook form / QGIS"

    In the **Site** tab choose *Type the numbers* and fill the boxes (only the
    area is required), or choose a results folder, a config file or a DEM and an
    outlet and press **Measure the catchment**. The QGIS tool *3. Nepal flood
    estimates* has the same choice.

Numbers you leave empty take these values. Every assumption is listed by
`assumptions()`, printed in the notes of the methods that depend on it, and
written in the report:

| Left empty | Value used | Note in the report |
|---|---|---|
| $A_{3000}$ | $A$ | "the area below 3,000 m is taken as the whole area (true for Terai and Chure catchments; give it if part lies higher)" |
| $A_{5000}$ | $A - a$ if $a$ was given, else $A$ | "no permanent snow is assumed" (when $a$ is also empty) |
| $a$ (snow) | $A - A_{5000}$ if $A_{5000}$ was given, else 0 | |
| $L$, $S$ | — | the Rational method reports *needs input*; the physics run is 24 h longer than the storm |

The numbers are checked: $A > 0$; no area or length is negative; no part area
is larger than $A$; and $A_{3000} \le A_{5000}$.

## River class

The compendium sorts Nepali rivers into three classes, and the national formulas
are least reliable for Class III (§6). MRRpy-Nepal guesses the class from the
elevations. It is used only for warnings, never inside a formula:

| Class | Rule used | Meaning |
|---|---|---|
| I | snow area $a > 0$, or $z_{max} \ge 5{,}000$ m | snow-fed river |
| III | $z_{max} < 1{,}500$ m | Chure/Siwalik or Terai stream |
| II | otherwise (with $z_{max}$ known) | rain-fed river from the hills or the Mahabharat range |
| II | $z_{max}$ unknown and $A_{3000} < A$ | rain-fed river with high ground above 3,000 m |
| unknown | $z_{max}$ unknown and $A_{3000} = A$ | give the highest elevation to tell a Chure stream from a hill river |

What a Class III catchment changes:

* WECS/DHM 1990, DHM 2004 and MHSP 1997 are marked *use with caution*: there
  $A_{3000} = A$, so the formulas use area only, and few such catchments were in
  the data they were fitted to;
* the results start with a warning that rainfall-based methods, the physics model
  and local flood marks deserve more weight;
* the recommendation says the same.

Next: [the official regional formulas](regional-formulas.md).
