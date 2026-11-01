# Ammeter Emulators & Test Framework

[![tests](https://github.com/almi131/ammeter-test-framework/actions/workflows/tests.yml/badge.svg)](https://github.com/almi131/ammeter-test-framework/actions/workflows/tests.yml)

Config-driven framework for three TCP ammeter emulators (Greenlee, ENTES, CIRCUTOR). It samples them on a fixed schedule, computes statistics, archives JSON results, and can compare runs.

Verified by the GitHub Actions matrix on Ubuntu, Windows, and macOS with Python 3.12 (badge above). The code uses only syntax and stdlib features available in Python 3.10+.

Design decisions, the assignment bonuses, and bug-fix explanations: [DESIGN.md](DESIGN.md).

## Project structure

- `main.py` — starts the three emulators, waits until each port accepts a connection, and prints one reading from each.
- `run_framework.py` — starts the emulators, runs every configured meter, prints a report, saves JSON.
- `Ammeters/` — emulator classes and `client.py` (float reading, timeout, typed errors).
- `config/config.yaml` — ports, commands, sampling, analysis, results.
- `src/testing/test_framework.py` — `AmmeterTestFramework`, sampling, statistics, `ResultStore`.
- `src/archive/` — run archive: unique run id, metadata, list/load/compare, CLI (`python -m src.archive`).
- `src/testing/visualization.py` — optional matplotlib plots.
- `src/utils/` — YAML loader, logger.
- `tests/` — pytest suite, one module per area of the test plan (TC-01..TC-37).
- `sample_results/` — real successful run (20 samples at 10 Hz) and `comparison.png`.
- `sample_results/examples/` — deterministic partial failure, complete failure, stats, comparisons, plot.
- `examples/run_tests.py` — short run of all three meters (3 samples at 10 Hz). From the project root: `python examples/run_tests.py`.
- `.github/workflows/tests.yml` — Ubuntu, Windows, and macOS. Each job runs pytest, then `main.py`, then `examples/run_tests.py`.

## Ammeters

| Meter | Port | Command | Method |
|---|---|---|---|
| Greenlee | 5001 | `MEASURE_GREENLEE -get_measurement` | Ohm's law, I = V / R |
| ENTES | 5002 | `MEASURE_ENTES -get_data` | Hall effect, I = B * K |
| CIRCUTOR | 5003 | `MEASURE_CIRCUTOR -get_measurement -current` | Rogowski coil, I = ∫V dt |

`python main.py` starts all three, waits until each port accepts a connection, and prints one reading. `python run_framework.py` uses the same wait, then runs the configured sampling. Use the command strings in the table. Each server accepts one client at a time. Run the commands from the project root. A relative `--results-dir` is saved under the project root, not the shell's current directory.

## Install

```sh
python -m pip install -r requirements.txt
python -m pip install -r requirements-plot.txt
```

`requirements.txt` is PyYAML and pytest. `requirements-plot.txt` is matplotlib, only for `--plot`. A measurement run succeeds without it: `plot_results` returns `None` and the JSON result is still saved. CI installs both files so the visualization test runs.

| Package | Required? | Why |
|---|---|---|
| pyyaml | yes | load `config/config.yaml` |
| pytest | tests only | the automated suite |
| matplotlib | plot only | `--plot` and `plot_results`. Not installed by `requirements.txt` |

## Usage

```sh
python main.py
python run_framework.py
python run_framework.py --count 20 --frequency 10 --plot --results-dir sample_results
python run_framework.py --ammeters entes circutor --duration 5 --frequency 4
python run_framework.py --no-emulators
```

Options: `--config`, `--ammeters`, `--count`, `--duration`, `--frequency`, `--results-dir`, `--no-emulators`, `--plot`, `--verbose`. A sampling flag overrides that one field and keeps the others from the config. If the mix disagrees, fields you did not pass are recalculated. Passing all three with values that disagree is still an error. `--count 3` with the default 10 Hz config takes 3 samples at 10 Hz (duration becomes 0.3 s).

From the project root. `register_ammeter` supplies the readings, so this block does not need the TCP emulators. `greenlee`, `entes`, and `circutor` are already registered from the config; `run_test("entes")` is the same call once that server is accepting connections.

```python
from src.testing.test_framework import (
    AmmeterTestFramework,
    format_ammeter_comparison,
    format_report,
)

fw = AmmeterTestFramework("config/config.yaml", results_dir="results/readme_example")
fw.register_ammeter("steady", lambda: 1.25)
fw.register_ammeter("other", lambda: 2.50)
sampling = {"measurements_count": 4, "sampling_frequency_hz": 10}

steady = fw.run_test("steady", sampling=sampling)
run_id = steady["run_id"]
print(run_id)
print(format_report(steady))

results = {
    "steady": steady,
    "other": fw.run_test("other", sampling=sampling),
}
print(format_ammeter_comparison(fw.compare_ammeters(results)))
print(format_ammeter_comparison(fw.compare_ammeters(results, reference_current_a=1.0)))
```

Exit codes of `run_framework.py`: `0` when every meter is `ok` or `partial`; `1` when a meter is `failed` or a result could not be saved; `2` for a config or usage error.

## Configuration

Sampling needs at least two of `measurements_count`, `total_duration_seconds`, and `sampling_frequency_hz`. If all three are set they must agree. Names match `[A-Za-z0-9_-]+`. Resolution rules are in [DESIGN.md](DESIGN.md).

```yaml
testing:
  sampling:
    measurements_count: 20
    total_duration_seconds: 2.0
    sampling_frequency_hz: 10
  client_timeout_seconds: 3.0
  # Off unless enabled is true. Does nothing when omitted.
  error_simulation:
    enabled: false
    seed: 1
    connection_failure: false   # bool, or a rate 0..1
    timeout: false
    invalid_response: false     # returns NaN
    intermittent_failure: 0.0
  # Omit this to avoid an accuracy claim.
  # reference_current_a: 1.0
```

`reference_current_a` is optional. Error-simulation behavior is in [DESIGN.md](DESIGN.md).

Add a meter under `ammeters:` (host, port, command). To emulate it, add the class to `EMULATORS` in `run_framework.py`.

## Tests

```sh
python -m pytest
python -m pytest -v
python -m pytest --results-list
```

`pytest` prints one progress line per file. `pytest -v` prints each test name and `PASSED` or `FAILED`. `--results-list` adds the same names plus the error line for a failure and the passed/failed totals.

95 tests cover TC-01..TC-37, plus the run archive tests (`tests/test_archive.py`), and regression checks for the CLI sampling override, metric validation, accuracy ranking, the half-open window boundary, three timing checks, and a corrupt result file. TC-06, TC-14, TC-20, TC-32, TC-34, and TC-35 are parameterized. Results go to pytest's `tmp_path`, not `results/`. Real emulator tests start `GreenleeAmmeter`, `EntesAmmeter`, and `CircutorAmmeter` on a free port and stop the thread afterwards.

The half-open window `[0, D)` is checked by `test_half_open_window_excludes_the_end_boundary` in `tests/test_sampling.py`, parametrized over `0.3s @ 10 Hz`, `1 s @ 4 Hz`, and `0.7s @ 10 Hz`. Each case asserts the exact schedule, that the last timestamp is strictly less than `D`, and that `len(samples) == ceil(D * f)`. `test_tc12_sampling_frequency` adds the gap-based check with `measurements_count=4`.

TC-38, TC-39, and TC-40 cover cross-platform verification on Ubuntu, Windows, and macOS. The complete pytest suite and application smoke tests passed on all three platforms through GitHub Actions CI.

## Results

Each run is `<results_dir>/<ammeter>_<UTC timestamp>_<uuid8>.json` (default `results/runs/`). Logs go to `<results_dir>/logs/`. The JSON fields are listed in [DESIGN.md](DESIGN.md).

From the project root. This block saves two runs, loads one archive by its run id, and compares those two runs.

```python
from src.testing.test_framework import AmmeterTestFramework, format_run_comparison

fw = AmmeterTestFramework("config/config.yaml", results_dir="results/readme_example")
readings = iter([1.0, 1.0, 1.0, 1.0, 1.1, 1.1, 1.1, 1.1])
fw.register_ammeter("bench", lambda: next(readings))
sampling = {"measurements_count": 4, "sampling_frequency_hz": 10}

first = fw.run_test("bench", sampling=sampling)
second = fw.run_test("bench", sampling=sampling)
run_id = first["run_id"]

archived = fw.load_result(run_id)
print(archived["run_id"], archived["status"], archived["stats"]["mean"])

saved = fw.list_results("bench")
print([row["run_id"] for row in saved])
history = fw.compare_runs([first["run_id"], second["run_id"]])
print(format_run_comparison(history))
```

`mean_delta_pct` is the change from the first run, and only when both runs are the same ammeter and that first mean is not zero. Otherwise the field is null.

### Run archive

Every `run_all` (so `run_framework.py` and `examples/run_tests.py`) and every saved `run_test` also writes one archive file, `<results_dir>/archive/<run_id>.json` (gitignored with `results/`). The run id is `<UTC timestamp>_<uuid8>`. It holds metadata (timestamp, OS/platform, Python, git commit or null, sampling and ammeter config, summary counts) and a compact result per ammeter (stats, timing, error count, and `result_run_id` of the full per-ammeter file). An archive write failure is logged and does not lose the results.

```sh
python -m src.archive --results-dir results/example list
python -m src.archive --results-dir results/example show latest
python -m src.archive --results-dir results/example compare <run_a> latest
```

`--results-dir` defaults to `results/runs`. In Python: `fw.archive.list()`, `fw.archive.load("latest")`, `fw.archive.compare(a, b)`. Compare reports each ammeter's status change (`regressed`, `improved`, `unchanged`), metric deltas with percent change, and ammeters present in only one run. Tests: `tests/test_archive.py`.

Sample output: [`sample_results/`](sample_results/) (real emulator run and plot). Short deterministic cases, produced by the framework with fake readers: [`sample_results/examples/`](sample_results/examples/).

## Visualization

```sh
python run_framework.py --plot --results-dir sample_results
```

`analysis.visualization.plot_types` selects `time_series` and `boxplot`. Each meter gets its own row and y-axis because the random ranges differ. A meter with no valid samples is labeled and does not crash the plot. Without matplotlib the function returns `None`.

## Known limitations

- The emulators draw random currents. They have no true reference. `relative_spread` is precision (spread), not accuracy.
- `relative_error = (mean - reference) / reference` is stored only when `reference_current_a` is set and not zero. With no reference, the result has no `relative_error` field. A zero reference stores null and a note.
- The comparison table shows `success` (valid samples / attempts) next to precision and, when a reference is set, relative error. Rank does not use that rate. The rule is in [DESIGN.md](DESIGN.md).
- A `Winners:` summary is appended to the comparison report with three categories: most precise ammeter (lowest relative spread), most accurate ammeter (lowest absolute relative error, only shown when a reference is available), and most reliable communication (highest measurement success rate). The reliability category reports communication reliability, not overall measurement quality. The winners are a display-only summary and do not change the ranked table order.
- Servers handle one client at a time.
- Scheduling is best-effort, not hard real-time. A fast in-process reader stays within 50 ms of the schedule (`TIMING_TOLERANCE_S`). TCP latency can be larger and shows up as jitter or `late_samples`. The schedule rule is in [DESIGN.md](DESIGN.md).
- Windows and macOS are verified by the GitHub Actions workflow in [`.github/workflows/tests.yml`](https://github.com/almi131/ammeter-test-framework/actions/workflows/tests.yml); the latest run on all three OSes is green.

## Cross-platform verification

The GitHub Actions workflow in `.github/workflows/tests.yml` runs the pytest suite, `python main.py`, and `python examples/run_tests.py` on `ubuntu-latest`, `windows-latest`, and `macos-latest` with Python 3.12. The latest successful workflow run proves those three commands pass on all three operating systems. See the full run history at https://github.com/almi131/ammeter-test-framework/actions/workflows/tests.yml. The badge at the top of this file reflects the status of `main`.

## Operating systems

| Platform | Status |
|---|---|
| Linux | Verified in GitHub Actions (`ubuntu-latest`, Python 3.12) |
| Windows | Verified in GitHub Actions (`windows-latest`, Python 3.12) |
| macOS | Verified in GitHub Actions (`macos-latest`, Python 3.12) |
