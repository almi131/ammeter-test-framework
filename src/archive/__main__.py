"""CLI: python -m src.archive [--results-dir DIR] list | show RUN | compare RUN_A RUN_B (RUN may be `latest`)."""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

from src.archive.store import PROJECT_ROOT, RunArchive

DEFAULT_RESULTS_DIR = "results/runs"


def _fmt(v) -> str:
    return "-" if v is None else f"{v:.4g}" if isinstance(v, float) else str(v)


def format_list(rows: List[Dict]) -> str:
    if not rows:
        return "No archived runs."
    lines = [f"{'run_id':<30}{'timestamp':<28}{'commit':<10}{'ok':>4}{'part':>5}{'fail':>5}"]
    for r in rows:
        s = r["summary"]
        lines.append(f"{r['run_id']:<30}{r['timestamp'][:26]:<28}{(r['git_commit'] or '-')[:8]:<10}"
                     f"{s.get('ok', 0):>4}{s.get('partial', 0):>5}{s.get('failed', 0):>5}")
    return "\n".join(lines)


def format_comparison(diff: Dict) -> str:
    lines = [f"{diff['a']}  ->  {diff['b']}"]
    for name, d in diff["ammeters"].items():
        lines.append(f"{name}: {d['status']['a']} -> {d['status']['b']} ({d['change']})")
        for key, m in d["metrics"].items():
            pct = "" if m["delta_pct"] is None else f" ({m['delta_pct']:+.2f}%)"
            lines.append(f"    {key:<28}{_fmt(m['a']):>12} -> {_fmt(m['b']):<12}{pct}")
    for label, names in (("only in first", diff["only_in_a"]), ("only in second", diff["only_in_b"])):
        if names:
            lines.append(f"{label}: {', '.join(names)}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.archive", description=__doc__)
    ap.add_argument("--results-dir", default=DEFAULT_RESULTS_DIR,
                    help="results dir; the archive is <results-dir>/archive")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list archived runs")
    show = sub.add_parser("show", help="print one run as JSON")
    show.add_argument("run")
    cmp_ = sub.add_parser("compare", help="diff two runs")
    cmp_.add_argument("run_a")
    cmp_.add_argument("run_b")
    args = ap.parse_args(argv)

    base = Path(args.results_dir)
    archive = RunArchive((base if base.is_absolute() else PROJECT_ROOT / base) / "archive")
    try:
        if args.command == "list":
            print(format_list(archive.list()))
        elif args.command == "show":
            print(json.dumps(archive.load(args.run), indent=2))
        else:
            print(format_comparison(archive.compare(args.run_a, args.run_b)))
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
