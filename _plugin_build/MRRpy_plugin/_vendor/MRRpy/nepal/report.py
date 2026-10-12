# -*- coding: utf-8 -*-
"""
report.py
=========
The chart and the written report of a Nepal flood study.

``plot_estimates`` draws flood against return period: each official
regional method as a thin grey line, their range shaded with the median on
top, and the methods that carry the story — the physics model, a gauge
frequency analysis (with its confidence band), the Rational method, a donor
gauge — in their own colours, plus any observed flood (e.g. from flood
marks) as a reference line.  The table is always written next to the chart
(it is the chart's accessible twin), so the chart labels sparingly.

``report_markdown`` writes the whole result as Markdown: catchment, design
basis, the table with its flags, the official range, the physics runs,
every method's notes and source caveats, warnings and the recommendation.
"""

import datetime as _dt

import numpy as np

from . import frequency as fq
from .methods import FLOOD_METHODS, STATUS_TEXT

# Chart palette: the validated categorical slots, light and dark (colour
# follows the entity, never its rank — a method always gets the same hue).
_THEMES = {
    "light": dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", muted="#898781",
                  grid="#e1e0d9", axis="#c3c2b7",
                  slots=("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4")),
    "dark": dict(surface="#1a1a19", ink="#f0efec", ink2="#c3c2b7", muted="#898781",
                 grid="#2c2c2a", axis="#383835",
                 slots=("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181")),
}
_SLOT = {"official": 0, "physics": 1, "frequency": 2, "rational": 3, "area_ratio": 4}
_EMPHASIS = ("rational", "area_ratio", "frequency", "physics")      # drawn last = on top


