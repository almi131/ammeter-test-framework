import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"


def _check_ci(os_name):
    text = WORKFLOW.read_text(encoding="utf-8")
    assert os_name in text
    for command in ("python -m pytest", "python main.py", "python examples/run_tests.py"):
        assert command in text


def test_tc38_ubuntu_ci():
    _check_ci("ubuntu-latest")


def test_tc39_windows_ci():
    _check_ci("windows-latest")


def test_tc40_macos_ci():
    _check_ci("macos-latest")


def test_plan_maps_to_existing_tests():
    plan = (ROOT / "docs" / "TEST_PLAN.md").read_text(encoding="utf-8")
    sources = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "tests").glob("test_*.py"))
    cases = re.findall(r"^\| (TC-\d+) \|.*?\| (.*?) \| `test_\w+\.py` \|$", plan, re.M)
    assert [c for c, _ in cases] == [f"TC-{i:02d}" for i in range(1, 41)]
    for case, names in cases:
        for name in re.findall(r"`(test_\w+)`", names):
            assert f"def {name}(" in sources, f"{case}: {name} not found"
