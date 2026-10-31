import statistics

import pytest

from tests.helpers import ManualClock, fake_reader


def test_perf01_slow_measurement_response(framework):
    """A 250 ms read at 10 Hz does not move later scheduled times or drop samples."""
    clock = ManualClock()
    interval = 0.1
    delay = 0.25
    count = 4
    fw = framework(
        clock=clock,
        testing={"sampling": {"measurements_count": count, "sampling_frequency_hz": 10}},
    )

    def slow():
        clock.t += delay
        return 1.5

    fw.register_ammeter("meter", slow)
    result = fw.run_test("meter")
    samples = result["samples"]
    scheduled = [i * interval for i in range(count)]
    actual = [i * delay for i in range(count)]
    assert [s["scheduled_s"] for s in samples] == pytest.approx(scheduled)
    assert [s["actual_s"] for s in samples] == pytest.approx(actual)
    assert [s["latency_ms"] for s in samples] == pytest.approx([delay * 1000] * count)
    assert [s["value"] for s in samples] == [1.5] * count
    assert result["timing"]["late_samples"] == sum(
        a - s > interval for s, a in zip(scheduled, actual))
    assert result["status"] == "ok"


def test_perf02_extended_sampling_stability(framework):
    count = 1000
    values = [float(i) for i in range(1, count + 1)]
    fw = framework(testing={"sampling": {"measurements_count": count, "sampling_frequency_hz": 1000}})
    fw.register_ammeter("meter", fake_reader(values))
    result = fw.run_test("meter")
    assert [s["value"] for s in result["samples"]] == values
    assert result["stats"]["count"] == count
    assert result["stats"]["mean"] == pytest.approx(sum(values) / count)
    assert result["stats"]["min"] == 1.0
    assert result["stats"]["max"] == float(count)
    assert result["status"] == "ok"
    loaded = fw.load_result(result["run_id"])
    assert loaded["samples"] == result["samples"]
    assert loaded["stats"]["mean"] == result["stats"]["mean"]


def test_perf03_timing_metrics_correctness(framework):
    """One 250 ms read among fast reads. Timing fields match the timestamps."""
    clock = ManualClock()
    fw = framework(
        clock=clock,
        testing={"sampling": {"measurements_count": 4, "sampling_frequency_hz": 10}},
    )
    calls = {"n": 0}

    def read():
        calls["n"] += 1
        if calls["n"] == 3:
            clock.t += 0.25
        return 2.0

    fw.register_ammeter("meter", read)
    result = fw.run_test("meter")
    samples = result["samples"]
    jitter_s = [s["actual_s"] - s["scheduled_s"] for s in samples]
    assert [s["scheduled_s"] for s in samples] == pytest.approx([0.0, 0.1, 0.2, 0.3])
    assert [s["actual_s"] for s in samples] == pytest.approx([0.0, 0.1, 0.2, 0.45])
    assert [s["latency_ms"] for s in samples] == pytest.approx([0.0, 0.0, 250.0, 0.0])
    assert jitter_s == pytest.approx([0.0, 0.0, 0.0, 0.15])
    assert result["timing"]["mean_jitter_ms"] == pytest.approx(statistics.fmean(jitter_s) * 1000)
    assert result["timing"]["mean_jitter_ms"] == pytest.approx(37.5)
    assert result["timing"]["max_abs_jitter_ms"] == pytest.approx(150.0)
    assert result["timing"]["late_samples"] == 1