def plot_estimates(estimates, ax=None, observed=None, title=None, theme="light"):
    """
    Flood [m³/s] against return period for every method in *estimates*.

    observed  [(label, Q m³/s)] floods with no return period (flood marks,
              the largest gauged flood) drawn as reference lines.
    theme     'light' or 'dark'.
    Returns (fig, ax).
    """
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

    th = _THEMES[theme]
    if ax is None:
        fig, ax = plt.subplots(figsize=(8.0, 4.8), dpi=110)
    else:
        fig = ax.figure
    fig.patch.set_facecolor(th["surface"])
    ax.set_facecolor(th["surface"])
    T = estimates.T
    tops = []

    first = True
    for r in estimates.official_rows():
        ok = np.isfinite(r["Q"])
        if ok.sum() == 0:
            continue
        ax.plot(T[ok], r["Q"][ok], color=th["muted"], lw=0.9, alpha=0.8, zorder=2,
                solid_capstyle="round", label="Each official method (see the table)" if first else None)
        first = False
        tops.append(np.nanmax(r["Q"]))

    env = estimates.envelope
    n = env["n_methods"].to_numpy()
    lo, md, hi = (env[c].to_numpy(dtype=float) for c in ("min", "median", "max"))
    band = n >= 2
    blue = th["slots"][_SLOT["official"]]
    if band.any():
        ax.fill_between(T[band], lo[band], hi[band], color=blue, alpha=0.10, lw=0, zorder=1,
                        label="Official range (min–max)")
    has_md = n >= 1
    if has_md.any():
        ax.plot(T[has_md], md[has_md], color=blue, lw=1.6, zorder=3, solid_capstyle="round",
                label="Official median")

    for key in _EMPHASIS:
        try:
            r = estimates.row(key)
        except KeyError:
            continue
        ok = np.isfinite(r["Q"])
        if not ok.any():
            continue
        color = th["slots"][_SLOT[key]]
        name = FLOOD_METHODS[key].name if key in FLOOD_METHODS else r["name"]
        if r.get("band"):
            b = [r["band"].get(fq._tkey(t), (np.nan, np.nan)) for t in T]
            blo = np.array([x[0] for x in b])
            bhi = np.array([x[1] for x in b])
            okb = np.isfinite(blo) & np.isfinite(bhi)
            if okb.sum() > 1:
                ax.fill_between(T[okb], blo[okb], bhi[okb], color=color, alpha=0.10, lw=0,
                                zorder=1, label=f"{name}: confidence band")
                tops.append(np.nanmax(bhi[okb]))
        big = key == "physics"
        ax.plot(T[ok], r["Q"][ok], color=color, lw=1.6, marker="o", ms=8 if big else 6,
                mec=th["surface"], mew=1.5, zorder=5 if big else 4, label=name,
                solid_capstyle="round")
        tops.append(np.nanmax(r["Q"]))
        if big:                                        # the story: label its values
            for t, q in zip(T[ok], r["Q"][ok]):
                ax.annotate(f"{_q(q)} m³/s", (t, q), textcoords="offset points",
                            xytext=(7, 6), fontsize=8.5, color=th["ink"], zorder=6)

    for label, q in observed or ():
        ax.axhline(float(q), color=th["ink2"], lw=1.0, zorder=2)
        ax.annotate(f"{label}: {_q(q)} m³/s", (T.min(), float(q)), textcoords="offset points",
                    xytext=(2, 4), fontsize=8.5, color=th["ink2"])
        tops.append(float(q))

    ax.set_xscale("log")
    ax.xaxis.set_major_locator(FixedLocator(T))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{fq._tkey(round(v, 6))}"))
    ax.xaxis.set_minor_locator(NullLocator())
    ax.set_xlim(T.min() / 1.15, T.max() * 1.15)
    ax.set_ylim(0, (max(tops) if tops else 1.0) * 1.12)
    ax.grid(True, which="major", color=th["grid"], lw=0.8, ls="-", zorder=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(th["axis"])
    ax.tick_params(colors=th["ink2"], labelsize=9)
    ax.set_xlabel("Return period (years)", color=th["ink2"], fontsize=9.5)
    ax.set_ylabel("Peak discharge (m³/s)", color=th["ink2"], fontsize=9.5)
    head = title or "Flood estimates by return period"
    site = estimates.descriptors.name
    ax.set_title(head + (f" — {site}" if site else ""), loc="left", color=th["ink"],
                 fontsize=11, pad=18)
    ax.text(0, 1.015, estimates.descriptors.summary().split(": ", 1)[-1]
            if site else estimates.descriptors.summary(),
            transform=ax.transAxes, fontsize=8.5, color=th["ink2"], va="bottom")
    leg = ax.legend(loc="upper left", fontsize=8.5, frameon=False)
    for text in leg.get_texts():
        text.set_color(th["ink"])
    fig.tight_layout()
    return fig, ax


# ═════════════════════════════════════════════════════════════════════════════
# Markdown report
# ═════════════════════════════════════════════════════════════════════════════
def report_markdown(result):
    """The whole study as a Markdown document."""
    from .. import __version__
    est, desc = result.estimates, result.descriptors
    out = [f"# MRRpy-Nepal flood estimates{' — ' + desc.name if desc.name else ''}", "",
           f"_Written by MRRpy {__version__} on {_dt.date.today().isoformat()}. Formulas and "
           "coefficients from the compendium *Nepal Flood Estimation Methods*; read the notes "
           "before using a number in a design._", ""]

    out += ["## Catchment", "", "| Quantity | Value | Unit |", "|---|---|---|"]
    for _i, row in desc.table().iterrows():
        out.append(f"| {row['quantity']} | {row['value']} | {row['unit']} |")
    for a in desc.assumptions():
        out.append(f"\n- Assumed: {a}.")
    out.append("")

    out += ["## Design basis", ""]
    if result.agency is not None:
        out.append(f"- Methods: **{result.agency.label}**. {result.agency.note}")
        if result.agency.not_yet:
            out.append(f"  Not yet in MRRpy-Nepal: {', '.join(result.agency.not_yet)}.")
    if result.structure is not None:
        out.append(f"- Structure: {result.structure.describe()}.")
    out.append("- Return periods: " + ", ".join(f"{fq._tkey(t)}" for t in est.T) + " years.")
    out.append("")

    out += ["## Flood estimates (m³/s)", "", est.to_markdown(), "",
            "≈ interpolated between tabulated return periods (or design rainfalls); "
            "\\* extrapolated (beyond 100 years, or beyond twice the gauge record); "
            "– not available.", ""]

    env = est.envelope
    out += ["## Official range", "",
            "The regional peak methods that are usable here (status *ok* or *use with "
            "caution*):", "", "| T (years) | Methods | Min | Median | Max | Max ÷ min |",
            "|---|---|---|---|---|---|"]
    for t, e in env.iterrows():
        out.append(f"| {t} | {int(e['n_methods'])} | {_g(e['min'])} | {_g(e['median'])} | "
                   f"{_g(e['max'])} | {_g(e['spread'])} |")
    out.append("")

    if result.physics:
        out += ["## Physics model (MRRpy design storm)", ""]
        comp = est.compare("physics")
        for T, f in sorted(result.physics.items()):
            c = comp.loc[fq._tkey(T)] if fq._tkey(T) in comp.index else None
            line = f"- {f.summary()}."
            if c is not None and c["position"]:
                line += (f" It is **{c['position']}** the official range "
                         f"({_g(c['official_min'])}–{_g(c['official_max'])} m³/s), "
                         f"{_g(c['ratio_to_median'])}× the official median.")
            out.append(line)
            out.append(f"  Files: `{f.folder}`")
        out.append("")

    out += ["## Notes by method", ""]
    for r in est.rows:
        m = FLOOD_METHODS.get(r["key"])
        status = STATUS_TEXT.get(r["status"], r["status"])
        notes = "; ".join(r["notes"])
        notes = notes[:1].upper() + notes[1:] + "." if notes else ""
        out.append(f"- **{r['name']}** ({status}). {notes}".rstrip())
        if m is not None:
            out.append(f"  Formula: {m.formula}. Used by: {m.used_by}.")
            if m.source:
                out.append(f"  Source note: {m.source}")
    out.append("")

    warnings = est.warnings()
    if warnings:
        out += ["## Warnings", ""] + [f"- {w}" for w in warnings] + [""]
    if result.recommendation:
        out += ["## What the compendium recommends for this catchment", ""]
        out += [f"- {w}" for w in result.recommendation] + [""]
    if result.observed:
        out += ["## Observed floods", ""]
        out += [f"- {label}: {float(q):.4g} m³/s" for label, q in result.observed] + [""]
    if result.files:
        out += ["## Files", ""] + [f"- {k}: `{v}`" for k, v in result.files.items()] + [""]
    return "\n".join(out)


def _g(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "–"
    return "–" if not np.isfinite(v) else f"{v:.4g}"


def _q(v):
    """A discharge for a label: 3 significant figures, whole numbers from 100 up."""
    v = float(v)
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:.3g}"
