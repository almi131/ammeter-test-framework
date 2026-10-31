import pytest

from src.testing.test_framework import AmmeterTestFramework
from src.utils.config import ConfigError


def test_tc33_load_configuration(tmp_path):
    fw = AmmeterTestFramework("config/config.yaml", results_dir=str(tmp_path))
    assert fw.specs["greenlee"].port == 5001
    assert fw.specs["greenlee"].command == "MEASURE_GREENLEE -get_measurement"
    assert fw.specs["entes"].port == 5002
    assert fw.specs["entes"].command == "MEASURE_ENTES -get_data"
    assert fw.specs["circutor"].port == 5003
    assert fw.specs["circutor"].command == "MEASURE_CIRCUTOR -get_measurement -current"
    plan = fw.plan_for()
    assert (plan.count, plan.duration_s, plan.frequency_hz) == (20, 2.0, 10.0)
    assert fw.timeout == 3.0
    assert fw.error_simulation is None
    assert fw.reference_current_a is None


@pytest.mark.parametrize("case", [
    "missing_file", "invalid_yaml", "missing_port", "bad_port", "bad_sampling",
])
def test_tc34_invalid_configuration(case, tmp_path, framework):
    if case == "missing_file":
        with pytest.raises(FileNotFoundError):
            AmmeterTestFramework(str(tmp_path / "missing.yaml"))
    elif case == "invalid_yaml":
        path = tmp_path / "bad.yaml"
        path.write_text("testing: [\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="Invalid YAML"):
            AmmeterTestFramework(str(path))
    elif case == "missing_port":
        with pytest.raises(ConfigError, match="port"):
            AmmeterTestFramework(config={"ammeters": {"meter": {"command": "X"}}})
    elif case == "bad_port":
        with pytest.raises(ConfigError, match="port"):
            AmmeterTestFramework(config={"ammeters": {"meter": {"port": 70000, "command": "X"}}})
    else:
        fw = framework()
        calls = []
        fw.register_ammeter("meter", lambda: calls.append(1) or 1.0)
        with pytest.raises(ConfigError, match="positive number"):
            fw.run_test("meter", sampling={"measurements_count": 0, "sampling_frequency_hz": 10})
        assert calls == []
