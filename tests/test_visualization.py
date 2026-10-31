import pytest

from src.testing.visualization import plot_results


def _sample(index, actual_s, value):
    return {"index": index, "scheduled_s": actual_s, "actual_s": actual_s,
            "value": value, "error": None, "latency_ms": 0.0}


def test_tc31_measurement_visualization(tmp_path, monkeypatch):
    pytest.importorskip("matplotlib")
    from matplotlib.figure import Figure

    captured = {}
    original = Figure.savefig

    def spy(self, filename, *args, **kwargs):
        captured["titles"] = [ax.get_title() for ax in self.axes]
        captured["labels"] = [(ax.get_xlabel(), ax.get_ylabel()) for ax in self.axes]
        captured["series"] = [(list(line.get_xdata()), list(line.get_ydata()))
                              for ax in self.axes for line in ax.get_lines()]
        captured["notes"] = [text.get_text() for ax in self.axes for text in ax.texts]
        return original(self, filename, *args, **kwargs)

    monkeypatch.setattr(Figure, "savefig", spy)
    results = {
        "greenlee": {"samples": [_sample(0, 0.0, 1.5), _sample(1, 0.1, 2.5)]},
        "entes": {"samples": [
            {"index": 0, "scheduled_s": 0.0, "actual_s": 0.0, "value": None,
             "error": "AmmeterTimeoutError: boom", "latency_ms": 0.0},
        ]},
    }
    path = plot_results(results, tmp_path / "chart.png")
    assert path == tmp_path / "chart.png"
    assert path.read_bytes().startswith(b"\x89PNG")
    assert any("GREENLEE" in title for title in captured["titles"])
    assert any("ENTES" in title for title in captured["titles"])
    assert ("time (s)", "current (A)") in captured["labels"]
    assert any(xs == [0.0, 0.1] and ys == [1.5, 2.5] for xs, ys in captured["series"])
    assert "No valid samples" in captured["notes"]
