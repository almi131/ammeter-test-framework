"""Run a short measurement on each configured ammeter and print the report.

From the project root:

    python examples/run_tests.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from run_framework import sampling_override, start_emulators  # noqa: E402
from src.testing.test_framework import (  # noqa: E402
    AmmeterTestFramework, format_ammeter_comparison, format_report)


def main() -> int:
    fw = AmmeterTestFramework(
        str(ROOT / "config" / "config.yaml"),
        results_dir=str(ROOT / "results" / "example"),
    )
    sampling = sampling_override(fw.default_sampling, count=3, frequency=10)
    start_emulators(fw)
    results = fw.run_all(sampling=sampling)
    for result in results.values():
        print(format_report(result))
        print(f"  saved    : {fw.store.path_for(result['run_id'])}\n")
    print(format_ammeter_comparison(fw.compare_ammeters(results)))
    return 1 if any(result["status"] == "failed" for result in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
