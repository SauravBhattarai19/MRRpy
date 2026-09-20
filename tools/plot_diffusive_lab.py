"""Plot saved independent diffusion results; does not rerun the solvers."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    data = json.loads((args.directory/"summary.json").read_text())
    profiles = np.load(args.directory/"profiles.npz")
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    ax = axes[0, 0]
    for method, dt, label in (("radau", None, "Radau reference"),
            ("explicit", .5, "Guarded explicit"), ("newton_tree", .5, "BE, dt = 0.5 s"),
            ("newton_tree", .02, "BE, dt = 0.02 s")):
        key = "flat_dam_"+method+("" if dt is None else f"_{dt}")
        h = profiles[key]
        ax.plot((np.arange(len(h))+.5)*10, h, label=label)
    ax.set(xlabel="Distance (m)", ylabel="Depth (m)", title="Flat reservoir after 5 s", xlim=(30, 150))
    ax.legend(fontsize=8)
    ax = axes[0, 1]
    for name in ("flat_dam", "steep_flat", "contraction", "adverse_step"):
        rows = [r for r in data["results"] if r["case"] == name and r["method"] == "newton_tree"]
        ax.loglog([r["dt_max"] for r in rows], [r["l1_error_m"] for r in rows], "o-", label=name)
    ax.set(xlabel="Maximum implicit timestep (s)", ylabel="Mean depth error vs Radau (m)",
           title="Stable large steps still incur error")
    ax.legend(fontsize=8)
    ax = axes[1, 0]
    rows = data["linear_diffusion"]
    names = ["explicit", "backward_euler", "crank_nicolson", "rannacher_start"]
    ratios = [rows[n]["amplitude_ratio"] for n in names]
    ax.bar(["FE", "BE", "CN", "2 BE half steps"], ratios, color=["#c44e52", "#55a868", "#c44e52", "#55a868"])
    ax.set_yscale("symlog", linthresh=.01)
    ax.set_ylim(-200, .08)
    ax.axhline(0, color="black", linewidth=.8)
    ax.set(ylabel="Signed mode amplification (symlog)", title="Diffusion at Fourier number 10: CN rings")
    for i, v in enumerate(ratios):
        ax.annotate(f"{v:.4g}", (i, v), xytext=(0, 5 if v >= 0 else -14), textcoords="offset points", ha="center")
    ax = axes[1, 1]
    names = ["flat_dam", "contraction", "near_level", "backwater_directed"]
    x = np.arange(len(names))
    for k, method in enumerate(("explicit", "newton_tree")):
        steps = [next(r["steps"] for r in data["results"] if r["case"]==n and r["method"]==method and r["dt_max"]==.5) for n in names]
        ax.bar(x+(k-.5)*.35, steps, .35, label=method)
    ax.set_xticks(x, ["Flat dam", "Contraction", "Near level", "Blocked backwater"], rotation=12)
    ax.set(yscale="log", ylabel="Accepted steps over 5 s", title="Step counts, not equal-accuracy speedups")
    ax.legend(fontsize=8)
    fig.suptitle("Independent diffusion experiments — CPU, 32 cells, closed boundaries", fontsize=14)
    fig.savefig(args.directory/"results.png", dpi=170)
    fig.savefig(args.directory/"results.pdf")


if __name__ == "__main__":
    main()
