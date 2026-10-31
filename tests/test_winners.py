"""Tests for the three-winner summary in the ammeter comparison report."""
import itertools

import pytest

from src.testing.test_framework import format_ammeter_comparison, select_winners
from tests.helpers import fake_reader


SAMPLING = {"measurements_count": 10, "sampling_frequency_hz": 1000}


def _flaky(reader, raise_every):
    """Wrap a reader to raise on every Nth call (N=raise_every). N=2 => half fail."""
    calls = {"n": 0}

    def wrapped():
        calls["n"] += 1
        if calls["n"] % raise_every == 0:
            raise RuntimeError("simulated communication failure")
        return reader()

    return wrapped


def test_precision_winner_lowest_relative_spread(framework):
    fw = framework(testing={"sampling": SAMPLING})
    fw.register_ammeter("steady", fake_reader(itertools.cycle([10.0, 10.01, 9.99, 10.0])))
    fw.register_ammeter("medium", fake_reader(itertools.cycle([10.0, 10.5, 9.5, 10.0])))
    fw.register_ammeter("noisy", fake_reader(itertools.cycle([1.0, 20.0, 3.0, 30.0])))
    rows = fw.compare_ammeters(fw.run_all(["steady", "medium", "noisy"]))

    winners = select_winners(rows)
    assert winners["precision"] is not None
    assert winners["precision"]["ammeters"] == ["steady"]
    assert winners["precision"]["metric"] == "relative_spread"

    report = format_ammeter_comparison(rows)
    assert "Winners:" in report
    assert "most precise" in report
    # the winning ammeter name appears on the most-precise line
    for line in report.splitlines():
        if "most precise" in line:
            assert "steady" in line
            break
    else:
        pytest.fail("no 'most precise' line in report")


def test_accuracy_winner_only_shown_when_reference_present(framework):
    fw = framework(testing={"sampling": SAMPLING})
    fw.register_ammeter("far", fake_reader(itertools.cycle([20.0, 20.0, 20.0])))
    fw.register_ammeter("near", fake_reader(itertools.cycle([10.5, 10.5, 10.5])))

    results = fw.run_all(["far", "near"])

    rows_no_ref = fw.compare_ammeters(results)
    assert select_winners(rows_no_ref)["accuracy"] is None
    report_no_ref = format_ammeter_comparison(rows_no_ref)
    assert "most accurate" not in report_no_ref

    rows_ref = fw.compare_ammeters(results, reference_current_a=10.0)
    winners = select_winners(rows_ref)
    assert winners["accuracy"] is not None
    assert winners["accuracy"]["ammeters"] == ["near"]
    assert winners["accuracy"]["metric"] == "abs_relative_error"

    report_ref = format_ammeter_comparison(rows_ref)
    assert "most accurate" in report_ref
    for line in report_ref.splitlines():
        if "most accurate" in line:
            assert "near" in line
            break


def test_reliability_winner_uses_success_rate_not_precision(framework):
    fw = framework(testing={"sampling": SAMPLING})
    # 'tight_flaky' is extremely precise but half its samples raise, so success_rate ~= 0.5.
    fw.register_ammeter("tight_flaky", _flaky(lambda: 10.0, raise_every=2))
    # 'noisier_reliable' is wider but every sample succeeds.
    fw.register_ammeter("noisier_reliable", fake_reader(itertools.cycle([10.0, 10.2, 9.8, 10.1])))
    rows = fw.compare_ammeters(fw.run_all(["tight_flaky", "noisier_reliable"]))

    winners = select_winners(rows)
    assert winners["reliability"] is not None
    assert winners["reliability"]["ammeters"] == ["noisier_reliable"]
    assert winners["reliability"]["metric"] == "success_rate"
    assert winners["reliability"]["value"] == pytest.approx(1.0)

    # tight_flaky could still win precision because its succeeding samples are constant,
    # but it must not win reliability.
    assert "tight_flaky" not in winners["reliability"]["ammeters"]


def test_tie_lists_all_tied_ammeters(framework):
    fw = framework(testing={"sampling": SAMPLING})
    fw.register_ammeter("twin_a", lambda: 5.0)
    fw.register_ammeter("twin_b", lambda: 5.0)
    rows = fw.compare_ammeters(fw.run_all(["twin_a", "twin_b"]))

    winners = select_winners(rows)
    assert winners["precision"] is not None
    assert set(winners["precision"]["ammeters"]) == {"twin_a", "twin_b"}

    report = format_ammeter_comparison(rows)
    for line in report.splitlines():
        if "most precise" in line:
            assert "twin_a" in line and "twin_b" in line
            assert "twin_a, twin_b" in line or "twin_b, twin_a" in line
            break
    else:
        pytest.fail("no 'most precise' line in report")


def test_zero_successful_measurements_cannot_win_precision_or_accuracy(framework):
    fw = framework(testing={"sampling": SAMPLING})

    def always_raises():
        raise RuntimeError("boom")

    fw.register_ammeter("dead", always_raises)
    fw.register_ammeter("alive", fake_reader(itertools.cycle([10.1, 9.9, 10.2])))
    rows = fw.compare_ammeters(fw.run_all(["dead", "alive"]), reference_current_a=10.0)

    winners = select_winners(rows)
    assert winners["precision"] is not None
    assert "dead" not in winners["precision"]["ammeters"]
    assert winners["accuracy"] is not None
    assert "dead" not in winners["accuracy"]["ammeters"]


def test_all_zero_success_rate_no_reliability_winner(framework):
    fw = framework(testing={"sampling": SAMPLING})

    def always_raises():
        raise RuntimeError("boom")

    fw.register_ammeter("dead_a", always_raises)
    fw.register_ammeter("dead_b", always_raises)
    rows = fw.compare_ammeters(fw.run_all(["dead_a", "dead_b"]))

    winners = select_winners(rows)
    assert winners["reliability"] is None

    report = format_ammeter_comparison(rows)
    assert "most reliable" not in report


def test_existing_ranking_unchanged(framework):
    fw = framework(testing={"sampling": SAMPLING})
    # Three distinct spreads: tight < medium < wide.
    fw.register_ammeter("tight", fake_reader(itertools.cycle([10.0, 10.01, 9.99, 10.0])))
    fw.register_ammeter("medium", fake_reader(itertools.cycle([10.0, 10.3, 9.7, 10.0])))
    fw.register_ammeter("wide", fake_reader(itertools.cycle([5.0, 15.0, 7.0, 13.0])))
    rows = fw.compare_ammeters(fw.run_all(["wide", "medium", "tight"]))

    assert [row["ammeter"] for row in rows] == ["tight", "medium", "wide"]
    assert [row["rank"] for row in rows] == [1, 2, 3]
    assert all(row["ranked_by"] == "relative_spread" for row in rows)
    assert rows[0]["relative_spread"] < rows[1]["relative_spread"] < rows[2]["relative_spread"]
