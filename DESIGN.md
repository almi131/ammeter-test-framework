# Design decisions

How the framework is built, and which original defects were fixed. How to run it is in [README.md](README.md).

## Assignment bonuses

Every bonus in the exam specification is implemented:

- Visualization of measurement data, and the advanced-visualization bonus: `time_series` and `boxplot` in `src/testing/visualization.py`, selected from `config.yaml`.
- Performance consistency: `relative_spread`, jitter, and `late_samples`. Timing checks are in `tests/test_performance.py`.
- Accuracy assessment: `compare_ammeters` ranks meters, `relative_error` is the accuracy figure when a reference is set, and `relative_spread` is the precision figure.
- Error simulation: `error_simulation` in `config.yaml`, applied in the framework. The emulators are unchanged.
- Configuration-driven testing: ports, commands, sampling, metrics, plots, and error simulation come from `config/config.yaml`.

## Cross-platform CI

One workflow at `.github/workflows/tests.yml` runs a matrix of `ubuntu-latest`, `windows-latest`, and `macos-latest` with Python 3.12. Each job installs `requirements.txt` and `requirements-plot.txt`, then runs `python -m pytest -q`, `python main.py`, and `python examples/run_tests.py` in that order. `fail-fast: false` so each OS reports independently. The matrix exists because scheduling and socket behavior differ per OS: the Windows PowerShell cp1252 default encoding on the Greenlee ohm-sign print and the Windows connection-refused handshake that TC-04 drives through `refusing_port` are both covered in Bug fixes. The macOS runner can jitter past the local 50 ms timing SLA, so TC-15 loosens its bound when the `CI` env var is set.

## Architecture

Emulators are TCP servers. Each accepts one client, so meters are sampled one after another. `client.py` turns one exchange into a float or a typed error: it reads until the server closes the socket and rejects a reply over 1024 bytes. `stop()` on the base class releases the port. `main.py` and `run_framework.py` start the servers on daemon threads and call `wait_until_accepting` in `base_ammeter.py` instead of sleeping a fixed time. `main.py` does not call `stop()`.

A relative results directory is resolved from the project root (`PROJECT_ROOT`), not from the shell's current directory.

Paths use `pathlib`. Networking and clocks use the standard library. Tests do not call shell commands.

## Unified API

The framework never opens sockets itself. Every meter is a zero-argument reader that returns a float. Config builds that reader from host, port, and command. `register_ammeter(name, reader)` accepts any callable, including fakes in tests. Statistics, JSON results, and comparisons are the same for every meter.

## Sampling

Samples are scheduled at `t_i = i / f` inside the half-open window `[0, D)`. The count is `ceil(D * f)`, computed with `fractions.Fraction` so `0.3 * 10` is 3, not `3.0000000000000004`. The first sample is at `t = 0`. The last is at `(N - 1) / f`, which is strictly before `D`.

Give at least two of count, duration, and frequency (`f = N / D`, or `D = N / f`). All three must satisfy `count == ceil(D * f)`.

The boundary rule is pinned by `test_half_open_window_excludes_the_end_boundary` in `tests/test_sampling.py`, parametrized over `0.3s @ 10 Hz`, `1 s @ 4 Hz`, and `0.7s @ 10 Hz`. Each case asserts the exact schedule, `scheduled[-1] < D`, and `len(samples) == ceil(D * f)`.

The schedule is absolute (`t0 + i/f` on `time.perf_counter`, coarse sleep plus a short spin) so a slow read does not shift later samples. Tests may inject a clock. If that callable has `advance_to(deadline)`, the scheduler jumps there instead of sleeping. Production does not pass a clock.

## Timing tolerance

A sample is late when the read starts more than one interval after its scheduled time. `late_samples` counts those reads. The run still finishes and the status is unchanged. In-process readers are expected to stay within `TIMING_TOLERANCE_S` (50 ms). TCP latency can exceed that and shows up as jitter or `late_samples`.

The short busy-wait improves precision on a normal operating system. It is best-effort scheduling, not a hard real-time guarantee.

## Statistics

Mean, median, sample standard deviation (n − 1, `statistics.stdev`), min, and max. One value has std 0. An empty set returns `{"count": 0}` and no other metrics. Median of an even count is the average of the two middle values.

`relative_spread = std / |mean|`, or null when the mean is 0. Failed samples, including NaN and infinity, are stored and excluded from the statistics.

## Errors

Client errors are `AmmeterConnectionError`, `AmmeterTimeoutError`, `AmmeterNoReplyError`, and `AmmeterParseError`. The collector records them on the sample and continues. Config problems raise `ConfigError` (a `ValueError`) before any sample is taken. A missing config file raises `FileNotFoundError`.

Error simulation wraps the reader inside the framework and does not change the emulators. It is off unless `error_simulation.enabled` is true. A missing section leaves every sample on the normal path. Each run restarts `random.Random(seed)`. Modes are checked in the order connection, timeout, invalid response, intermittent. The first hit wins for that sample and becomes a per-sample error. The run continues. Status is `partial` when some samples are valid and `failed` when none are.

