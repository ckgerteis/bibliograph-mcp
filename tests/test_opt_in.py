"""JDCat loads only on request in the public build (decided 1 Nov 2026)."""
import json

import pytest

from bibliograph import server as S

pytestmark = pytest.mark.default_opt_in


def _sources(suite):
    return [x["source"] for x in suite.loaded]


def test_jdcat_is_off_by_default_and_says_why(monkeypatch):
    monkeypatch.delenv("BIBLIOGRAPH_ENABLE_JDCAT", raising=False)
    suite = S.Suite()
    assert "jdcat" not in _sources(suite)
    why = [x for x in suite.skipped if x["source"] == "jdcat"]
    assert why and "BIBLIOGRAPH_ENABLE_JDCAT" in why[0]["reason"]
    assert not any(n.startswith("jdcat_") for n in S._registry(suite.mcp))


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_enabling_variable_loads_it(monkeypatch, value):
    monkeypatch.setenv("BIBLIOGRAPH_ENABLE_JDCAT", value)
    assert "jdcat" in _sources(S.Suite())


@pytest.mark.parametrize("value", ["", "0", "false", "${user_config.enable_jdcat}"])
def test_other_values_leave_it_off(monkeypatch, value):
    monkeypatch.setenv("BIBLIOGRAPH_ENABLE_JDCAT", value)
    assert "jdcat" not in _sources(S.Suite())


def test_naming_it_in_only_loads_it(monkeypatch):
    monkeypatch.delenv("BIBLIOGRAPH_ENABLE_JDCAT", raising=False)
    assert _sources(S.Suite(only=["jdcat"])) == ["jdcat"]


def test_manifest_offers_both_settings():
    from pathlib import Path
    m = json.loads((Path(__file__).resolve().parents[1] / "mcpb" / "manifest.template.json").read_text("utf-8"))
    uc = m["user_config"]
    assert uc["enable_jdcat"]["type"] == "boolean" and uc["enable_jdcat"]["default"] is False
    assert uc["kci_api_key"]["sensitive"] is True
    env = m["server"]["mcp_config"]["env"]
    assert env["KCI_API_KEY"] == "${user_config.kci_api_key}"
    assert env["BIBLIOGRAPH_ENABLE_JDCAT"] == "${user_config.enable_jdcat}"
