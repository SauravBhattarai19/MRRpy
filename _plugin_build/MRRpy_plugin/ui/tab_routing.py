# -*- coding: utf-8 -*-
"""
tab_routing.py
==============
Tab 4 — Routing & Numerics (with progressive disclosure).

Only the fields relevant to the current choices are shown:
  • Manning source scalar → value; raster → file picker; lulc/lcz → neither.
  • Channel-n override off → hide channel-n value.
  • Scheme diffusive → diffusion θ; dynamic → flux-centering θ;
    diffusive_implicit → the Picard / solver controls.
  • Channel routing off → hide per-order widths.
  • Adaptive off → hide the CFL controls.  The implicit scheme has no CFL
    stability limit, so it swaps the explicit C target / dt-max for its own
    (≫1 allowed) Courant target.

The scheme list is read from the core package (``Config`` enum registry), so a
scheme added to MRRpy shows up here even before it gets a friendly label.
"""

import os
import sys

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QGroupBox, QDoubleSpinBox,
    QSpinBox, QRadioButton, QButtonGroup, QHBoxLayout, QLabel,
    QComboBox, QCheckBox, QLineEdit, QScrollArea, QFrame,
)
from qgis.gui import QgsCollapsibleGroupBox, QgsFileWidget


def _set_row_visible(form: QFormLayout, field, visible: bool):
    """Show/hide a QFormLayout row (both the field and its label, if any)."""
    field.setVisible(visible)
    lbl = form.labelForField(field)
    if lbl is not None:
        lbl.setVisible(visible)


def _cupy_available() -> bool:
    """Check CuPy availability via the core package's backend helper."""
    try:
        from ..bridge import ensure_core
        ensure_core()
        from MRRpy.utils import gpu_utils
        return gpu_utils.cupy_available()
    except Exception:  # noqa: BLE001
        return False


# Friendly labels for the routing schemes; the order and membership come from
# the core registry (MRRpy.config._ENUM_CHOICES["ROUTING_SCHEME"]).
_SCHEME_LABELS = {
    "kinematic": "kinematic — Manning on static bed slope (fast, reproducible)",
    "diffusive": "diffusive — CASC2D/GSSHA water-surface-slope diffusion wave",
    "muskingum": "muskingum — Muskingum–Cunge (physical diffusion, grid-independent)",
    "dynamic": "dynamic — local-inertial dynamic wave (LISFLOOD-FP; backwater, surges)",
    "diffusive_implicit": "diffusive_implicit — semi-implicit diffusion wave "
                          "(HEC-RAS-style, unconditionally stable, CPU only)",
}
def routing_schemes():
    """Ordered routing-scheme names, as the installed core package defines them."""
    from ..bridge import core_choices
    return core_choices("ROUTING_SCHEME", list(_SCHEME_LABELS))


