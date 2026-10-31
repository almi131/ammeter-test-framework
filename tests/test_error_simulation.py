import pytest


@pytest.mark.parametrize("mode, needle", [
    pytest.param("connection_failure", "simulated connection failure", id="connection_failure"),
    pytest.param("timeout", "simulated timeout", id="timeout"),
    pytest.param("invalid_response", "Non-finite", id="invalid_response"),
    pytest.param("intermittent_failure", "simulated intermittent failure", id="intermittent_failure"),
])
def test_tc32_error_simulation(mode, needle, framework):
    rate = 0.5 if mode == "intermittent_failure" else True
    fw = framework(testing={
        "sampling": {"measurements_count": 8, "sampling_frequency_hz": 100},
        "error_simulation": {"enabled": True, "seed": 1, mode: rate},
    })
    fw.register_ammeter("meter", lambda: 3.25)
    result = fw.run_test("meter")
    assert len(result["samples"]) == 8
    if mode == "intermittent_failure":
        # random.Random(1), rate 0.5: fail indexes 0, 3, 4, 5
        assert [s["index"] for s in result["samples"] if s["error"]] == [0, 3, 4, 5]
        assert result["status"] == "partial"
        assert result["stats"]["count"] == 4
        assert result["stats"]["mean"] == pytest.approx(3.25)
        assert all(needle in s["error"] for s in result["samples"] if s["error"])
    else:
        assert result["status"] == "failed"
        assert result["stats"] == {"count": 0}
        assert all(needle in s["error"] for s in result["samples"])


def test_tc32_disabled_simulation_keeps_valid_samples(framework):
    configs = (
        {},
        {"error_simulation": {"enabled": False, "connection_failure": True, "seed": 1}},
    )
    for testing in configs:
        fw = framework(testing=testing)
        fw.register_ammeter("meter", lambda: 1.5)
        result = fw.run_test("meter")
        assert result["status"] == "ok"
        assert all(s["value"] == 1.5 and s["error"] is None for s in result["samples"])
        assert "error_simulation" not in result["metadata"]
