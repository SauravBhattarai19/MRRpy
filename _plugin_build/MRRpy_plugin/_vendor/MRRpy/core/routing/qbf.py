# -*- coding: utf-8 -*-
"""
qbf.py — bankfull discharge Q_bf [m³/s] for ``CHANNEL_GEOMETRY='discharge'``.

The model channel at each cell carries Q_bf before water spreads over the rest
of the cell; the target is the 2-year flood (median of yearly peak flows).
``CHANNEL_QBF_M3S`` takes one of three kinds of value:

  None / "auto"   automatic global estimate of the 2-year flood at the outlet
                  (HydroATLAS wettest-month flow, one Earth Engine request;
                  without Earth Engine, drainage area alone), spread over the
                  network as Q_bf ∝ A^CHANNEL_QBF_AREA_EXP.
  a number        your 2-year flood at the outlet — or at the gauge whose
                  drainage area is CHANNEL_QBF_AREA_KM2 — spread the same way.
  a formula       a regional relation evaluated at EVERY cell with that cell's
                  own variables, e.g. "wecs_nepal" or "1.8767*(A_below(3000)+1)^0.8783".

Formula language (parsed safely — no Python is executed):
  A             drainage area of the cell [km²]
  A_below(z)    part of that area below elevation z [km²]   (A_above(z) likewise)
  H             mean elevation of that area [m]
  P             mean annual precipitation over the basin [mm] (HydroATLAS, at the
                outlet — one value for the whole basin; needs Earth Engine)
  + - * / ^ (or **), parentheses, exp, log (= ln), log10, sqrt, abs, min, max.
  A leading "Q2 =" (any name) is ignored, so formulas can be pasted from reports.

The global relations below were fitted once on 5,156 near-natural GSIM gauges
in 62 countries (100–10,000 km², 2-year instantaneous flood) and scored out of
sample — see TestCases/Channel_capacity/report.md §3.  p10/p90 = the range of
(estimate ÷ observed) that holds 80 % of gauges.
"""

import ast
import os

import numpy as np

# Q2 = exp(ln_a) · X^b
GLOBAL_HYDROATLAS = dict(ln_a=2.7126, b=0.6441, p10=0.38, p90=2.59)   # X = dis_m3_pmx·A/UP_AREA
GLOBAL_AREA = dict(ln_a=0.5477, b=0.6057, p10=0.32, p90=3.90)         # X = A [km²]

# name → (formula, description).  Regional relations apply only in their region.
QBF_PRESETS = {
    "wecs_nepal": ("1.8767 * (A_below(3000) + 1) ^ 0.8783",
                   "WECS/DHM (1990) 2-year flood for Nepal; A_below(3000) = drainage area below 3,000 m"),
    "global_area": ("1.73 * A ^ 0.606",
                    "MRRpy global fit on drainage area only (offline); 80 % of gauges within 0.32–3.9×"),
    "global_area_rain": ("1.72e-4 * A ^ 0.640 * P ^ 1.313",
                         "MRRpy global fit on drainage area and mean annual rain P [mm]; 80 % within 0.36–3.3×"),
}

_FUNCS = {"exp": np.exp, "log": np.log, "ln": np.log, "log10": np.log10,
          "sqrt": np.sqrt, "abs": np.abs, "min": np.minimum, "max": np.maximum}
_AREA_FUNCS = ("A_below", "A_above")
_VARS = ("A", "H", "P")
_BINOPS = {ast.Add: np.add, ast.Sub: np.subtract, ast.Mult: np.multiply,
           ast.Div: np.divide, ast.Pow: np.power}


