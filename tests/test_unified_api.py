import pytest

from src.utils.config import ConfigError

_RESULT_KEYS = {"run_id", "ammeter", "status", "metadata", "stats", "timing", "samples"}
_STAT_KEYS = {"count", "mean", "median", "std_dev", "min", "max", "relative_spread"}


_EXPECTED = {"greenlee": 1.0, "entes": 2.0, "circutor": 3.0}


def _register_three(fw):
    for name, value in _EXPECTED.items():
        fw.register_ammeter(name, lambda value=value: value)


def _assert_meter_values(results):
    for name, value in _EXPECTED.items():
        assert all(sample["value"] == value for sample in results[name]["samples"])
        assert results[name]["stats"]["mean"] == value


def test_tc07_unified_api_for_all_ammeters(framework):
    fw = framework()
    _register_three(fw)
    results = fw.run_all(["greenlee", "entes", "circutor"])
    assert set(results) == set(_EXPECTED)
    assert all(r["status"] == "ok" for r in results.values())
    _assert_meter_values(results)


def test_tc08_consistent_result_format(framework):
    fw = framework()
    _register_three(fw)
    results = fw.run_all(["greenlee", "entes", "circutor"])
    shapes = []
    for result in results.values():
        assert set(result) == _RESULT_KEYS
        assert set(result["stats"]) == _STAT_KEYS
        assert isinstance(result["samples"][0]["value"], float)
        shapes.append((set(result), set(result["stats"]), set(result["samples"][0])))
    assert shapes[0] == shapes[1] == shapes[2]
    _assert_meter_values(results)


def test_tc09_unsupported_ammeter(framework):
    fw = framework()
    with pytest.raises(ConfigError, match="Unknown ammeter 'unknown'"):
        fw.run_test("unknown")
