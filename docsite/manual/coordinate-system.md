# 2 Coordinate system

The model computes slopes, areas and flow speeds in **metres**, so it runs on a
grid in a **projected coordinate system** whose unit is the metre. Your DEM and
every other map you give (rasters, gauge files) can be in any projection; MRRpy
reprojects them to this one.

!!! info "Where to set it"
    Notebook form: step **2 Coordinate system** (one click fills in your outlet's
    UTM zone) · Wizard: part **1 Basin, terrain and results folder** (it suggests
    the UTM zone) · QGIS: tab **1 · DEM & Watershed**, *Target CRS*.

## 2.1 Map projection

The safe choice is the **UTM zone that contains your basin**. Its EPSG code is

$$
\text{EPSG} = \begin{cases} 32600 + \text{zone} & \text{north of the equator} \\ 32700 + \text{zone} & \text{south of the equator} \end{cases}
\qquad \text{zone} = \left\lfloor \frac{\text{longitude} + 180}{6} \right\rfloor + 1
$$

| Place | Longitude | Zone | Code |
|---|---|---|---|
| Kathmandu, Nepal | 85.3° E | 45 N | `EPSG:32645` |
| Mississippi, USA | 90.2° W | 15 N | `EPSG:32615` |
| São Paulo, Brazil | 46.6° W | 23 S | `EPSG:32723` |
| Nairobi, Kenya | 36.8° E | 37 S | `EPSG:32737` |

A national projection in metres (for example `EPSG:5070` for the contiguous
USA) works as well. Don't use a geographic system such as `EPSG:4326`: its unit
is the degree, not the metre.

<!-- settings: TARGET_CRS_EPSG -->

!!! note "Coordinates that stay in degrees"
    Points you type, such as the outlet `OUTPUT_POINT`, gauges and inflow points,
    are always **latitude, longitude** in degrees, whatever the projection. The
    exceptions are the rain-gauge file (`easting_m`, `northing_m`) and points
    given as `easting`/`northing`: those are in this projection.