class QbfFormula:
    """A parsed, validated Q_bf formula (or preset name)."""

    def __init__(self, text):
        self.text = str(text).strip()
        expr = self.text
        preset = QBF_PRESETS.get(expr.lower())
        self.preset = expr.lower() if preset else None
        if preset:
            expr = preset[0]
        if "=" in expr:                                   # "Q2 = 1.88*…" → right-hand side
            lhs, rhs = expr.split("=", 1)
            if lhs.strip().isidentifier():
                expr = rhs
        self.expr = expr.strip().replace("^", "**")
        try:
            self.tree = ast.parse(self.expr, mode="eval")
        except SyntaxError as exc:
            raise ValueError(f"Q_bf formula {self.text!r} is not valid maths: {exc.msg}") from None
        self.uses = set()
        self._check(self.tree.body)

    def __repr__(self):
        return f"QbfFormula({self.text!r})"

    # -- validation -----------------------------------------------------------
    def _check(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            return
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            self._check(node.left)
            self._check(node.right)
            return
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            self._check(node.operand)
            return
        if isinstance(node, ast.Name):
            if node.id not in _VARS:
                raise ValueError(f"Q_bf formula {self.text!r}: unknown name {node.id!r} "
                                 f"(variables: {', '.join(_VARS)}, A_below(z), A_above(z))")
            self.uses.add(node.id)
            return
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            name = node.func.id
            if name in _AREA_FUNCS:
                if len(node.args) != 1:
                    raise ValueError(f"Q_bf formula {self.text!r}: {name}() takes one elevation [m]")
                self.uses.add((name, _constant(node.args[0], self.text)))
                return
            if name in _FUNCS:
                n_ok = len(node.args) >= 2 if name in ("min", "max") else len(node.args) == 1
                if not n_ok:
                    raise ValueError(f"Q_bf formula {self.text!r}: wrong number of arguments to {name}()")
                for a in node.args:
                    self._check(a)
                return
            raise ValueError(f"Q_bf formula {self.text!r}: unknown function {name!r} "
                             f"(allowed: {', '.join(sorted(_FUNCS) + list(_AREA_FUNCS))})")
        raise ValueError(f"Q_bf formula {self.text!r}: '{ast.unparse(node)}' is not allowed "
                         "(use numbers, A, H, P, A_below(z), + - * / ^ and maths functions)")

    # -- evaluation -----------------------------------------------------------
    def evaluate(self, env):
        """Evaluate with ``env`` mapping each entry of ``self.uses`` to a value/array."""
        def ev(node):
            if isinstance(node, ast.Constant):
                return float(node.value)
            if isinstance(node, ast.BinOp):
                return _BINOPS[type(node.op)](ev(node.left), ev(node.right))
            if isinstance(node, ast.UnaryOp):
                v = ev(node.operand)
                return -v if isinstance(node.op, ast.USub) else v
            if isinstance(node, ast.Name):
                return env[node.id]
            name = node.func.id
            if name in _AREA_FUNCS:
                return env[(name, _constant(node.args[0], self.text))]
            args = [ev(a) for a in node.args]
            out = args[0]
            if name in ("min", "max"):
                for a in args[1:]:
                    out = _FUNCS[name](out, a)
                return out
            return _FUNCS[name](out)
        with np.errstate(all="ignore"):
            return ev(self.tree.body)


def _constant(node, text):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_constant(node.operand, text)
    raise ValueError(f"Q_bf formula {text!r}: A_below()/A_above() need a plain number (elevation in m)")


def classify_qbf(spec):
    """
    ('auto', None) | ('value', float) | ('formula', QbfFormula) for a
    ``CHANNEL_QBF_M3S`` setting.  Raises ValueError for an unusable value.
    """
    if spec is None:
        return "auto", None
    if isinstance(spec, bool):
        raise ValueError(f"CHANNEL_QBF_M3S must be a number, a formula or 'auto' (got {spec!r})")
    if isinstance(spec, (int, float, np.number)):
        v = float(spec)
    else:
        s = str(spec).strip()
        if s == "" or s.lower() == "auto":
            return "auto", None
        try:
            v = float(s)
        except ValueError:
            return "formula", QbfFormula(s)
    if not np.isfinite(v) or v <= 0:
        raise ValueError(f"CHANNEL_QBF_M3S must be > 0 m³/s (got {spec!r})")
    return "value", v


def describe_presets():
    """Printable list of the formula presets."""
    return "\n".join(f"  {k:18s} {f}\n  {'':18s} {d}" for k, (f, d) in QBF_PRESETS.items())


# ---------------------------------------------------------------------------
def _accumulate(acc, ds):
    for i in range(acc.shape[0]):
        j = ds[i]
        if j >= 0:
            acc[j] += acc[i]
    return acc


try:
    from numba import njit as _njit
    _accumulate = _njit(cache=True)(_accumulate)
except Exception:                                  # pragma: no cover - numba optional
    pass


def upstream_sum(w, ds):
    """Sum of ``w`` over every cell draining to each cell (cells in topological
    order, upstream first; ``ds`` = downstream index, −1 at the outlet)."""
    return _accumulate(np.array(w, dtype=np.float64), np.asarray(ds, dtype=np.int64))


def _lookup_point(cfg, grid_data=None):
    """(lat, lon) where the HydroATLAS lookup is made: OUTPUT_POINT, or — for a
    whole-DEM run, which has no outlet point — the main exit (largest drainage)."""
    if grid_data is not None and grid_data.get("whole_dem"):
        from .terrain import cell_latlon
        lat, lon = cell_latlon(grid_data["outlet_rc"], grid_data["transform"],
                               getattr(cfg, "TARGET_CRS_EPSG", None))
        return (lat, lon) if lat is not None else None
    return getattr(cfg, "OUTPUT_POINT", None) or None


def _outlet_attrs(cfg, point=None):
    from ...gee.hydroatlas import basin_attributes
    lat, lon = point if point is not None else cfg.OUTPUT_POINT
    cache = os.path.join(getattr(cfg, "OUTPUT_DIR", "output/"), "hydroatlas_outlet.json")
    project = getattr(cfg, "GEE_PROJECT", None) or os.environ.get("GEE_PROJECT")
    return basin_attributes(lat, lon, project=project, cache_path=cache)


def global_q2_at_outlet(cfg, a_out_km2, point=None):
    """Automatic 2-year flood at the outlet → (Q2, source label, p10, p90).
    *point* (lat, lon) overrides OUTPUT_POINT (whole-DEM runs: the main exit)."""
    attrs = None
    point = point if point is not None else getattr(cfg, "OUTPUT_POINT", None)
    if point:
        attrs = _outlet_attrs(cfg, point)
    if attrs and attrs.get("dis_m3_pmx", 0) > 0 and attrs.get("UP_AREA", 0) > 0:
        c = GLOBAL_HYDROATLAS
        x = attrs["dis_m3_pmx"] * a_out_km2 / attrs["UP_AREA"]
        return float(np.exp(c["ln_a"]) * x ** c["b"]), "HydroATLAS wettest-month flow", c["p10"], c["p90"]
    c = GLOBAL_AREA
    return (float(np.exp(c["ln_a"]) * a_out_km2 ** c["b"]),
            "drainage area only — Earth Engine unavailable", c["p10"], c["p90"])


def resolve_qbf(cfg, grid_data, A_km2):
    """Q_bf [m³/s] at every cell (array like ``A_km2``) and a one-line source label."""
    kind, val = classify_qbf(getattr(cfg, "CHANNEL_QBF_M3S", None))
    theta = float(getattr(cfg, "CHANNEL_QBF_AREA_EXP", 0.75))
    a_out = float(A_km2.max())

    if kind == "value":
        a_ref = getattr(cfg, "CHANNEL_QBF_AREA_KM2", None)
        a_ref = float(a_ref) if a_ref else a_out
        return val * (A_km2 / a_ref) ** theta, (f"your 2-year flood {val:g} m³/s at {a_ref:,.0f} km², "
                                               f"× (area ratio)^{theta:g}")

    if kind == "auto":
        q2, src, p10, p90 = global_q2_at_outlet(cfg, a_out, _lookup_point(cfg, grid_data))
        print(f"  Channel size   | no CHANNEL_QBF_M3S → global estimate ({src}):\n"
              f"                 | 2-year flood at the outlet ≈ {q2:.0f} m³/s "
              f"(80 % of basins: {q2 / p90:.0f}–{q2 / p10:.0f}); rivers scale as area^{theta:g}.\n"
              f"                 | Know the 2-year flood at a gauge, or a regional formula? "
              f"Set CHANNEL_QBF_M3S to the number or the formula.")
        return q2 * (A_km2 / a_out) ** theta, f"global estimate ({src})"

    f = val
    env = {}
    if "A" in f.uses:
        env["A"] = A_km2
    need_up = [u for u in f.uses if isinstance(u, tuple)] + (["H"] if "H" in f.uses else [])
    if need_up:
        ds = grid_data["ds_idx"]
        ds = ds.get() if hasattr(ds, "get") else np.asarray(ds)
        z = np.asarray(grid_data["dem_1d"], dtype=np.float64)
        ones = upstream_sum(np.ones_like(z), ds)
        if "H" in f.uses:
            env["H"] = upstream_sum(z, ds) / ones
        for u in f.uses:
            if isinstance(u, tuple):
                name, level = u
                below = z < level if name == "A_below" else z >= level
                env[u] = A_km2 * upstream_sum(below.astype(np.float64), ds) / ones
    if "P" in f.uses:
        point = _lookup_point(cfg, grid_data)
        attrs = _outlet_attrs(cfg, point) if point else None
        if not attrs or attrs.get("pre_mm_uyr") is None:
            raise ValueError(f"Q_bf formula {f.text!r} uses P (mean annual rain) but the HydroATLAS "
                             "lookup failed — set GEE_PROJECT, or write P as a number")
        env["P"] = float(attrs["pre_mm_uyr"])
    q = np.broadcast_to(np.asarray(f.evaluate(env), dtype=np.float64), A_km2.shape).copy()
    out = int(np.argmax(A_km2))
    if not np.isfinite(q[out]) or q[out] <= 0:
        raise ValueError(f"Q_bf formula {f.text!r} gives {q[out]!r} m³/s at the outlet")
    bad = ~np.isfinite(q) | (q <= 0)
    q[bad] = 1e-3
    label = f"formula {f.preset or f.text}"
    if f.preset:
        label += f" = {QBF_PRESETS[f.preset][0]}"
    return q, label