## Result storage

One JSON file per run, written via a temporary file and `replace`:

`<results_dir>/<ammeter>_<UTC timestamp>_<uuid8>.json`

Default directory is `results/runs/`. Logs go to `<results_dir>/logs/`.

Fields: `run_id`, `ammeter`, `status` (`ok` / `partial` / `failed`), `metadata` (start and end time, host, port, command, sampling, errors, Python, platform), `stats`, `timing` (jitter and `late_samples`), and `samples` (scheduled time, actual time, value, latency, error).

If saving raises `OSError`, the result is returned with `metadata.save_error`. `compare_runs` sets `mean_delta_pct` against the first run only when the ammeter matches and that first mean is not zero. Otherwise it is null. Corrupt JSON raises `ValueError`. Run ids containing `..` or a path separator are rejected.

## Accuracy and relative spread

The emulators draw random currents and have no true reference. `relative_spread` is precision (how tight the samples are). It is not accuracy.

A relative error is stored only when `reference_current_a` is set and non-zero. It is not an absolute error in amperes:

```
relative_error = (mean - reference_current_a) / reference_current_a
```

Reference `0` sets `relative_error` to null and `relative_error_note` to a short explanation. No exception. With no reference the field is omitted, including in `compare_ammeters`, unless the caller passes `reference_current_a` there.

The comparison report shows three separate facts side by side:

- Precision is `relative_spread` (column `rel.spread`). Lower means the valid samples are tighter.
- Accuracy is `relative_error` (column `rel.err`). It appears only when a nonzero reference exists.
- Success rate is valid samples divided by attempts (column `success`). A failed sample lowers it. It does not change the rank. `err rate` is the complement and is also display-only.

Ranking without a usable relative error is by `relative_spread`, lowest first. When a nonzero reference produces a relative error, ranking switches to `|relative_error|`, lowest first. Each comparison row records `ranked_by` as `relative_spread` or `abs_relative_error`. The text report says which one was used.

## Configuration

`config/config.yaml` is the single config source. Sampling keys are `measurements_count`, `total_duration_seconds`, and `sampling_frequency_hz`. Meter names match `[A-Za-z0-9_-]+`. A CLI sampling flag replaces only that field. The others stay from the file. If the three values then disagree, fields that were not passed on the command line are dropped and derived again. All three flags, when they disagree, still raise `ConfigError`.

`statistical_metrics: []` asks for no metrics, so a result with samples stores `count` only. `None` (the key omitted) computes every metric. An unknown name is rejected before any sample is taken, including when the sample list is empty.

`client_timeout_seconds` bounds one read. `reference_current_a` is optional so a run without a known true current does not invent an accuracy claim.

## Extensibility

A new meter is an `ammeters:` entry (host, port, command) plus an optional class in `EMULATORS` in `run_framework.py`. Custom readers are callables passed to `register_ammeter`. Metrics are the `METRICS` map. Error-simulation modes are the four keys in the config. Plot types are `time_series` and `boxplot` under `analysis.visualization.plot_types`.

## Libraries installed

The measurement code needs one third-party library. The others are for tests and the optional plot. Nothing else was installed to run the project. numpy, scipy, and pandas are not used.

| Library | File | Why |
|---|---|---|
| PyYAML | `requirements.txt` | Read `config/config.yaml` |
| pytest | `requirements.txt` | Run the automated tests |
| matplotlib | `requirements-plot.txt` | `--plot` only. A run without it still saves JSON |

```sh
python -m pip install -r requirements.txt
python -m pip install -r requirements-plot.txt
```

## Bug fixes

The original emulator classes, ports, and measurement formulas were kept. These defects in that code were fixed:

- `client.py` printed the reply and returned `None`, so nothing could collect measurements. It now returns a float and raises typed errors. Replies are read until the server closes. More than 1024 bytes is a parse error. NaN and infinity are rejected.
- README and config used ports 5000–5002 and a CIRCUTOR command without `-current`. The emulators use 5001–5003 and `-current`. A wrong command gets no reply.
- `test_framework.py` was missing a `Dict` import, and the framework itself was unimplemented.
- `logger.py` had no handler. It now writes a file and warnings to the console.
- Imports failed outside the project directory. `run_framework.py` puts the project root on `sys.path`.
- `base_ammeter.py` sets `SO_REUSEADDR` so a restart during `TIME_WAIT` can bind. `stop()` unblocks `accept` so tests can release the port. A client that connects and then closes makes `recv` raise `ConnectionResetError` on Windows and used to kill the emulator thread. That read is now ignored and the server keeps accepting. Measurement formulas are unchanged.
- `main.py` and `run_framework.py` reconfigure `sys.stdout`/`sys.stderr` to UTF-8 at startup. Windows PowerShell defaults to cp1252, which cannot encode the ohm sign (`Ω`) that Greenlee's `measure_current` prints. Without the reconfigure, that `print` raised `UnicodeEncodeError`, killed the Greenlee server thread between a matched request and the reply, and the client got no data back.
