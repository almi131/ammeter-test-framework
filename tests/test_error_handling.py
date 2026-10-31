from Ammeters.client import AmmeterConnectionError


def test_tc26_partial_measurement_failure(framework):
    fw = framework()
    pending = [None, 2.0, None, 4.0]

    def read():
        value = pending.pop(0)
        if value is None:
            raise AmmeterConnectionError("down")
        return value

    fw.register_ammeter("meter", read)
    result = fw.run_test("meter")
    assert result["status"] == "partial"
    assert [s["value"] for s in result["samples"]] == [None, 2.0, None, 4.0]
    assert [e["index"] for e in result["metadata"]["errors"]] == [0, 2]
    assert result["stats"]["count"] == 2
    assert result["stats"]["mean"] == 3.0


def test_tc27_complete_measurement_failure(framework):
    fw = framework()

    def down():
        raise AmmeterConnectionError("down")

    fw.register_ammeter("meter", down)
    result = fw.run_test("meter")
    assert result["status"] == "failed"
    assert result["stats"] == {"count": 0}
    assert "mean" not in result["stats"]
    assert result["metadata"]["error_count"] == len(result["samples"])
    assert all(s["error"] for s in result["samples"])
