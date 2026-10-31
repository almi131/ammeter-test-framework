import pytest

from src.testing.test_framework import AmmeterTestFramework
from tests.helpers import ManualClock


@pytest.fixture
def framework(tmp_path):
    """Build a framework whose results stay in tmp_path. clock=True skips real sleeps."""

    def factory(testing=None, clock=True, ammeters=None):
        config = {
            "testing": {
                "sampling": {"measurements_count": 4, "sampling_frequency_hz": 100},
                "client_timeout_seconds": 0.5,
            },
        }
        if testing:
            config["testing"].update(testing)
        if ammeters:
            config["ammeters"] = ammeters
        clk = ManualClock() if clock is True else clock
        return AmmeterTestFramework(config=config, results_dir=str(tmp_path), clock=clk)

    return factory


def _failure_message(report):
    crash = getattr(report.longrepr, "reprcrash", None)
    if crash is not None:
        return crash.message
    lines = str(report.longrepr).strip().splitlines()
    return lines[-1] if lines else ""


def pytest_addoption(parser):
    parser.addoption(
        "--results-list",
        action="store_true",
        default=False,
        help="after the run, list each test name, PASSED or FAILED, and the error line",
    )


def pytest_terminal_summary(terminalreporter, config):
    """Optional name-by-name list. Plain pytest keeps the short progress output."""
    if not config.getoption("results_list"):
        return
    rows = []
    for outcome in ("passed", "failed", "error", "skipped"):
        for report in terminalreporter.stats.get(outcome, []):
            if outcome == "passed" and report.when != "call":
                continue
            rows.append((report.nodeid, outcome, report))
    rows.sort(key=lambda row: row[0])

    terminalreporter.write_sep("=", "test results")
    passed = failed = 0
    for nodeid, outcome, report in rows:
        label = "FAILED" if outcome in ("failed", "error") else outcome.upper()
        terminalreporter.write_line(f"{nodeid}  {label}")
        if outcome in ("failed", "error"):
            failed += 1
            terminalreporter.write_line(f"    {_failure_message(report)}")
        elif outcome == "passed":
            passed += 1
    terminalreporter.write_sep("-", f"passed: {passed}  failed: {failed}")
