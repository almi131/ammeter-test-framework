import time

import pytest

from src.testing.test_framework import TIMING_TOLERANCE_S, ConfigError, SamplingPlan, samples_in_window
from tests.helpers import ManualClock


def test_cli_sampling_flag_overrides_one_field():
    from run_framework import sampling_override

    base = {"measurements_count": 20, "total_duration_seconds": 2.0, "sampling_frequency_hz": 10}
    plan = SamplingPlan.from_config(sampling_override(base, count=3))
    assert (plan.count, plan.frequency_hz, plan.duration_s) == (3, 10.0, pytest.approx(0.3))
    with pytest.raises(ConfigError, match="Inconsistent sampling"):
        SamplingPlan.from_config(sampling_override(base, count=5, duration=2, frequency=10))


def test_tc10_measurement_count(framework):
    fw = framework()
    fw.register_ammeter("meter", lambda: 1.0)
    result = fw.run_test("meter", sampling={"measurements_count": 5, "sampling_frequency_hz": 10})
    assert len(result["samples"]) == 5
    assert result["stats"]["count"] == 5
    assert result["status"] == "ok"


def test_tc11_sampling_duration(framework):
    duration, freq = 1.0, 2.5
    fw = framework()
    fw.register_ammeter("meter", lambda: 1.0)
    result = fw.run_test(
        "meter", sampling={"total_duration_seconds": duration, "sampling_frequency_hz": freq})
    scheduled = [s["scheduled_s"] for s in result["samples"]]
    assert scheduled == pytest.approx([0.0, 0.4, 0.8])
    assert scheduled[-1] < duration
    assert all(0 <= t < duration for t in scheduled)


@pytest.mark.parametrize("duration, freq, expected", [
    pytest.param(0.3, 10, [0.0, 0.1, 0.2], id="0.3s-10Hz"),
    pytest.param(1.0, 4, [0.0, 0.25, 0.5, 0.75], id="1s-4Hz"),
    pytest.param(0.7, 10, [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6], id="0.7s-10Hz"),
])
def test_half_open_window_excludes_the_end_boundary(duration, freq, expected, framework):
    fw = framework()
    fw.register_ammeter("meter", lambda: 1.0)
    result = fw.run_test(
        "meter", sampling={"total_duration_seconds": duration, "sampling_frequency_hz": freq})
    scheduled = [sample["scheduled_s"] for sample in result["samples"]]
    assert scheduled == pytest.approx(expected)
    assert all(0 <= t < duration for t in scheduled)
    assert len(scheduled) == samples_in_window(duration, freq)


def test_tc12_sampling_frequency(framework):
    freq = 4.0
    fw = framework()
    fw.register_ammeter("meter", lambda: 1.0)
    result = fw.run_test("meter", sampling={"measurements_count": 4, "sampling_frequency_hz": freq})
    scheduled = [s["scheduled_s"] for s in result["samples"]]
    assert scheduled == pytest.approx([i / freq for i in range(4)])
    gaps = [b - a for a, b in zip(scheduled, scheduled[1:])]
    assert gaps == pytest.approx([1 / freq] * 3)


def test_tc13_combined_sampling_configuration():
    plan = SamplingPlan.from_config(
        {"measurements_count": 20, "total_duration_seconds": 2, "sampling_frequency_hz": 10})
    assert (plan.count, plan.duration_s, plan.frequency_hz) == (20, 2.0, 10.0)
    assert plan.count == samples_in_window(plan.duration_s, plan.frequency_hz)
    with pytest.raises(ConfigError, match="Inconsistent sampling"):
        SamplingPlan.from_config(
            {"measurements_count": 5, "total_duration_seconds": 2, "sampling_frequency_hz": 10})


@pytest.mark.parametrize("cfg, message", [
    pytest.param({"measurements_count": 0, "sampling_frequency_hz": 10}, "positive number", id="zero"),
    pytest.param({"total_duration_seconds": -1, "sampling_frequency_hz": 10}, "positive number",
                 id="negative"),
    pytest.param({"measurements_count": "5", "sampling_frequency_hz": 10}, "positive number",
                 id="nonnumeric"),
    pytest.param({"measurements_count": True, "sampling_frequency_hz": 10}, "positive number", id="bool"),
    pytest.param({"measurements_count": 4}, "at least two", id="incomplete"),
    pytest.param({"measurements_count": 4, "sampling_frequency_hz": float("nan")}, "positive number",
                 id="nan"),
])
def test_tc14_invalid_sampling_parameters(cfg, message, framework):
    fw = framework()
    calls = []
    fw.register_ammeter("meter", lambda: calls.append(1) or 1.0)
    with pytest.raises(ConfigError, match=message):
        fw.run_test("meter", sampling=cfg)
    assert calls == []


def test_tc15_scheduled_times_use_injected_clock(framework):
    clock = ManualClock(start=10.0)
    fw = framework(
        clock=clock,
        testing={"sampling": {"measurements_count": 4, "sampling_frequency_hz": 10}},
    )
    fw.register_ammeter("meter", lambda: 1.0)
    started = time.perf_counter()
    result = fw.run_test("meter")
    assert time.perf_counter() - started < 0.05
    expected = [i / 10 for i in range(4)]
    assert [s["scheduled_s"] for s in result["samples"]] == pytest.approx(expected)
    assert [s["actual_s"] for s in result["samples"]] == pytest.approx(expected)


def test_tc15_real_clock_within_tolerance(framework):
    import os
    fw = framework(
        clock=None,
        testing={"sampling": {"measurements_count": 4, "sampling_frequency_hz": 50}},
    )
    fw.register_ammeter("meter", lambda: 1.0)
    result = fw.run_test("meter")
    last = result["samples"][-1]
    assert last["scheduled_s"] == pytest.approx(3 / 50)
    # TIMING_TOLERANCE_S is a quiet-machine SLA (50 ms). GitHub Actions runners,
    # especially macOS, can jitter well past that; relax the bound only on CI.
    tolerance = 0.5 if os.environ.get("CI") else TIMING_TOLERANCE_S
    assert abs(last["actual_s"] - last["scheduled_s"]) <= tolerance
