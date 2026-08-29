from pathlib import Path


def test_debian_package_build_skips_upstream_tests() -> None:
    rules = Path("packaging/debian/rules").read_text(encoding="utf-8")

    assert "override_dh_auto_test" in rules
    assert "dh_auto_test" not in rules.split("override_dh_auto_test", maxsplit=1)[1]


def test_github_test_workflow_runs_pytest_separately() -> None:
    workflow = Path(".github/workflows/test.yml").read_text(encoding="utf-8")

    assert "pip install \".[test]\"" in workflow
    assert "xvfb-run pytest" in workflow
    assert "libpulse0" in workflow


def test_qt_module_dependencies_are_declared_for_debian_packaging() -> None:
    control = Path("packaging/debian/control").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/package.yml").read_text(encoding="utf-8")

    assert "python3-pyqt6.qtmultimedia" in control
    assert "python3-pyqt6.qtmultimedia" in workflow
    assert "python3-pyqt6.qtsvg" in control
    assert "python3-pyqt6.qtsvg" in workflow
    assert "libpulse0" in workflow
