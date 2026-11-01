import itertools

import pytest

from src.testing.test_framework import format_ammeter_comparison
from tests.helpers import fake_reader


def test_tc28_compare_ammeter_measurements(framework):
    fw = framework()
    fw.register_ammeter("greenlee", lambda: 1.0)
    fw.register_ammeter("entes", lambda: 5.0)
    fw.register_ammeter("circutor", lambda: 2.0)
    results = fw.run_all(["greenlee", "entes", "circutor"])
    rows = fw.compare_ammeters(results)
    assert {row["ammeter"] for row in rows} == {"greenlee", "entes", "circutor"}
    for row in rows:
        assert {"mean", "std_dev", "relative_spread", "rank", "error_rate", "success_rate",
                "ci95_rel", "outliers"} <= set(row)
        assert row["success_rate"] == 1.0
    report = format_ammeter_comparison(rows)
    assert "greenlee" in report and "entes" in report and "circutor" in report
    assert "success" in report and "100.0%" in report


def test_tc29_relative_accuracy(framework):
    plain = framework()
    plain.register_ammeter("meter", lambda: 12.0)
    unreferenced = plain.run_test("meter")
    assert "relative_error" not in unreferenced["stats"]
    assert "relative_error" not in plain.compare_ammeters({"meter": unreferenced})[0]

    passed = plain.compare_ammeters({"meter": unreferenced}, reference_current_a=10)
    assert passed[0]["relative_error"] == pytest.approx(0.2)
    zero_passed = plain.compare_ammeters({"meter": unreferenced}, reference_current_a=0)
    assert zero_passed[0]["relative_error"] is None
    assert "undefined" in zero_passed[0]["relative_error_note"]

    referenced = framework(testing={"reference_current_a": 10})
    referenced.register_ammeter("meter", lambda: 12.0)
    result = referenced.run_test("meter")
    assert result["stats"]["relative_error"] == pytest.approx((12.0 - 10.0) / 10.0)
    assert "relative_error_note" not in result["stats"]
    assert referenced.compare_ammeters({"meter": result})[0]["relative_error"] == pytest.approx(0.2)

    zero = framework(testing={"reference_current_a": 0})
    zero.register_ammeter("meter", lambda: 12.0)
    result = zero.run_test("meter")
    assert result["stats"]["relative_error"] is None
    assert "reference_current_a is 0" in result["stats"]["relative_error_note"]


def test_reference_ranks_by_absolute_relative_error(framework):
    fw = framework()
    fw.register_ammeter("tight_far", fake_reader([20.0, 20.0, 20.0, 20.0]))
    fw.register_ammeter("wide_close", fake_reader([9.0, 11.0, 8.0, 12.0]))
    results = fw.run_all(["tight_far", "wide_close"])
    by_precision = fw.compare_ammeters(results)
    assert by_precision[0]["ranked_by"] == "relative_spread"
    assert [row["ammeter"] for row in by_precision] == ["tight_far", "wide_close"]
    by_accuracy = fw.compare_ammeters(results, reference_current_a=10)
    assert by_accuracy[0]["ranked_by"] == "abs_relative_error"
    assert [row["ammeter"] for row in by_accuracy] == ["wide_close", "tight_far"]
    assert abs(by_accuracy[0]["relative_error"]) < abs(by_accuracy[1]["relative_error"])
    assert "not more accurate" in format_ammeter_comparison(by_precision)
    assert "relative error" in format_ammeter_comparison(by_accuracy)


def test_tc30_measurement_consistency(framework):
    fw = framework()
    fw.register_ammeter("steady", fake_reader(itertools.cycle([10.0, 10.1, 9.9, 10.0])))
    fw.register_ammeter("noisy", fake_reader(itertools.cycle([1.0, 20.0, 3.0, 30.0])))
    rows = fw.compare_ammeters(fw.run_all(["noisy", "steady"]))
    assert [row["ammeter"] for row in rows] == ["steady", "noisy"]
    assert rows[0]["relative_spread"] < rows[1]["relative_spread"]
