"""Public build: JDCat is opt-in. The shared tests were written for a build
that loads every source, so they run with it enabled; test_opt_in.py checks
the default."""
import pytest


@pytest.fixture(autouse=True)
def _jdcat_enabled_for_shared_tests(monkeypatch, request):
    if request.node.get_closest_marker("default_opt_in") is None:
        monkeypatch.setenv("BIBLIOGRAPH_ENABLE_JDCAT", "1")


def pytest_configure(config):
    config.addinivalue_line("markers", "default_opt_in: run without enabling opt-in sources")
