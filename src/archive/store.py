"""Files-based archive of whole test runs: unique id, metadata, per-ammeter results, comparison."""
import json
import platform
import re
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LATEST = "latest"
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_STATUS_RANK = {"ok": 0, "partial": 1, "failed": 2}
_REQUIRED = ("run_id", "metadata", "results")


def new_run_id(now: Optional[datetime] = None) -> str:
    """`<UTC timestamp>_<uuid8>`: sorts by time and stays unique within the same second."""
    now = now or datetime.now(timezone.utc)
    return f"{now:%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:8]}"


def git_commit(cwd: Path = PROJECT_ROOT) -> Optional[str]:
    """HEAD commit hash, or None without git, outside a repo, or on timeout."""
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(cwd), capture_output=True,
                             text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    commit = out.stdout.strip()
    return commit if out.returncode == 0 and commit else None


def summarize(results: Dict[str, Dict]) -> Dict:
    """Counts across the ammeters of one run."""
    statuses = [r["status"] for r in results.values()]
    samples = sum(len(r.get("samples", [])) for r in results.values())
    errors = sum(r["metadata"].get("error_count", 0) for r in results.values())
    return {"ammeters": len(results), "ok": statuses.count("ok"), "partial": statuses.count("partial"),
            "failed": statuses.count("failed"), "samples": samples, "valid_samples": samples - errors,
            "errors": errors}


def _compact(result: Dict) -> Dict:
    """Result without raw samples; `result_run_id` points at the full per-ammeter file."""
    samples = result.get("samples", [])
    errors = result["metadata"].get("error_count", 0)
    return {"result_run_id": result["run_id"], "ammeter": result["ammeter"], "status": result["status"],
            "start_time": result["metadata"].get("start_time"), "stats": result.get("stats", {}),
            "timing": result.get("timing", {}), "samples": len(samples), "errors": errors}


def _numbers(row: Dict) -> Dict[str, float]:
    """Flat numeric metrics of one archived ammeter result."""
    flat = {f"stats.{k}": v for k, v in row.get("stats", {}).items()}
    flat.update({f"timing.{k}": v for k, v in row.get("timing", {}).items()})
    flat["errors"] = row.get("errors")
    return {k: v for k, v in flat.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


def _delta(a, b) -> Dict:
    d = b - a
    return {"a": a, "b": b, "delta": d, "delta_pct": d / abs(a) * 100 if a else None}


def compare_runs(a: Dict, b: Dict) -> Dict:
    """Diff two archived runs: per-ammeter status change and metric deltas (b relative to a)."""
    ra, rb = a["results"], b["results"]
    ammeters = {}
    for name in sorted(set(ra) & set(rb)):
        x, y = ra[name], rb[name]
        sa, sb = _STATUS_RANK.get(x["status"], 2), _STATUS_RANK.get(y["status"], 2)
        na, nb = _numbers(x), _numbers(y)
        metrics = {k: _delta(na[k], nb[k]) for k in sorted(set(na) & set(nb)) if na[k] != nb[k]}
        ammeters[name] = {
            "status": {"a": x["status"], "b": y["status"]},
            "change": "regressed" if sb > sa else "improved" if sb < sa else "unchanged",
            "metrics": metrics,
        }
    return {"a": a["run_id"], "b": b["run_id"], "ammeters": ammeters,
            "only_in_a": sorted(set(ra) - set(rb)), "only_in_b": sorted(set(rb) - set(ra))}


class RunArchive:
    """One JSON file per run in `directory`, named `<run_id>.json`."""

    def __init__(self, directory):
        self.directory = Path(directory)

    def path_for(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or not _ID_RE.match(run_id):
            raise ValueError(f"Invalid run id {run_id!r}: use letters, digits, '_' and '-' only")
        return self.directory / f"{run_id}.json"

    def record(self, results: Dict[str, Dict], run_id: Optional[str] = None, config: Optional[Dict] = None,
               commit: Callable[[], Optional[str]] = git_commit) -> Dict:
        """Archive one run. `results` maps ammeter name -> result from the framework."""
        run_id = run_id or new_run_id()
        path = self.path_for(run_id)
        if path.exists():
            raise FileExistsError(f"Run '{run_id}' is already archived")
        now = self._monotonic_now()
        entry = {
            "run_id": run_id,
            "metadata": {
                "timestamp": now.isoformat(),
                "platform": platform.platform(),
                "os": platform.system(),
                "python": platform.python_version(),
                "git_commit": commit(),
                "config": config or {},
                "summary": summarize(results),
            },
            "results": {name: _compact(r) for name, r in results.items()},
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entry, indent=2), encoding="utf-8")
        tmp.replace(path)
        return entry

    def list(self) -> List[Dict]:
        """Run summaries (run_id, timestamp, commit, summary), oldest first. Corrupt files are skipped."""
        rows = []
        for p in self.directory.glob("*.json") if self.directory.exists() else []:
            try:
                e = self._read(p)
            except (OSError, ValueError):
                continue
            m = e["metadata"]
            rows.append({"run_id": e["run_id"], "timestamp": m.get("timestamp", ""),
                         "git_commit": m.get("git_commit"), "summary": m.get("summary", {})})
        return sorted(rows, key=lambda r: (r["timestamp"], r["run_id"]))

    def load(self, run_id: str) -> Dict:
        """Load by id, or `latest` for the newest run."""
        if run_id == LATEST:
            rows = self.list()
            if not rows:
                raise FileNotFoundError(f"No archived runs in {self.directory}")
            run_id = rows[-1]["run_id"]
        path = self.path_for(run_id)
        if not path.exists():
            raise FileNotFoundError(f"No archived run '{run_id}' in {self.directory}")
        return self._read(path)

    def compare(self, run_a: str, run_b: str) -> Dict:
        return compare_runs(self.load(run_a), self.load(run_b))

    def _monotonic_now(self) -> datetime:
        # Guarantee strictly-increasing metadata.timestamp per archive dir so `latest` is deterministic
        # even on coarse-tick clocks (e.g. Windows ~15 ms).
        now = datetime.now(timezone.utc)
        latest = max((r["timestamp"] for r in self.list()), default="")
        if latest and now.isoformat() <= latest:
            try:
                return datetime.fromisoformat(latest) + timedelta(microseconds=1)
            except ValueError:
                pass
        return now

    @staticmethod
    def _read(path: Path) -> Dict:
        try:
            e = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(e, dict) or any(k not in e for k in _REQUIRED):
                raise ValueError("missing run_id/metadata/results")
            if not isinstance(e["metadata"], dict) or not isinstance(e["results"], dict):
                raise ValueError("metadata and results must be objects")
        except ValueError as err:  # includes JSONDecodeError and UnicodeDecodeError
            raise ValueError(f"Corrupt archive file {path}: {err}") from err
        return e
