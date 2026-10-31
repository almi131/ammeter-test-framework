import statistics

import pytest

from Ammeters.client import AmmeterTimeoutError
from src.testing.test_framework import ConfigError, compute_stats


def test_metric_names_are_checked_before_the_values():
    with pytest.raises(ConfigError, match="Unknown statistical metrics"):
        compute_stats([], ["bad"])
    assert compute_stats([1.0, 2.0], []) == {"count": 2}
    assert set(compute_stats([1.0, 2.0], ["min"])) == {"count", "min", "relative_spread"}


def test_tc16_mean_calculation():
    # (1 + 2 + 3 + 4 + 10) / 5 = 4
    assert compute_stats([1.0, 2.0, 3.0, 4.0, 10.0])["mean"] == pytest.approx(4.0)


def test_tc17_median_odd_and_even():
    assert compute_stats([1.0, 3.0, 5.0])["median"] == 3.0
    assert compute_stats([1.0, 2.0, 3.0, 4.0])["median"] == 2.5


def test_tc18_standard_deviation():
    # sample std (n-1): [2, 4] -> sqrt(2). Population std would be 1.
    assert compute_stats([2.0, 4.0])["std_dev"] == pytest.approx(statistics.stdev([2.0, 4.0]))
    assert compute_stats([2.0, 4.0])["std_dev"] == pytest.approx(2 ** 0.5)


def test_tc19_minimum_and_maximum():
    stats = compute_stats([3.0, -1.0, 8.0, 0.5])
    assert stats["min"] == -1.0
    assert stats["max"] == 8.0


@pytest.mark.parametrize("kind", ["empty", "single", "failed", "zero", "negative"])
def test_tc20_statistical_edge_cases(kind, framework):
    if kind == "empty":
        assert compute_stats([]) == {"count": 0}
    elif kind == "single":
        stats = compute_stats([5.0])
        assert stats["mean"] == 5.0 and stats["std_dev"] == 0.0
        assert stats["min"] == stats["max"] == 5.0
    elif kind == "zero":
        stats = compute_stats([0.0, 0.0])
        assert stats["mean"] == 0.0 and stats["min"] == 0.0 and stats["max"] == 0.0
        assert stats["relative_spread"] is None
    elif kind == "negative":
        stats = compute_stats([-4.0, -2.0, -6.0])
        assert stats["mean"] == pytest.approx(-4.0)
        assert stats["min"] == -6.0 and stats["max"] == -2.0
        assert stats["relative_spread"] == pytest.approx(stats["std_dev"] / 4.0)
    else:
        fw = framework()
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] % 2:
                raise AmmeterTimeoutError("boom")
            return 2.0

        fw.register_ammeter("flaky", flaky)
        result = fw.run_test("flaky")
        valid = [sample for sample in result["samples"] if sample["error"] is None]
        assert len(valid) == len(result["samples"]) // 2
        assert all(sample["value"] == 2.0 for sample in valid)
        assert result["stats"]["count"] == len(valid)
        assert result["stats"]["mean"] == 2.0
