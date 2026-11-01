"""Start the emulators, run the test framework for every configured ammeter, print and save results."""
import argparse
import contextlib
import io
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))  # lets `Ammeters` and `src` import from any cwd

# Windows PowerShell defaults stdout to cp1252, which cannot encode the ohm symbol printed by Greenlee's measure_current.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

from Ammeters.base_ammeter import wait_until_accepting  # noqa: E402
from Ammeters.Circutor_Ammeter import CircutorAmmeter  # noqa: E402
from Ammeters.Entes_Ammeter import EntesAmmeter  # noqa: E402
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter  # noqa: E402
from src.testing.test_framework import (  # noqa: E402
    AmmeterTestFramework, ConfigError, SamplingPlan, format_ammeter_comparison, format_report)
from src.testing.visualization import plot_results  # noqa: E402

EMULATORS = {"greenlee": GreenleeAmmeter, "entes": EntesAmmeter, "circutor": CircutorAmmeter}
_SAMPLING_KEYS = ("measurements_count", "total_duration_seconds", "sampling_frequency_hz")


def sampling_override(base, count=None, duration=None, frequency=None):
    """Replace only the sampling fields given on the CLI, then keep the result consistent.

    Fields left off the command stay from `base`. If that mix disagrees, fields the
    user did not pass are dropped and SamplingPlan derives the missing one. All three
    CLI values, when they disagree with each other, are left for that same check to reject.
    """
    overrides = {}
    if count is not None:
        overrides["measurements_count"] = count
    if duration is not None:
        overrides["total_duration_seconds"] = duration
    if frequency is not None:
        overrides["sampling_frequency_hz"] = frequency
    if not overrides:
        return None
    merged = dict(base or {})
    merged.update(overrides)
    if len(overrides) < 3 and all(merged.get(key) is not None for key in _SAMPLING_KEYS):
        try:
            SamplingPlan.from_config(merged)
        except ConfigError:
            if len(overrides) >= 2:
                merged = dict(overrides)
            else:
                only = next(iter(overrides))
                partner = "sampling_frequency_hz" if only != "sampling_frequency_hz" else "total_duration_seconds"
                if merged.get(partner) is None:
                    partner = next(key for key in _SAMPLING_KEYS if key != only and merged.get(key) is not None)
                merged = {only: overrides[only], partner: merged[partner]}
    return merged


def start_emulators(framework: AmmeterTestFramework) -> None:
    for name, spec in framework.specs.items():
        cls = EMULATORS.get(name)
        if cls:
            threading.Thread(target=cls(spec.port).start_server, daemon=True).start()
    for spec in framework.specs.values():
        wait_until_accepting(spec.host, spec.port, name=spec.name)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="config/config.yaml")
    ap.add_argument("--ammeters", nargs="+", help="subset to test (default: all in config)")
    ap.add_argument("--count", type=int, help="override measurements_count")
    ap.add_argument("--duration", type=float, help="override total_duration_seconds")
    ap.add_argument("--frequency", type=float, help="override sampling_frequency_hz")
    ap.add_argument("--results-dir", help="override result_management.results_dir")
    ap.add_argument("--no-emulators", action="store_true", help="use already running servers")
    ap.add_argument("--plot", action="store_true", help="save a plot (needs matplotlib)")
    ap.add_argument("--verbose", action="store_true", help="show emulator output")
    args = ap.parse_args(argv)

    try:
        fw = AmmeterTestFramework(args.config, results_dir=args.results_dir)
        sampling = sampling_override(fw.default_sampling, args.count, args.duration, args.frequency)
        names = args.ammeters or fw.ammeter_names
        fw.plan_for(sampling)

        quiet = contextlib.nullcontext() if args.verbose else contextlib.redirect_stdout(io.StringIO())
        with quiet:  # emulators print on every request
            if not args.no_emulators:
                start_emulators(fw)
            results = fw.run_all(names, sampling)
    except (ConfigError, RuntimeError, OSError) as e:  # OSError: missing config, unusable results dir
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    unsaved = []
    for r in results.values():
        print(format_report(r))
        err = r["metadata"].get("save_error")
        if err:
            unsaved.append(r["run_id"])
            print(f"  WARNING  : result NOT saved ({err})\n", file=sys.stderr)
        else:
            print(f"  saved    : {fw.store.path_for(r['run_id'])}\n")
    print(format_ammeter_comparison(fw.compare_ammeters(results)))
    if fw.last_archive_id:
        print(f"\nArchived run: {fw.last_archive_id}  (python -m src.archive list)")

    viz = (fw.config.get("analysis") or {}).get("visualization") or {}
    if args.plot and viz.get("enabled", True):
        out = plot_results(results, fw.store.directory / "comparison.png", viz.get("plot_types"))
        print(f"\nPlot saved: {out}" if out else "\nPlot skipped: matplotlib not installed")

    # 0 = ok, 1 = a meter failed completely or a result could not be saved, 2 = config/usage error
    return 1 if unsaved or any(r["status"] == "failed" for r in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
