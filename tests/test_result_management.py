import json

import pytest

from tests.helpers import fake_reader


def test_tc21_save_test_results(framework, tmp_path):
    fw = framework()
    fw.register_ammeter("meter", lambda: 1.5)
    result = fw.run_test("meter")
    path = tmp_path / f"{result['run_id']}.json"
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["run_id"] == result["run_id"]


def test_tc22_unique_test_run_id(framework):
    fw = framework()
    fw.register_ammeter("meter", lambda: 1.0)
    ids = [fw.run_test("meter")["run_id"] for _ in range(3)]
    assert len(set(ids)) == 3
    assert all(run_id.startswith("meter_") for run_id in ids)


def test_tc23_metadata_storage(framework):
    fw = framework()
    fw.register_ammeter("meter", lambda: 1.25)
    result = fw.run_test("meter")
    assert result["run_id"]
    assert result["ammeter"] == "meter"
    assert result["status"] == "ok"
    assert result["metadata"]["start_time"]
    sampling = result["metadata"]["config"]["sampling"]
    assert {"measurements_count", "total_duration_seconds", "sampling_frequency_hz"} <= set(sampling)
    assert result["samples"]
    assert all("value" in sample for sample in result["samples"])


def test_tc24_historical_result_retrieval(framework):
    fw = framework()
    fw.register_ammeter("meter", lambda: 1.5)
    result = fw.run_test("meter")
    loaded = fw.load_result(result["run_id"])
    assert loaded == json.loads(json.dumps(result))
    listed = fw.list_results("meter")
    assert [row["run_id"] for row in listed] == [result["run_id"]]


def test_corrupt_result_file_is_reported(framework, tmp_path):
    fw = framework()
    fw.register_ammeter("meter", lambda: 1.0)
    good = fw.run_test("meter")
    (tmp_path / "meter_broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="Corrupt result file"):
        fw.load_result("meter_broken")
    assert [row["run_id"] for row in fw.list_results()] == [good["run_id"]]


def test_tc25_historical_result_comparison(framework):
    fw = framework()
    fw.register_ammeter("meter", fake_reader([10.0] * 4 + [20.0] * 4))
    first, second = fw.run_test("meter"), fw.run_test("meter")
    rows = fw.compare_runs([first["run_id"], second["run_id"]])
    assert rows[0]["mean"] == pytest.approx(10.0)
    assert rows[1]["mean"] == pytest.approx(20.0)
    assert rows[0]["mean_delta_pct"] == pytest.approx(0.0)
    assert rows[1]["mean_delta_pct"] == pytest.approx(100.0)
