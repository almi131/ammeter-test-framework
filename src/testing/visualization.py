"""Optional plots; matplotlib is not required for the framework."""
from pathlib import Path
from typing import Dict, List, Optional

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:  # optional dependency
    plt = None


def plot_results(results: Dict[str, Dict], path, plot_types: Optional[List[str]] = None) -> Optional[Path]:
    """Save independently scaled plots per meter (amperage ranges differ greatly)."""
    if plt is None:
        return None
    plot_types = plot_types or ["time_series", "boxplot"]
    if not results or not plot_types:
        return None

    fig, axes = plt.subplots(
        len(results), len(plot_types),
        figsize=(6 * len(plot_types), 3.5 * len(results)),
        squeeze=False,
    )
    for row, (name, result) in enumerate(results.items()):
        valid = [s for s in result["samples"] if s["value"] is not None]
        values = [s["value"] for s in valid]
        for col, kind in enumerate(plot_types):
            ax = axes[row][col]
            if kind == "time_series":
                if valid:
                    ax.plot([s["actual_s"] for s in valid], values, marker="o", ms=3)
                else:
                    ax.text(0.5, 0.5, "No valid samples", ha="center", va="center",
                            transform=ax.transAxes)
                ax.set(xlabel="time (s)", ylabel="current (A)",
                       title=f"{name.upper()} – current over time")
            elif kind == "boxplot":
                if values:
                    ax.boxplot([values])
                    ax.set_xticklabels([name])
                else:
                    ax.text(0.5, 0.5, "No valid samples", ha="center", va="center",
                            transform=ax.transAxes)
                ax.set(ylabel="current (A)", title=f"{name.upper()} – distribution")
            else:
                ax.text(0.5, 0.5, f"Unknown plot type: {kind}", ha="center", va="center",
                        transform=ax.transAxes)
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path
