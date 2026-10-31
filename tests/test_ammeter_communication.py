import math

import pytest

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.client import AmmeterParseError
from tests.helpers import ask, refusing_port, running_emulator, serve_holding, serve_once


def _one_reading(framework, cls, name, command):
    with running_emulator(cls) as emu:
        fw = framework(
            ammeters={name: {"host": "localhost", "port": emu.port, "command": command}},
            testing={
                "client_timeout_seconds": 2,
                "sampling": {"measurements_count": 1, "sampling_frequency_hz": 20},
            },
        )
        return fw.run_test(name)


def test_tc01_greenlee_measurement(framework):
    result = _one_reading(framework, GreenleeAmmeter, "greenlee", "MEASURE_GREENLEE -get_measurement")
    assert result["status"] == "ok"
    assert math.isfinite(result["samples"][0]["value"])


def test_tc02_entes_measurement(framework):
    result = _one_reading(framework, EntesAmmeter, "entes", "MEASURE_ENTES -get_data")
    assert result["status"] == "ok"
    assert math.isfinite(result["samples"][0]["value"])


def test_tc03_circutor_measurement(framework):
    result = _one_reading(
        framework, CircutorAmmeter, "circutor", "MEASURE_CIRCUTOR -get_measurement -current")
    assert result["status"] == "ok"
    assert math.isfinite(result["samples"][0]["value"])


def test_tc04_connection_failure(framework):
    with refusing_port() as port:
        fw = framework(ammeters={"down": {"host": "127.0.0.1", "port": port, "command": "X"}})
        result = fw.run_test("down")
    assert result["status"] == "failed"
    assert result["metadata"]["error_count"] == len(result["samples"])
    assert all("AmmeterConnectionError" in err["error"] for err in result["metadata"]["errors"])


def test_tc05_communication_timeout(framework):
    port = serve_holding(hold=1.0, accepts=4)
    fw = framework(
        ammeters={"slow": {"host": "127.0.0.1", "port": port, "command": "X"}},
        testing={
            "client_timeout_seconds": 0.2,
            "sampling": {"measurements_count": 2, "sampling_frequency_hz": 100},
        },
    )
    result = fw.run_test("slow")
    assert result["status"] == "failed"
    assert all("AmmeterTimeoutError" in err["error"] for err in result["metadata"]["errors"])


@pytest.mark.parametrize("reply", [
    pytest.param(b"abc", id="nonnumeric"),
    pytest.param(b"nan", id="nan"),
    pytest.param(b"inf", id="infinity"),
])
def test_tc06_invalid_emulator_response(reply):
    with pytest.raises(AmmeterParseError, match="Unparsable reply"):
        ask(serve_once(reply))
