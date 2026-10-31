import math

import pytest

from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from tests.helpers import METERS, running_emulator


def _real_framework(framework, name, port, command, testing):
    return framework(
        clock=None,
        ammeters={name: {"host": "localhost", "port": port, "command": command}},
        testing=testing,
    )


@pytest.mark.parametrize("name,cls,command", METERS, ids=["greenlee", "entes", "circutor"])
def test_tc35_complete_measurement_workflow(name, cls, command, framework):
    with running_emulator(cls) as emu:
        fw = _real_framework(framework, name, emu.port, command, {
            "client_timeout_seconds": 2,
            "sampling": {"measurements_count": 3, "sampling_frequency_hz": 20},
        })
        result = fw.run_test(name)
        loaded = fw.load_result(result["run_id"])
    assert result["status"] == "ok"
    assert result["stats"]["count"] == 3
    assert math.isfinite(result["stats"]["mean"])
    assert all(math.isfinite(s["value"]) for s in result["samples"])
    assert loaded["run_id"] == result["run_id"]
    assert loaded["stats"]["mean"] == result["stats"]["mean"]
    assert loaded["samples"] == result["samples"]


def test_tc36_multiple_ammeter_execution(framework):
    with running_emulator(METERS[0][1]) as greenlee, running_emulator(METERS[1][1]) as entes, \
            running_emulator(METERS[2][1]) as circutor:
        ports = {"greenlee": greenlee.port, "entes": entes.port, "circutor": circutor.port}
        fw = framework(
            clock=None,
            ammeters={
                name: {"host": "localhost", "port": ports[name], "command": command}
                for name, _cls, command in METERS
            },
            testing={
                "client_timeout_seconds": 2,
                "sampling": {"measurements_count": 3, "sampling_frequency_hz": 20},
            },
        )
        results = fw.run_all()
    assert set(results) == {"greenlee", "entes", "circutor"}
    assert len({r["run_id"] for r in results.values()}) == 3
    assert len({r["metadata"]["config"]["port"] for r in results.values()}) == 3
    for name, result in results.items():
        assert result["ammeter"] == name
        assert result["status"] == "ok"
        assert result["stats"]["count"] == 3
        assert math.isfinite(result["stats"]["mean"])


def test_tc37_e2e_failure_recovery(framework):
    with running_emulator(GreenleeAmmeter) as emu:
        fw = _real_framework(framework, "greenlee", emu.port, "MEASURE_GREENLEE -get_measurement", {
            "client_timeout_seconds": 2,
            "sampling": {"measurements_count": 8, "sampling_frequency_hz": 20},
            "error_simulation": {"enabled": True, "seed": 1, "intermittent_failure": 0.5},
        })
        result = fw.run_test("greenlee")
    valid = [s for s in result["samples"] if s["error"] is None]
    failed = [s for s in result["samples"] if s["error"]]
    assert valid and failed
    assert result["status"] == "partial"
    assert result["stats"]["count"] == len(valid)
    assert all(math.isfinite(s["value"]) for s in valid)
    assert result["metadata"]["error_count"] == len(failed)