class TabRouting(QWidget):
    """Routing & numerics parameters tab."""

    _MANNINGS_SOURCES = ["scalar", "lulc", "lcz", "raster"]
    _IMPLICIT_SOLVERS = ["auto", "numba", "splu"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._gpu_ok = _cupy_available()
        self._channel_n_custom = None   # non-scalar MANNINGS_N_CHANNEL from a loaded config
        self._build_ui()
        self._wire_disclosure()
        self._apply_disclosure()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        panel = QWidget()
        scroll.setWidget(panel)
        root = QVBoxLayout(panel)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self._build_mannings_group(root)
        self._build_scheme_group(root)
        self._build_channel_group(root)
        self._build_time_group(root)
        self._build_backend_group(root)
        self._build_advanced_group(root)
        root.addStretch()

    # ── Manning's roughness ────────────────────────────────────────────────────

    def _build_mannings_group(self, root):
        grp = QGroupBox("Manning's Roughness")
        form = self._mann_form = QFormLayout(grp)

        self.mannings_source = QComboBox()
        self.mannings_source.addItems([
            "scalar — uniform value",
            "lulc — ESA WorldCover lookup (needs GEE)",
            "lcz — WUDAPT LCZ lookup (needs GEE; also sets OPM root-zone depth)",
            "raster — pre-computed GeoTIFF",
        ])
        form.addRow("Manning's n source:", self.mannings_source)

        self.mannings_n = QDoubleSpinBox()
        self.mannings_n.setRange(0.001, 1.0); self.mannings_n.setDecimals(4)
        self.mannings_n.setValue(0.09)
        self.mannings_n.setToolTip("Uniform Manning's n (typical: 0.04–0.10).")
        form.addRow("Manning's n:", self.mannings_n)

        self.mannings_raster = QgsFileWidget()
        self.mannings_raster.setStorageMode(QgsFileWidget.GetFile)
        self.mannings_raster.setFilter("GeoTIFF (*.tif *.tiff);;All files (*)")
        form.addRow("Manning's n raster:", self.mannings_raster)

        self._mann_gee_note = QLabel(
            "Downloads land cover from Earth Engine — set the project on the "
            "Precipitation tab.")
        self._mann_gee_note.setWordWrap(True)
        self._mann_gee_note.setStyleSheet("color: #666;")
        form.addRow(self._mann_gee_note)

        self.channel_n_override = QCheckBox("Override roughness on channel cells")
        self.channel_n_override.setChecked(True)
        form.addRow(self.channel_n_override)

        self.channel_n = QDoubleSpinBox()
        self.channel_n.setRange(0.005, 0.5); self.channel_n.setDecimals(4)
        self.channel_n.setValue(0.035)
        self.channel_n.setToolTip("Uniform channel Manning's n for high-flow-accumulation cells.")
        form.addRow("Channel n:", self.channel_n)

        # A loaded config may carry a rule the UI can't edit (per-Strahler-order
        # dict, elevation bins, a raster path).  It is kept verbatim until the
        # user unticks the override.
        self._channel_n_custom_label = QLabel()
        self._channel_n_custom_label.setWordWrap(True)
        self._channel_n_custom_label.setStyleSheet("color: #666;")
        form.addRow("Channel n:", self._channel_n_custom_label)
        self.channel_n_override.toggled.connect(self._on_channel_override_toggled)

        self.channel_faccum = QSpinBox()
        self.channel_faccum.setRange(0, 100_000_000)
        self.channel_faccum.setSpecialValueText("auto (top ~1% of cells)")
        self.channel_faccum.setValue(0)
        self.channel_faccum.setToolTip("Flow-accumulation threshold that defines channel cells. 0 = auto.")
        form.addRow("Channel faccum threshold:", self.channel_faccum)

        root.addWidget(grp)

    # ── Routing scheme ─────────────────────────────────────────────────────────

    def _build_scheme_group(self, root):
        grp = QGroupBox("Routing Scheme")
        form = self._scheme_form = QFormLayout(grp)

        self.scheme_combo = QComboBox()
        self._SCHEMES = routing_schemes()
        self.scheme_combo.addItems([_SCHEME_LABELS.get(s, s) for s in self._SCHEMES])
        self.scheme_combo.setCurrentIndex(self._scheme_index("diffusive"))
        form.addRow("Scheme:", self.scheme_combo)

        self.diffusion_theta = QDoubleSpinBox()
        self.diffusion_theta.setRange(0.0, 1.0); self.diffusion_theta.setDecimals(2)
        self.diffusion_theta.setValue(1.0); self.diffusion_theta.setSingleStep(0.1)
        self.diffusion_theta.setToolTip("0 ≈ kinematic  |  1 = full water-surface-slope diffusion.")
        form.addRow("Diffusion θ:", self.diffusion_theta)

        # ── dynamic (local-inertial) ──────────────────────────────────────────
        self.dynamic_flux_theta = QDoubleSpinBox()
        self.dynamic_flux_theta.setRange(0.0, 1.0); self.dynamic_flux_theta.setDecimals(2)
        self.dynamic_flux_theta.setValue(0.8); self.dynamic_flux_theta.setSingleStep(0.05)
        self.dynamic_flux_theta.setToolTip(
            "de Almeida flux-centering weight θ.\n"
            "1.0 = original Bates scheme (prone to checkerboard oscillation);\n"
            "0.7–0.9 damps it.  Default 0.8.")
        form.addRow("Flux-centering θ:", self.dynamic_flux_theta)

        # ── diffusive_implicit (semi-implicit tree solve) ─────────────────────
        # Expert knobs; the defaults suit most runs, so they start collapsed.
        self._grp_implicit = QgsCollapsibleGroupBox("Semi-implicit solver settings")
        self._grp_implicit.setCollapsed(True)
        self._grp_implicit.setSaveCollapsedState(False)
        impl_form = QFormLayout(self._grp_implicit)
        form.addRow(self._grp_implicit)
        self.implicit_solver = QComboBox()
        self.implicit_solver.addItems([
            "auto — Numba sweep if installed, else SciPy splu",
            "numba — parallel O(n) tree sweep",
            "splu — SciPy sparse LU (no Numba needed)",
        ])
        self.implicit_solver.setToolTip("Linear-solve backend for the implicit step.")
        impl_form.addRow("Implicit solver:", self.implicit_solver)

        self.implicit_threads = QSpinBox()
        self.implicit_threads.setRange(0, 1024)
        self.implicit_threads.setSpecialValueText("auto (min(32, CPU cores))")
        self.implicit_threads.setValue(0)
        self.implicit_threads.setToolTip(
            "Threads for the Numba assembly kernel.  It is memory-bandwidth bound:\n"
            "beyond ~32–64 threads it gets slower.  0 = auto.")
        impl_form.addRow("Solver threads:", self.implicit_threads)

        self.implicit_theta = QDoubleSpinBox()
        self.implicit_theta.setRange(0.5, 1.0); self.implicit_theta.setDecimals(2)
        self.implicit_theta.setValue(1.0); self.implicit_theta.setSingleStep(0.05)
        self.implicit_theta.setToolTip("Time weighting: 1.0 = backward Euler (robust), 0.5 = Crank–Nicolson.")
        impl_form.addRow("Implicit θ:", self.implicit_theta)

        self.implicit_max_iters = QSpinBox()
        self.implicit_max_iters.setRange(1, 100); self.implicit_max_iters.setValue(8)
        self.implicit_max_iters.setToolTip("Picard iterations per step (lagged conveyance).")
        impl_form.addRow("Picard max iterations:", self.implicit_max_iters)

        self.implicit_tol = QDoubleSpinBox()
        self.implicit_tol.setRange(1e-8, 1.0); self.implicit_tol.setDecimals(8)
        self.implicit_tol.setValue(1e-4); self.implicit_tol.setSuffix(" m")
        self.implicit_tol.setToolTip("Picard convergence tolerance on max |Δ water-surface elevation|.")
        impl_form.addRow("Picard tolerance:", self.implicit_tol)

        self.implicit_relax = QDoubleSpinBox()
        self.implicit_relax.setRange(0.05, 1.0); self.implicit_relax.setDecimals(2)
        self.implicit_relax.setValue(0.7); self.implicit_relax.setSingleStep(0.05)
        self.implicit_relax.setToolTip(
            "Conductance under-relaxation; helps Picard converge at large steps.\n"
            "1.0 = off.  Works best with the adaptive timestep.")
        impl_form.addRow("Conductance relaxation:", self.implicit_relax)

        self.implicit_slope_floor = QDoubleSpinBox()
        self.implicit_slope_floor.setRange(1e-12, 1e-2); self.implicit_slope_floor.setDecimals(12)
        self.implicit_slope_floor.setValue(1e-8)
        self.implicit_slope_floor.setToolTip("Floor on |water-surface slope| in the conductance [m/m].")
        impl_form.addRow("Slope floor:", self.implicit_slope_floor)

        root.addWidget(grp)

    # ── Channel routing ────────────────────────────────────────────────────────

    def _build_channel_group(self, root):
        grp = QGroupBox("Confined Channel Routing")
        form = self._channel_form = QFormLayout(grp)

        self.channel_routing = QCheckBox(
            "Route channel cells as a confined rectangular channel (true R = A/P)"
        )
        self.channel_routing.setChecked(True)
        form.addRow(self.channel_routing)

        self.channel_widths = QLineEdit("3,5,8,12,18,28,45,70")
        self.channel_widths.setToolTip(
            "Channel width B [m] per Strahler order, comma-separated, from order 1.\n"
            "Orders above the last value reuse the last value."
        )
        form.addRow("Channel widths by order (m):", self.channel_widths)

        root.addWidget(grp)

    # ── Time stepping ──────────────────────────────────────────────────────────

    def _build_time_group(self, root):
        grp = QGroupBox("Time Stepping")
        form = self._time_form = QFormLayout(grp)

        self.adaptive = QCheckBox("Adaptive CFL timestep (re-derive Δt each step from wave celerity)")
        self.adaptive.setChecked(True)
        form.addRow(self.adaptive)

        self.dt_spin = QDoubleSpinBox()
        self.dt_spin.setRange(0.001, 3600.0); self.dt_spin.setDecimals(3)
        self.dt_spin.setValue(2.0); self.dt_spin.setSuffix(" s")
        self.dt_spin.setToolTip("Static / initial Δt. Used as the fallback when adaptive is off.")
        form.addRow("Time step Δt (static/initial):", self.dt_spin)

        self.cfl_target = QDoubleSpinBox()
        self.cfl_target.setRange(0.05, 0.99); self.cfl_target.setDecimals(2)
        self.cfl_target.setValue(0.85)
        self.cfl_target.setToolTip("Target Courant number (0.7 safe, 0.85 sharper peak).")
        form.addRow("CFL target C:", self.cfl_target)

        self.implicit_cfl_target = QDoubleSpinBox()
        self.implicit_cfl_target.setRange(0.1, 1000.0); self.implicit_cfl_target.setDecimals(2)
        self.implicit_cfl_target.setValue(2.0)
        self.implicit_cfl_target.setToolTip(
            "Courant target for the semi-implicit scheme (> 1 allowed — it is\n"
            "unconditionally stable).  It bounds the per-step depth change so the\n"
            "Picard loop converges; ~1–3 mirrors HEC-RAS practice.  The adaptive\n"
            "Δt ceiling is the output interval (CFL dt max is not used).")
        form.addRow("Implicit Courant target:", self.implicit_cfl_target)

        self.cfl_dt_max = QDoubleSpinBox()
        self.cfl_dt_max.setRange(0.0, 3600.0); self.cfl_dt_max.setDecimals(2)
        self.cfl_dt_max.setValue(5.0)
        self.cfl_dt_max.setSpecialValueText("auto (= output interval)")
        self.cfl_dt_max.setSuffix(" s")
        self.cfl_dt_max.setToolTip("Ceiling on adaptive Δt. 0 = auto (output interval).")

        self.cfl_dt_min = QDoubleSpinBox()
        self.cfl_dt_min.setRange(0.001, 60.0); self.cfl_dt_min.setDecimals(3)
        self.cfl_dt_min.setValue(0.01); self.cfl_dt_min.setSuffix(" s")
        self.cfl_dt_min.setToolTip("Floor on adaptive Δt; the flux limiter covers cells needing less.")

        self.cfl_dt_grow = QDoubleSpinBox()
        self.cfl_dt_grow.setRange(1.0, 100.0); self.cfl_dt_grow.setDecimals(2)
        self.cfl_dt_grow.setValue(1.5)
        self.cfl_dt_grow.setToolTip("Max factor Δt may grow per step (GSSHA-style ramp-up).")

        self.sim_hours = QDoubleSpinBox()
        self.sim_hours.setRange(0.1, 99999.0); self.sim_hours.setDecimals(1)
        self.sim_hours.setValue(96.0); self.sim_hours.setSuffix(" hours")
        self.sim_hours.setToolTip("Total simulation length. Also sets the IMERG download window end.")
        form.addRow("Simulation duration:", self.sim_hours)

        self.out_interval = QSpinBox()
        self.out_interval.setRange(1, 86400); self.out_interval.setValue(600)
        self.out_interval.setSuffix(" s")
        self.out_interval.setToolTip("How often to record a hydrograph row (600 s = 10-minute output).")
        form.addRow("Output interval:", self.out_interval)

        root.addWidget(grp)

    # ── Backend ────────────────────────────────────────────────────────────────

    def _build_backend_group(self, root):
        grp = QGroupBox("Compute Backend")
        v = QVBoxLayout(grp)

        self._backend_group = QButtonGroup(self)
        self._rb_cpu = QRadioButton("CPU  (NumPy — always available)")
        self._rb_cpu.setChecked(True)
        self._rb_gpu = QRadioButton("GPU  (CuPy / CUDA)")

        if self._gpu_ok:
            self._rb_gpu.setToolTip("CuPy detected — GPU acceleration available.")
        else:
            self._rb_gpu.setEnabled(False)
            self._rb_gpu.setToolTip(
                "CuPy not found in this Python environment.\n"
                "Install CuPy matching your CUDA version:\n"
                "  pip install cupy-cuda12x  (CUDA 12)\n"
                "  pip install cupy-cuda11x  (CUDA 11)"
            )

        self._backend_group.addButton(self._rb_cpu, 0)
        self._backend_group.addButton(self._rb_gpu, 1)
        v.addWidget(self._rb_cpu)
        v.addWidget(self._rb_gpu)

        self._prec_widget = QWidget()
        self._prec_row = QHBoxLayout(self._prec_widget)
        self._prec_row.setContentsMargins(0, 0, 0, 0)
        self._prec_label = QLabel("GPU precision:")
        self._prec_row.addWidget(self._prec_label)
        self.precision_combo = QComboBox()
        self.precision_combo.addItems([
            "float64  (full precision, default)",
            "float32  (faster, ~1e-7 relative error)",
        ])
        self.precision_combo.setEnabled(self._gpu_ok)
        self._prec_row.addWidget(self.precision_combo)
        self._prec_row.addStretch()
        v.addWidget(self._prec_widget)

        self._rb_gpu.toggled.connect(lambda on: self.precision_combo.setEnabled(on and self._gpu_ok))

        self._implicit_cpu_note = QLabel(
            "Note: the semi-implicit scheme has no GPU kernel — it will run on the CPU.")
        self._implicit_cpu_note.setWordWrap(True)
        self._implicit_cpu_note.setStyleSheet("color: #8a6d00;")
        v.addWidget(self._implicit_cpu_note)

        root.addWidget(grp)

    # ── Advanced ───────────────────────────────────────────────────────────────

    def _build_advanced_group(self, root):
        # Collapsed by default but ALWAYS applied (the defaults suit most runs).
        grp = QgsCollapsibleGroupBox("Advanced numerics")
        grp.setCollapsed(True)
        grp.setSaveCollapsedState(False)
        form = self._adv_form = QFormLayout(grp)

        form.addRow("Adaptive Δt max:", self.cfl_dt_max)
        form.addRow("Adaptive Δt min:", self.cfl_dt_min)
        form.addRow("Adaptive Δt growth factor:", self.cfl_dt_grow)

        self.mass_balance = QCheckBox("Append per-run mass-balance row to mass_balance.csv")
        self.mass_balance.setChecked(True)
        form.addRow(self.mass_balance)

        self.min_slope = QDoubleSpinBox()
        self.min_slope.setRange(1e-8, 1.0); self.min_slope.setDecimals(6)
        self.min_slope.setValue(1e-4)
        self.min_slope.setToolTip("Minimum slope floor in Manning's equation [m/m].")
        form.addRow("MIN_SLOPE:", self.min_slope)

        self.min_depth = QDoubleSpinBox()
        self.min_depth.setRange(1e-10, 0.01); self.min_depth.setDecimals(8)
        self.min_depth.setValue(1e-6)
        self.min_depth.setToolTip("Minimum water depth kept to avoid numerical issues [m].")
        form.addRow("MIN_DEPTH_M:", self.min_depth)

        self.slope_cap = QDoubleSpinBox()
        self.slope_cap.setRange(0.0, 10.0); self.slope_cap.setDecimals(4)
        self.slope_cap.setSingleStep(0.01)
        self.slope_cap.setValue(0.0)
        self.slope_cap.setSpecialValueText("off (uncapped)")
        self.slope_cap.setToolTip(
            "Cap on the friction slope used in Manning's velocity/celerity (all schemes).\n"
            "On near-vertical cells raw Manning gives unphysical velocities and\n"
            "celerities no explicit Δt can satisfy.  0.05–0.10 is typical for steep\n"
            "terrain.  0 = off.")
        form.addRow("MANNING_SLOPE_CAP:", self.slope_cap)

        self.flux_limiter = QCheckBox(
            "Volume-conservative flux limiter (Q ≤ V/Δt) — kinematic / diffusive")
        self.flux_limiter.setChecked(True)
        self.flux_limiter.setToolTip(
            "The explicit schemes' stability net.  Disable ONLY together with a\n"
            "CFL-safe adaptive timestep.  Muskingum–Cunge never uses it.")
        form.addRow(self.flux_limiter)

        root.addWidget(grp)

    # ── Progressive disclosure ─────────────────────────────────────────────────

    def _wire_disclosure(self):
        self.mannings_source.currentIndexChanged.connect(self._apply_disclosure)
        self.channel_n_override.toggled.connect(self._apply_disclosure)
        self.scheme_combo.currentIndexChanged.connect(self._apply_disclosure)
        self.channel_routing.toggled.connect(self._apply_disclosure)
        self.adaptive.toggled.connect(self._apply_disclosure)
        self._rb_gpu.toggled.connect(self._apply_disclosure)

    def uses_gee(self) -> bool:
        """LULC / LCZ Manning's n is downloaded from Earth Engine."""
        return self._MANNINGS_SOURCES[self.mannings_source.currentIndex()] in ("lulc", "lcz")

    def get_scheme(self) -> str:
        return self._SCHEMES[self.scheme_combo.currentIndex()]

    def _scheme_index(self, name) -> int:
        name = str(name).lower()
        return self._SCHEMES.index(name) if name in self._SCHEMES else 0

    def _apply_disclosure(self, *args):
        src = self.mannings_source.currentIndex()   # 0 scalar,1 lulc,2 lcz,3 raster
        _set_row_visible(self._mann_form, self.mannings_n, src == 0)
        _set_row_visible(self._mann_form, self.mannings_raster, src == 3)
        custom_ch_n = self._channel_n_custom is not None
        _set_row_visible(self._mann_form, self.channel_n,
                         self.channel_n_override.isChecked() and not custom_ch_n)
        _set_row_visible(self._mann_form, self._channel_n_custom_label,
                         self.channel_n_override.isChecked() and custom_ch_n)

        scheme = self.get_scheme()
        implicit = scheme == "diffusive_implicit"
        _set_row_visible(self._scheme_form, self.diffusion_theta, scheme == "diffusive")
        _set_row_visible(self._scheme_form, self.dynamic_flux_theta, scheme == "dynamic")
        self._grp_implicit.setVisible(implicit)

        _set_row_visible(self._channel_form, self.channel_widths, self.channel_routing.isChecked())

        adaptive = self.adaptive.isChecked()
        # The implicit scheme is unconditionally stable: it uses its own (≫1)
        # Courant target and the output interval as the dt ceiling.
        _set_row_visible(self._time_form, self.cfl_target, adaptive and not implicit)
        _set_row_visible(self._time_form, self.implicit_cfl_target, adaptive and implicit)
        _set_row_visible(self._adv_form, self.cfl_dt_max, adaptive and not implicit)
        for w in (self.cfl_dt_min, self.cfl_dt_grow):
            _set_row_visible(self._adv_form, w, adaptive)

        self._mann_gee_note.setVisible(src in (1, 2))
        self._prec_widget.setVisible(self._rb_gpu.isChecked())

        self._implicit_cpu_note.setVisible(implicit and self._rb_gpu.isChecked())

    def _on_channel_override_toggled(self, on):
        if not on:
            self._channel_n_custom = None
        self._apply_disclosure()

    # ── Public getters ────────────────────────────────────────────────────────

    def get_backend(self) -> str:
        return "gpu" if self._rb_gpu.isChecked() else "cpu"

    def get_precision(self) -> str:
        return "float32" if self.precision_combo.currentIndex() == 1 else "float64"

    @staticmethod
    def _parse_widths(text):
        try:
            vals = [float(x) for x in text.replace(";", ",").split(",") if x.strip()]
        except ValueError:
            return None
        return {i + 1: v for i, v in enumerate(vals)} if vals else None

    # ── Config I/O ────────────────────────────────────────────────────────────

    def apply_config(self, cfg):
        src = getattr(cfg, "MANNINGS_N_SOURCE", "scalar")
        self.mannings_source.setCurrentIndex(
            self._MANNINGS_SOURCES.index(src) if src in self._MANNINGS_SOURCES else 0
        )
        self.mannings_n.setValue(cfg.MANNINGS_N)
        if getattr(cfg, "MANNINGS_N_RASTER_PATH", None):
            self.mannings_raster.setFilePath(cfg.MANNINGS_N_RASTER_PATH)
        ch_n = getattr(cfg, "MANNINGS_N_CHANNEL", 0.035)
        if ch_n is None:
            self.channel_n_override.setChecked(False)
        elif isinstance(ch_n, (int, float)) and not isinstance(ch_n, bool):
            self.channel_n_override.setChecked(True)
            self._channel_n_custom = None
            self.channel_n.setValue(float(ch_n))
        else:
            self.channel_n_override.setChecked(True)
            self._channel_n_custom = ch_n
            text = repr(ch_n)
            if len(text) > 120:
                text = text[:117] + "…"
            self._channel_n_custom_label.setText(
                f"custom rule from the loaded config (kept as is):\n{text}")
        faccum = getattr(cfg, "CHANNEL_FACCUM_THRESHOLD", None)
        self.channel_faccum.setValue(int(faccum) if faccum else 0)

        self.scheme_combo.setCurrentIndex(
            self._scheme_index(getattr(cfg, "ROUTING_SCHEME", "kinematic")))
        self.diffusion_theta.setValue(float(getattr(cfg, "DIFFUSION_THETA", 1.0)))
        self.dynamic_flux_theta.setValue(float(getattr(cfg, "DYNAMIC_FLUX_THETA", 0.8)))

        solver = str(getattr(cfg, "IMPLICIT_SOLVER", "auto")).lower()
        self.implicit_solver.setCurrentIndex(
            self._IMPLICIT_SOLVERS.index(solver) if solver in self._IMPLICIT_SOLVERS else 0)
        self.implicit_threads.setValue(int(getattr(cfg, "IMPLICIT_NUM_THREADS", None) or 0))
        self.implicit_theta.setValue(float(getattr(cfg, "IMPLICIT_THETA", 1.0)))
        self.implicit_max_iters.setValue(int(getattr(cfg, "IMPLICIT_MAX_ITERS", 8)))
        self.implicit_tol.setValue(float(getattr(cfg, "IMPLICIT_TOL", 1e-4)))
        self.implicit_relax.setValue(float(getattr(cfg, "IMPLICIT_RELAX", 0.7)))
        self.implicit_slope_floor.setValue(float(getattr(cfg, "IMPLICIT_SLOPE_FLOOR", 1e-8)))
        self.implicit_cfl_target.setValue(float(getattr(cfg, "IMPLICIT_CFL_TARGET", 2.0)))

        self.channel_routing.setChecked(bool(getattr(cfg, "CHANNEL_ROUTING", False)))
        widths = getattr(cfg, "CHANNEL_WIDTH_BY_ORDER", None)
        if isinstance(widths, dict) and widths:
            self.channel_widths.setText(",".join(str(widths[k]) for k in sorted(widths)))

        self.adaptive.setChecked(bool(getattr(cfg, "ADAPTIVE_TIMESTEP", False)))
        self.dt_spin.setValue(float(cfg.TIME_STEP_SECONDS))
        self.cfl_target.setValue(float(getattr(cfg, "CFL_TARGET", 0.85)))
        self.cfl_dt_max.setValue(float(getattr(cfg, "CFL_DT_MAX", 0.0) or 0.0))
        self.cfl_dt_min.setValue(float(getattr(cfg, "CFL_DT_MIN", 0.01)))
        self.cfl_dt_grow.setValue(float(getattr(cfg, "CFL_DT_GROW", 1.5)))
        self.sim_hours.setValue(float(cfg.TOTAL_SIMULATION_TIME_HOURS))
        self.out_interval.setValue(int(cfg.OUTPUT_INTERVAL_SECONDS))

        if cfg.BACKEND == "gpu" and self._gpu_ok:
            self._rb_gpu.setChecked(True)
        else:
            self._rb_cpu.setChecked(True)
        self.precision_combo.setCurrentIndex(0 if cfg.GPU_PRECISION == "float64" else 1)

        self.mass_balance.setChecked(bool(getattr(cfg, "MASS_BALANCE_REPORT", True)))
        self.min_slope.setValue(float(cfg.MIN_SLOPE))
        self.min_depth.setValue(float(cfg.MIN_DEPTH_M))
        self.slope_cap.setValue(float(getattr(cfg, "MANNING_SLOPE_CAP", None) or 0.0))
        self.flux_limiter.setChecked(bool(getattr(cfg, "FLUX_LIMITER", True)))

        self._apply_disclosure()

    def write_to_config(self, cfg):
        cfg.MANNINGS_N_SOURCE = self._MANNINGS_SOURCES[self.mannings_source.currentIndex()]
        cfg.MANNINGS_N = self.mannings_n.value()
        cfg.MANNINGS_N_RASTER_PATH = self.mannings_raster.filePath() or None
        if not self.channel_n_override.isChecked():
            cfg.MANNINGS_N_CHANNEL = None
        elif self._channel_n_custom is not None:
            cfg.MANNINGS_N_CHANNEL = self._channel_n_custom
        else:
            cfg.MANNINGS_N_CHANNEL = self.channel_n.value()
        cfg.CHANNEL_FACCUM_THRESHOLD = self.channel_faccum.value() or None

        cfg.ROUTING_SCHEME = self.get_scheme()
        cfg.DIFFUSION_THETA = self.diffusion_theta.value()
        cfg.DYNAMIC_FLUX_THETA = self.dynamic_flux_theta.value()
        cfg.IMPLICIT_SOLVER = self._IMPLICIT_SOLVERS[self.implicit_solver.currentIndex()]
        cfg.IMPLICIT_NUM_THREADS = self.implicit_threads.value() or None
        cfg.IMPLICIT_THETA = self.implicit_theta.value()
        cfg.IMPLICIT_MAX_ITERS = self.implicit_max_iters.value()
        cfg.IMPLICIT_TOL = self.implicit_tol.value()
        cfg.IMPLICIT_RELAX = self.implicit_relax.value()
        cfg.IMPLICIT_SLOPE_FLOOR = self.implicit_slope_floor.value()
        cfg.IMPLICIT_CFL_TARGET = self.implicit_cfl_target.value()

        cfg.CHANNEL_ROUTING = self.channel_routing.isChecked()
        widths = self._parse_widths(self.channel_widths.text())
        if widths:
            cfg.CHANNEL_WIDTH_BY_ORDER = widths

        cfg.ADAPTIVE_TIMESTEP = self.adaptive.isChecked()
        cfg.TIME_STEP_SECONDS = self.dt_spin.value()
        cfg.CFL_TARGET = self.cfl_target.value()
        cfg.CFL_DT_MAX = self.cfl_dt_max.value() or None
        cfg.CFL_DT_MIN = self.cfl_dt_min.value()
        cfg.CFL_DT_GROW = self.cfl_dt_grow.value()
        cfg.TOTAL_SIMULATION_TIME_HOURS = self.sim_hours.value()
        cfg.OUTPUT_INTERVAL_SECONDS = self.out_interval.value()

        cfg.BACKEND = self.get_backend()
        cfg.GPU_PRECISION = self.get_precision()

        cfg.MASS_BALANCE_REPORT = self.mass_balance.isChecked()
        cfg.MIN_SLOPE = self.min_slope.value()
        cfg.MIN_DEPTH_M = self.min_depth.value()
        cfg.MANNING_SLOPE_CAP = self.slope_cap.value() or None
        cfg.FLUX_LIMITER = self.flux_limiter.isChecked()
