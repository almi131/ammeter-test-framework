"""Unified, config-driven test framework for the ammeter emulators."""
import json
import math
import platform
import random
import statistics
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from Ammeters.client import (
    DEFAULT_TIMEOUT, AmmeterConnectionError, AmmeterTimeoutError, request_current_from_ammeter)
from src.utils.config import ConfigError, check_name, load_config, section
from src.utils.logger import TestLogger

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_DIR = "results/runs"
SPIN_WINDOW_S = 0.002  # sleep coarsely, then busy-wait the last bit for accuracy
# In-process reader: last actual_s stays within this of the schedule. TCP reads may be later.
TIMING_TOLERANCE_S = 0.05
_SIM_MODES = ("connection_failure", "timeout", "invalid_response", "intermittent_failure")


def _resolve(path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p


# ---------------------------------------------------------------- sampling

def _check_positive(label: str, v) -> None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
        raise ConfigError(f"{label} must be a positive number, got {v!r}")


@dataclass(frozen=True)
class SamplingPlan:
    count: int
    duration_s: float
    frequency_hz: float

    @property
    def interval_s(self) -> float:
        return 1.0 / self.frequency_hz

    @classmethod
    def from_config(cls, cfg: Optional[dict]) -> "SamplingPlan":
        """Needs >= 2 of 3 values. Window [0, duration), samples at i/frequency, count = ceil(duration*f)."""
        if cfg is None:
            cfg = {}
        if not isinstance(cfg, dict):
            raise ConfigError(f"sampling must be a mapping, got {type(cfg).__name__}")
        count = cfg.get("measurements_count")
        duration = cfg.get("total_duration_seconds")
        freq = cfg.get("sampling_frequency_hz")

        for name, v in (("measurements_count", count), ("total_duration_seconds", duration),
                        ("sampling_frequency_hz", freq)):
            if v is None:
                continue
            _check_positive(f"sampling.{name}", v)
        if count is not None and int(count) != count:
            raise ConfigError(f"sampling.measurements_count must be an integer, got {count!r}")

        if [count, duration, freq].count(None) > 1:
            raise ConfigError("Sampling needs at least two of: measurements_count, "
                              "total_duration_seconds, sampling_frequency_hz")
        if count is None:
            count = samples_in_window(duration, freq)
        elif freq is None:
            freq = count / duration
        elif duration is None:
            duration = count / freq
        else:
            expected = samples_in_window(duration, freq)
            if count != expected:
                raise ConfigError(
                    f"Inconsistent sampling: window [0, {duration}s) at {freq} Hz holds {expected} "
                    f"measurements, but measurements_count is {count}")
        return cls(int(count), float(duration), float(freq))

    @property
    def last_sample_s(self) -> float:
        return (self.count - 1) * self.interval_s

    def to_dict(self) -> Dict:
        return {"measurements_count": self.count, "total_duration_seconds": self.duration_s,
                "sampling_frequency_hz": self.frequency_hz, "last_sample_s": round(self.last_sample_s, 6)}


def samples_in_window(duration_s, frequency_hz) -> int:
    """Samples at t_i = i/f inside the half-open window [0, duration): ceil(duration * f).
    Fractions of the decimal text avoid float noise (0.3 * 10 = 3.0000000000000004)."""
    return math.ceil(Fraction(str(duration_s)) * Fraction(str(frequency_hz)))


# ---------------------------------------------------------------- statistics

def _stdev(v: List[float]) -> float:
    return statistics.stdev(v) if len(v) > 1 else 0.0  # sample std dev (n-1)


METRICS: Dict[str, Callable[[List[float]], float]] = {
    "mean": statistics.fmean,
    "median": statistics.median,
    "std_dev": _stdev,
    "min": min,
    "max": max,
}


def check_metrics(names) -> None:
    if not isinstance(names, list):
        raise ConfigError(f"statistical_metrics must be a list, got {names!r}")
    unknown = [m for m in names if m not in METRICS]
    if unknown:
        raise ConfigError(f"Unknown statistical metrics: {unknown}; available: {list(METRICS)}")


def compute_stats(values: List[float], metrics: Optional[List[str]] = None) -> Dict:
    """Requested metrics plus count. None means every metric. An empty list means count only.

    relative_spread (std/|mean|) is added whenever at least one metric is computed.
    """
    if metrics is not None:
        check_metrics(metrics)  # reject unknown names even when there are no samples
    if not values:
        return {"count": 0}
    names = list(METRICS) if metrics is None else list(metrics)
    stats = {"count": len(values)}
    if not names:
        return stats
    stats.update({m: METRICS[m](values) for m in names})
    mean, std = statistics.fmean(values), _stdev(values)
    stats["relative_spread"] = std / abs(mean) if mean else None
    return stats


def reference_error(mean: Optional[float], reference: float) -> Tuple[Optional[float], Optional[str]]:
    """relative_error = (mean - reference) / reference. Zero reference is undefined, not an exception."""
    if reference == 0:
        return None, "reference_current_a is 0; relative error is undefined"
    if mean is None:
        return None, "no valid measurements; relative error is undefined"
    return (mean - reference) / reference, None


def _attach_reference(stats: Dict, reference: Optional[float]) -> None:
    if reference is None:
        return  # no reference configured: do not emit an accuracy claim
    err, note = reference_error(stats.get("mean"), reference)
    stats["relative_error"] = err
    if note:
        stats["relative_error_note"] = note


def _parse_reference(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ConfigError(f"testing.reference_current_a must be a finite number, got {value!r}")
    return float(value)


def _parse_error_simulation(raw) -> Optional[Dict]:
    """None when the section is absent or enabled is false (normal runs stay unchanged)."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(f"testing.error_simulation must be a mapping, got {type(raw).__name__}")
    if raw.get("enabled") is not True:
        return None
    seed = raw.get("seed", 0)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ConfigError(f"testing.error_simulation.seed must be an integer, got {seed!r}")
    parsed = {"seed": seed}
    for mode in _SIM_MODES:
        if mode not in raw:
            continue
        value = raw[mode]
        if isinstance(value, bool):
            parsed[mode] = value
        elif isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 1:
            parsed[mode] = float(value)
        else:
            raise ConfigError(
                f"testing.error_simulation.{mode} must be a bool or a rate in 0..1, got {value!r}")
    return parsed


def _sim_fires(spec, rng: random.Random) -> bool:
    if spec is None or spec is False or spec == 0:
        return False
    if spec is True or spec == 1:
        return True
    return rng.random() < spec


def _wrap_reader(read: Callable[[], float], sim: Dict) -> Callable[[], float]:
    """Each run restarts from sim['seed']. The first matching mode wins for that sample."""
    rng = random.Random(sim["seed"])

    def wrapped():
        if _sim_fires(sim.get("connection_failure"), rng):
            raise AmmeterConnectionError("simulated connection failure")
        if _sim_fires(sim.get("timeout"), rng):
            raise AmmeterTimeoutError("simulated timeout")
        if _sim_fires(sim.get("invalid_response"), rng):
            return float("nan")  # existing non-finite path records a per-sample error
        if _sim_fires(sim.get("intermittent_failure"), rng):
            raise AmmeterConnectionError("simulated intermittent failure")
        return read()

    return wrapped


# ---------------------------------------------------------------- ammeters

@dataclass
class AmmeterSpec:
    name: str
    port: int
    command: str
    host: str = "localhost"

    @classmethod
    def from_config(cls, name: str, cfg: dict) -> "AmmeterSpec":
        check_name(name)
        if not isinstance(cfg, dict):
            raise ConfigError(f"ammeters.{name} must be a mapping, got {type(cfg).__name__}")
        missing = [k for k in ("port", "command") if k not in cfg]
        if missing:
            raise ConfigError(f"ammeters.{name} is missing: {missing}")
        port, command, host = cfg["port"], cfg["command"], cfg.get("host", "localhost")
        if isinstance(port, float) and port.is_integer():
            port = int(port)
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ConfigError(f"ammeters.{name}.port must be an integer in 1..65535, got {port!r}")
        if not isinstance(command, str) or not command.strip():
            raise ConfigError(f"ammeters.{name}.command must be a non-empty string, got {command!r}")
        if not isinstance(host, str) or not host.strip():
            raise ConfigError(f"ammeters.{name}.host must be a non-empty string, got {host!r}")
        return cls(name, port, command, host)

    def meta(self) -> Dict:
        return {"host": self.host, "port": self.port, "command": self.command}


class ResultStore:
    """JSON-file archive: one file per run, named <run_id>.json."""

    def __init__(self, directory):
        self.directory = _resolve(directory)

    def path_for(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or not run_id or ".." in run_id or "/" in run_id or "\\" in run_id:
            raise ValueError(f"Invalid run id {run_id!r}: must not be empty or contain '..' or path separators")
        return self.directory / f"{run_id}.json"

    def save(self, result: Dict) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(result["run_id"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, indent=2), encoding="utf-8")
        tmp.replace(path)
        return path

    def load(self, run_id: str) -> Dict:
        path = self.path_for(run_id)
        if not path.exists():
            raise FileNotFoundError(f"No saved run '{run_id}' in {self.directory}")
        return self._read(path)

    @staticmethod
    def _read(path: Path) -> Dict:
        """Parse a result file; anything unreadable or lacking the core keys is a ValueError."""
        try:
            r = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(r, dict) or not isinstance(r.get("metadata"), dict)
                    or not isinstance(r.get("stats"), dict)):
                raise ValueError("not a result object")
            for key in ("run_id", "ammeter", "status", "samples"):
                if key not in r:
                    raise ValueError(f"missing key '{key}'")
            if "start_time" not in r["metadata"]:
                raise ValueError("missing key 'metadata.start_time'")
        except ValueError as e:  # includes JSONDecodeError and UnicodeDecodeError
            raise ValueError(f"Corrupt result file {path}: {e}") from e
        return r

    def list(self, ammeter: Optional[str] = None) -> List[Dict]:
        """Run summaries (without samples), oldest first."""
        rows = []
        for p in self.directory.glob("*.json") if self.directory.exists() else []:
            try:
                r = self._read(p)
            except (OSError, ValueError):
                continue  # skip foreign/corrupt files
            row = {"run_id": r["run_id"], "ammeter": r["ammeter"], "status": r["status"],
                   "start_time": r["metadata"]["start_time"], "stats": r["stats"]}
            if ammeter is None or row["ammeter"] == ammeter:
                rows.append(row)
        return sorted(rows, key=lambda r: r["start_time"])


# ---------------------------------------------------------------- framework

class AmmeterTestFramework:
    def __init__(self, config_path: str = "config/config.yaml", config: Optional[Dict] = None,
                 results_dir: Optional[str] = None, clock: Optional[Callable[[], float]] = None):
        if config is None:
            path = Path(config_path)
            if not path.is_absolute() and not path.exists():
                path = PROJECT_ROOT / path
            config = load_config(str(path))
        if not isinstance(config, dict):
            raise ConfigError(f"Config must be a mapping, got {type(config).__name__}")
        self.config = config
        testing = section(config, "testing")
        self.default_sampling = testing.get("sampling")
        if self.default_sampling is not None and not isinstance(self.default_sampling, dict):
            raise ConfigError(f"testing.sampling must be a mapping, got {type(self.default_sampling).__name__}")
        timeout = testing.get("client_timeout_seconds")
        if timeout is None:
            timeout = DEFAULT_TIMEOUT
        _check_positive("testing.client_timeout_seconds", timeout)
        self.timeout = float(timeout)
        self._clock = clock  # None -> time.perf_counter. A test clock may implement advance_to(deadline).
        self.reference_current_a = _parse_reference(testing.get("reference_current_a"))
        self.error_simulation = _parse_error_simulation(testing.get("error_simulation"))
        analysis = section(config, "analysis")
        if "statistical_metrics" in analysis:
            self.metrics = analysis["statistical_metrics"]
            check_metrics(self.metrics)  # [] is count-only; unknown names fail before sampling
        else:
            self.metrics = None

        self.specs: Dict[str, AmmeterSpec] = {}
        self._readers: Dict[str, Callable[[], float]] = {}
        self._custom_meta: Dict[str, Dict] = {}
        for name, cfg in section(config, "ammeters").items():
            self._register_spec(AmmeterSpec.from_config(name, cfg))

        rm = section(config, "result_management")
        self.store = ResultStore(results_dir or rm.get("results_dir") or DEFAULT_RESULTS_DIR)
        self.logger = TestLogger("framework", log_dir=str(self.store.directory / "logs"))

    # -- registry
    def _register_spec(self, spec: AmmeterSpec) -> None:
        self.specs[spec.name] = spec
        command = spec.command.encode("utf-8")
        self._readers[spec.name] = lambda: request_current_from_ammeter(
            spec.port, command, host=spec.host, timeout=self.timeout, verbose=False)

    def register_ammeter(self, name: str, reader: Callable[[], float], meta: Optional[Dict] = None) -> None:
        """Add a custom ammeter: any zero-arg callable returning a float (raise on failure)."""
        check_name(name)
        self._readers[name] = reader  # re-registering a name replaces the earlier reader
        self.specs.pop(name, None)
        self._custom_meta[name] = meta or {}

    @property
    def ammeter_names(self) -> List[str]:
        return list(self._readers)

    def _meta_for(self, name: str) -> Dict:
        if name in self.specs:
            return self.specs[name].meta()
        return self._custom_meta.get(name, {})

    # -- running
    def plan_for(self, sampling: Optional[Dict] = None) -> SamplingPlan:
        return SamplingPlan.from_config(sampling if sampling is not None else self.default_sampling)

    def run_test(self, ammeter_type: str, sampling: Optional[Dict] = None, save: bool = True) -> Dict:
        if ammeter_type not in self._readers:
            raise ConfigError(f"Unknown ammeter '{ammeter_type}'; available: {self.ammeter_names}")
        plan = self.plan_for(sampling)
        read = self._readers[ammeter_type]
        if self.error_simulation:
            read = _wrap_reader(read, self.error_simulation)

        start_dt = datetime.now(timezone.utc)
        run_id = f"{ammeter_type}_{start_dt:%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:8]}"
        self.logger.info(f"[{run_id}] start: {plan.to_dict()}")

        samples = self._collect(read, plan, run_id)
        end_dt = datetime.now(timezone.utc)

        values = [s["value"] for s in samples if s["error"] is None]
        errors = [{"index": s["index"], "error": s["error"]} for s in samples if s["error"]]
        jitter = [s["actual_s"] - s["scheduled_s"] for s in samples]
        late = sum(j > plan.interval_s for j in jitter)
        if late:
            self.logger.warning(f"[{run_id}] {late}/{len(samples)} samples were late "
                                f"(read slower than the {plan.interval_s * 1000:.1f} ms interval)")
        status = "ok" if not errors else ("failed" if not values else "partial")
        stats = compute_stats(values, self.metrics)
        _attach_reference(stats, self.reference_current_a)
        run_cfg = {**self._meta_for(ammeter_type), "sampling": plan.to_dict(),
                   "client_timeout_seconds": self.timeout}
        if self.reference_current_a is not None:
            run_cfg["reference_current_a"] = self.reference_current_a

        result = {
            "run_id": run_id,
            "ammeter": ammeter_type,
            "status": status,
            "metadata": {
                "start_time": start_dt.isoformat(),
                "end_time": end_dt.isoformat(),
                "elapsed_s": round((end_dt - start_dt).total_seconds(), 6),
                "config": run_cfg,
                "error_count": len(errors),
                "errors": errors,
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
            "stats": stats,
            "timing": {
                "mean_jitter_ms": round(statistics.fmean(jitter) * 1000, 3),
                "max_abs_jitter_ms": round(max(abs(j) for j in jitter) * 1000, 3),
                "late_samples": int(late),
            },
            "samples": samples,
        }
        if self.error_simulation:
            result["metadata"]["error_simulation"] = dict(self.error_simulation)
        if save:
            try:
                path = self.store.save(result)
                self.logger.info(f"[{run_id}] saved to {path}")
            except OSError as e:  # keep the measurements even if they can't be archived
                result["metadata"]["save_error"] = f"{type(e).__name__}: {e}"
                self.logger.error(f"[{run_id}] could not save result: {e}")
        self.logger.info(f"[{run_id}] done: status={status}, errors={len(errors)}")
        return result

    def _now(self) -> float:
        return self._clock() if self._clock is not None else time.perf_counter()

    def _collect(self, read: Callable[[], float], plan: SamplingPlan, run_id: str) -> List[Dict]:
        """Sample on an absolute schedule (t0 + i*interval) so delays never accumulate."""
        samples = []
        t0 = self._now()
        for i in range(plan.count):
            target = i * plan.interval_s
            self._wait_until(t0 + target)
            began = self._now()
            sample = {"index": i, "scheduled_s": round(target, 6),
                      "actual_s": round(began - t0, 6), "value": None, "error": None}
            try:
                value = float(read())
                if not math.isfinite(value):
                    raise ValueError(f"Non-finite measurement: {value!r}")
                sample["value"] = value
            except Exception as e:  # a failed sample must not abort the run
                sample["error"] = f"{type(e).__name__}: {e}"
                self.logger.warning(f"[{run_id}] sample {i} failed: {sample['error']}")
            sample["latency_ms"] = round((self._now() - began) * 1000, 3)
            samples.append(sample)
        return samples

    def _wait_until(self, deadline: float) -> None:
        if self._clock is not None:
            advance_to = getattr(self._clock, "advance_to", None)
            if advance_to is not None:
                advance_to(deadline)  # unit tests jump to the sample time instead of sleeping
            return
        remaining = deadline - time.perf_counter()
        if remaining > SPIN_WINDOW_S:
            time.sleep(remaining - SPIN_WINDOW_S)
        while time.perf_counter() < deadline:
            pass

    def run_all(self, names: Optional[List[str]] = None, sampling: Optional[Dict] = None) -> Dict[str, Dict]:
        """names=None runs every ammeter; an explicit empty list is an error. Validates before running."""
        names = self.ammeter_names if names is None else list(names)
        if not names:
            raise ConfigError("no ammeters selected")
        unknown = [n for n in names if n not in self._readers]
        if unknown:
            raise ConfigError(f"Unknown ammeter(s) {unknown}; available: {self.ammeter_names}")
        self.plan_for(sampling)  # fail fast on bad sampling config
        return {n: self.run_test(n, sampling) for n in names}

    # -- history
    def load_result(self, run_id: str) -> Dict:
        return self.store.load(run_id)

    def list_results(self, ammeter: Optional[str] = None) -> List[Dict]:
        return self.store.list(ammeter)

    def compare_runs(self, run_ids: List[str]) -> List[Dict]:
        """Side-by-side stats. mean_delta_pct vs the first run, only for runs of the same ammeter."""
        rows = []
        for rid in run_ids:
            r = self.load_result(rid)
            rows.append({"run_id": rid, "ammeter": r["ammeter"], "status": r["status"],
                         "start_time": r["metadata"]["start_time"], **r["stats"]})
        base = rows[0].get("mean") if rows else None
        for row in rows:
            m = row.get("mean")
            comparable = row["ammeter"] == rows[0]["ammeter"] and m is not None and base
            row["mean_delta_pct"] = (m - base) / abs(base) * 100 if comparable else None
        return rows

    @staticmethod
    def compare_ammeters(results: Dict[str, Dict], reference_current_a: Optional[float] = None) -> List[Dict]:
        """Rank by precision, or by accuracy when a nonzero reference exists.

        Without a usable relative error, rank is relative_spread (lowest = most consistent).
        With a finite nonzero reference, rank is |relative_error| (lowest = closest to the reference).
        relative_spread stays on every row either way. A zero reference cannot be ranked as accuracy.
        success_rate is valid samples over attempts. It is reported and does not change the rank.
        """
        rows = []
        for name, r in results.items():
            s = r["stats"]
            n = len(r["samples"])
            row = {"ammeter": name, "relative_spread": s.get("relative_spread"),
                   "mean": s.get("mean"), "std_dev": s.get("std_dev"),
                   "error_rate": r["metadata"]["error_count"] / n if n else None,
                   "success_rate": (s.get("count") or 0) / n if n else None}
            ref = reference_current_a
            if ref is None and "relative_error" in s:
                row["relative_error"] = s.get("relative_error")
                if s.get("relative_error_note"):
                    row["relative_error_note"] = s["relative_error_note"]
            elif ref is not None:
                err, note = reference_error(s.get("mean"), ref)
                row["relative_error"] = err
                if note:
                    row["relative_error_note"] = note
            rows.append(row)
        by_accuracy = any(row.get("relative_error") is not None for row in rows)
        if by_accuracy:
            rows.sort(key=lambda x: (
                x.get("relative_error") is None,
                abs(x["relative_error"]) if x.get("relative_error") is not None else 0,
            ))
            ranked_by = "abs_relative_error"
        else:
            rows.sort(key=lambda x: (x["relative_spread"] is None, x["relative_spread"] or 0))
            ranked_by = "relative_spread"
        for rank, row in enumerate(rows, 1):
            row["rank"] = rank
            row["ranked_by"] = ranked_by
        return rows


# ---------------------------------------------------------------- reporting

def _fmt(v, spec=".4f") -> str:
    return "-" if v is None else format(v, spec)


def format_report(result: Dict) -> str:
    m, s, t = result["metadata"], result["stats"], result["timing"]
    cfg = m["config"]["sampling"]
    lines = [
        f"=== {result['ammeter'].upper()}  [{result['status']}]  run_id={result['run_id']}",
        f"  sampling : {cfg['measurements_count']} samples, {cfg['total_duration_seconds']}s, "
        f"{cfg['sampling_frequency_hz']} Hz   elapsed={m['elapsed_s']}s",
        f"  errors   : {m['error_count']}",
        f"  timing   : mean jitter {t['mean_jitter_ms']} ms, max |jitter| {t['max_abs_jitter_ms']} ms, "
        f"late samples {t.get('late_samples', 0)}",
    ]
    if s["count"]:
        lines.append(f"  stats (A): n={s['count']}  mean={_fmt(s.get('mean'))}  median={_fmt(s.get('median'))}  "
                     f"std={_fmt(s.get('std_dev'))}  min={_fmt(s.get('min'))}  max={_fmt(s.get('max'))}  "
                     f"rel.spread={_fmt(s.get('relative_spread'), '.3f')}")
    else:
        lines.append("  stats    : no valid samples")
    if "relative_error" in s:
        if s.get("relative_error_note"):
            lines.append(f"  accuracy : {s['relative_error_note']}")
        else:
            lines.append(f"  accuracy : relative_error={_fmt(s.get('relative_error'))} "
                         f"(reference {m['config'].get('reference_current_a')} A)")
    for e in m["errors"][:5]:
        lines.append(f"  ! sample {e['index']}: {e['error']}")
    return "\n".join(lines)


def select_winners(rows: List[Dict], *, has_reference: Optional[bool] = None) -> Dict[str, Optional[Dict]]:
    """Pick precision/accuracy/reliability winners from `compare_ammeters` rows.

    Display-only summary; does not change ranking. Zero-count rows are excluded from
    precision and accuracy. All-zero reliability yields no reliability winner. Ties
    (within math.isclose rel_tol=1e-9, abs_tol=1e-12) list every tied ammeter.
    """
    if has_reference is None:
        has_reference = any(r.get("relative_error") is not None for r in rows)

    def _tied(candidates, key):
        best = key(candidates[0])
        return [c for c in candidates if math.isclose(key(c), best, rel_tol=1e-9, abs_tol=1e-12)]

    winners: Dict[str, Optional[Dict]] = {"precision": None, "accuracy": None, "reliability": None}

    precision_candidates = [r for r in rows if r.get("relative_spread") is not None]
    if precision_candidates:
        sorted_p = sorted(precision_candidates, key=lambda r: r["relative_spread"])
        tied = _tied(sorted_p, lambda r: r["relative_spread"])
        winners["precision"] = {
            "ammeters": [r["ammeter"] for r in tied],
            "value": tied[0]["relative_spread"],
            "metric": "relative_spread",
        }

    if has_reference:
        accuracy_candidates = [r for r in rows if r.get("relative_error") is not None]
        if accuracy_candidates:
            sorted_a = sorted(accuracy_candidates, key=lambda r: abs(r["relative_error"]))
            tied = _tied(sorted_a, lambda r: abs(r["relative_error"]))
            winners["accuracy"] = {
                "ammeters": [r["ammeter"] for r in tied],
                "value": abs(tied[0]["relative_error"]),
                "metric": "abs_relative_error",
            }

    reliability_candidates = [r for r in rows if r.get("success_rate") is not None]
    if reliability_candidates:
        sorted_r = sorted(reliability_candidates, key=lambda r: -r["success_rate"])
        if sorted_r[0]["success_rate"] > 0.0:
            tied = _tied(sorted_r, lambda r: r["success_rate"])
            winners["reliability"] = {
                "ammeters": [r["ammeter"] for r in tied],
                "value": tied[0]["success_rate"],
                "metric": "success_rate",
            }
    return winners


_WINNER_LABELS = {
    "precision": "most precise",
    "accuracy": "most accurate",
    "reliability": "most reliable communication",
}
_WINNER_METRIC_LABELS = {
    "relative_spread": "relative_spread",
    "abs_relative_error": "|rel.error|",
    "success_rate": "success_rate",
}


def _format_winner_value(metric: str, value: float) -> str:
    if metric == "success_rate":
        return format(value, ".1%")
    return format(value, ".3f")


def format_ammeter_comparison(rows: List[Dict]) -> str:
    show_acc = any("relative_error" in r for r in rows)
    if rows and rows[0].get("ranked_by") == "abs_relative_error":
        title = "Ammeter comparison (ranked by |relative error|; lower is closer to the reference):"
    else:
        title = "Ammeter comparison (ranked by relative spread; lower is more consistent, not more accurate):"
    header = f"  {'rank':<5}{'ammeter':<10}{'rel.spread':>11}{'success':>10}"
    if show_acc:
        header += f"{'rel.err':>10}"
    header += f"{'mean (A)':>11}{'std (A)':>11}{'err rate':>10}"
    lines = [title, header]
    for r in rows:
        line = (f"  {r['rank']:<5}{r['ammeter']:<10}{_fmt(r['relative_spread'], '.3f'):>11}"
                f"{_fmt(r.get('success_rate'), '.1%'):>10}")
        if show_acc:
            line += f"{_fmt(r.get('relative_error')):>10}"
        line += f"{_fmt(r['mean']):>11}{_fmt(r['std_dev']):>11}{_fmt(r['error_rate'], '.1%'):>10}"
        lines.append(line)
    for r in rows:
        if r.get("relative_error_note"):
            lines.append(f"  {r['ammeter']}: {r['relative_error_note']}")

    winners = select_winners(rows, has_reference=show_acc)
    shown = [(cat, w) for cat, w in winners.items() if w is not None]
    if shown:
        label_width = max(len(_WINNER_LABELS[cat]) for cat, _ in shown)
        lines.append("Winners:")
        for cat, w in shown:
            names = ", ".join(w["ammeters"])
            metric_label = _WINNER_METRIC_LABELS[w["metric"]]
            value_str = _format_winner_value(w["metric"], w["value"])
            lines.append(f"  {_WINNER_LABELS[cat]:<{label_width}} : {names} ({metric_label}={value_str})")

    return "\n".join(lines)


def format_run_comparison(rows: List[Dict]) -> str:
    lines = [f"  {'run_id':<36}{'mean':>10}{'median':>10}{'std':>10}{'min':>10}{'max':>10}{'d_mean%':>9}"]
    for r in rows:
        lines.append(f"  {r['run_id']:<36}{_fmt(r.get('mean')):>10}{_fmt(r.get('median')):>10}"
                     f"{_fmt(r.get('std_dev')):>10}{_fmt(r.get('min')):>10}{_fmt(r.get('max')):>10}"
                     f"{_fmt(r.get('mean_delta_pct'), '.1f'):>9}")
    return "\n".join(lines)
