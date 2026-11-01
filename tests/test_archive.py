import json
import re

import pytest

from src.archive import LATEST, RunArchive, compare_runs, new_run_id
from src.archive.__main__ import main as cli
from tests.helpers import fake_reader


def _result(name, status="ok", mean=1.0, errors=0):
    stats = {"count": 4, "mean": mean} if status != "failed" else {"count": 0}
    return {"run_id": f"{name}_x", "ammeter": name, "status": status, "stats": stats,
            "timing": {"late_samples": 0}, "samples": [{}] * 4,
            "metadata": {"start_time": "2026-01-01T00:00:00+00:00", "error_count": errors}}


@pytest.fixture
def archive(tmp_path):
    return RunArchive(tmp_path / "archive")


def test_run_ids_are_unique_and_well_formed():
    ids = {new_run_id() for _ in range(50)}
    assert len(ids) == 50
    assert all(re.fullmatch(r"\d{8}T\d{6}Z_[0-9a-f]{8}", i) for i in ids)


def test_record_stores_metadata_and_results(archive):
    entry = archive.record({"a": _result("a"), "b": _result("b", "failed", errors=4)},
                           config={"sampling": {"measurements_count": 4}}, commit=lambda: "abc123")
    meta = entry["metadata"]
    assert meta["git_commit"] == "abc123"
    assert meta["config"] == {"sampling": {"measurements_count": 4}}
    assert meta["timestamp"] and meta["platform"] and meta["os"] and meta["python"]
    assert meta["summary"] == {"ammeters": 2, "ok": 1, "partial": 0, "failed": 1,
                               "samples": 8, "valid_samples": 4, "errors": 4}
    loaded = archive.load(entry["run_id"])
    assert loaded == json.loads(json.dumps(entry))
    assert loaded["results"]["a"]["samples"] == 4  # count only; raw samples live in the per-ammeter file


def test_missing_git_is_none(archive):
    assert archive.record({"a": _result("a")}, commit=lambda: None)["metadata"]["git_commit"] is None


def test_list_and_latest(archive):
    assert archive.list() == []
    with pytest.raises(FileNotFoundError):
        archive.load(LATEST)
    ids = [archive.record({"a": _result("a")}, commit=lambda: None)["run_id"] for _ in range(3)]
    assert [r["run_id"] for r in archive.list()] == ids
    assert archive.load(LATEST)["run_id"] == ids[-1]


def test_duplicate_id_is_rejected(archive):
    archive.record({"a": _result("a")}, run_id="fixed", commit=lambda: None)
    with pytest.raises(FileExistsError):
        archive.record({"a": _result("a")}, run_id="fixed", commit=lambda: None)


@pytest.mark.parametrize("bad", ["", "..", "../x", "a/b", "a\\b", "a.b"])
def test_unsafe_run_ids_are_rejected(archive, bad):
    with pytest.raises(ValueError, match="Invalid run id"):
        archive.load(bad)


def test_unknown_run_and_corrupt_file(archive):
    good = archive.record({"a": _result("a")}, commit=lambda: None)["run_id"]
    with pytest.raises(FileNotFoundError):
        archive.load("nope")
    (archive.directory / "broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="Corrupt archive file"):
        archive.load("broken")
    assert [r["run_id"] for r in archive.list()] == [good]


def test_compare_reports_status_and_metric_changes(archive):
    one = archive.record({"a": _result("a", mean=10.0), "b": _result("b"), "c": _result("c")},
                         commit=lambda: None)
    two = archive.record({"a": _result("a", mean=15.0), "b": _result("b", "failed", errors=4),
                          "d": _result("d")}, commit=lambda: None)
    diff = compare_runs(one, two)
    assert diff["ammeters"]["a"]["change"] == "unchanged"
    assert diff["ammeters"]["a"]["metrics"]["stats.mean"] == {
        "a": 10.0, "b": 15.0, "delta": 5.0, "delta_pct": pytest.approx(50.0)}
    assert diff["ammeters"]["b"]["change"] == "regressed"
    assert diff["ammeters"]["b"]["status"] == {"a": "ok", "b": "failed"}
    assert (diff["only_in_a"], diff["only_in_b"]) == (["c"], ["d"])
    back = archive.compare(two["run_id"], one["run_id"])
    assert back["ammeters"]["b"]["change"] == "improved"


def test_compare_identical_runs_has_no_metric_deltas(archive):
    one = archive.record({"a": _result("a")}, commit=lambda: None)["run_id"]
    two = archive.record({"a": _result("a")}, commit=lambda: None)["run_id"]
    assert archive.compare(one, two)["ammeters"]["a"]["metrics"] == {}


def test_run_all_archives_automatically(framework, tmp_path):
    fw = framework()
    fw.register_ammeter("good", fake_reader([1.0] * 4))
    fw.register_ammeter("bad", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    results = fw.run_all(["good", "bad"])
    entry = fw.archive.load(fw.last_archive_id)
    assert (tmp_path / "archive" / f"{fw.last_archive_id}.json").is_file()
    assert set(entry["results"]) == {"good", "bad"}
    assert entry["results"]["good"]["result_run_id"] == results["good"]["run_id"]
    assert entry["metadata"]["summary"]["ok"] == 1 and entry["metadata"]["summary"]["failed"] == 1
    assert entry["metadata"]["config"]["sampling"]["measurements_count"] == 4
    assert (tmp_path / f"{results['good']['run_id']}.json").is_file()  # per-ammeter file unchanged


def test_run_test_archives_single_run_and_save_false_does_not(framework):
    fw = framework()
    fw.register_ammeter("meter", lambda: 1.0)
    fw.run_test("meter", save=False)
    assert fw.archive.list() == []
    fw.run_test("meter")
    assert list(fw.archive.load(LATEST)["results"]) == ["meter"]


def test_archive_failure_keeps_results(framework, tmp_path):
    fw = framework()
    fw.register_ammeter("meter", lambda: 1.0)
    (tmp_path / "archive").write_text("not a directory", encoding="utf-8")
    results = fw.run_all(["meter"])
    assert results["meter"]["status"] == "ok"
    assert fw.last_archive_id is None


def test_cli_list_show_compare(tmp_path, capsys):
    arch = RunArchive(tmp_path / "archive")
    one = arch.record({"a": _result("a", mean=1.0)}, commit=lambda: "deadbeefcafe")["run_id"]
    arch.record({"a": _result("a", mean=2.0)}, commit=lambda: None)
    base = ["--results-dir", str(tmp_path)]

    assert cli(base + ["list"]) == 0
    out = capsys.readouterr().out
    assert one in out and "deadbeef" in out

    assert cli(base + ["show", LATEST]) == 0
    assert json.loads(capsys.readouterr().out)["results"]["a"]["stats"]["mean"] == 2.0

    assert cli(base + ["compare", one, LATEST]) == 0
    out = capsys.readouterr().out
    assert "stats.mean" in out and "+100.00%" in out


def test_cli_errors_return_nonzero(tmp_path, capsys):
    base = ["--results-dir", str(tmp_path)]
    assert cli(base + ["list"]) == 0
    assert "No archived runs" in capsys.readouterr().out
    assert cli(base + ["show", "latest"]) == 2
    assert cli(base + ["show", "../x"]) == 2
    assert "ERROR" in capsys.readouterr().err
