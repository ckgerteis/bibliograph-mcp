"""names_index: the in-server build for installs with no shell (the .mcpb bundle).

No network: the downloaders are replaced by small fixture files, so these tests
exercise the status reporting, the build-to-temp-then-rename step and the
refusal to start a second build, not the EDRDG downloads themselves.
"""

import json
import os
import sqlite3

import pytest

from bibliograph.sources.names import build_index as B
from bibliograph.sources.names import firstrun, paths


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JMNEDICT_DATA_DIR", str(tmp_path))
    return tmp_path


def _fixtures(tmp_path):
    files = {
        "jmnedict": {"words": B.DEMO_WORDS},
        "jmdict-eng": {"words": [{"id": "1", "kanji": [{"text": "書", "common": True}],
                                  "kana": [{"text": "しょ"}],
                                  "sense": [{"partOfSpeech": ["n"],
                                             "gloss": [{"lang": "eng", "text": "writing"}]}]}]},
        "kanjidic2-en": {"characters": [{"literal": "書", "misc": {"strokeCounts": [10]},
                                         "radicals": [], "readingMeaning": None,
                                         "queryCodes": []}]},
        "kradfile": {"kanji": {"書": ["聿", "日"]}},
        "radkfile": {"radicals": {"日": {"strokeCount": 4, "kanji": ["書"]}}},
    }
    out = {}
    for key, data in files.items():
        p = tmp_path / f"fixture-{key}.json"
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        out[key] = str(p)
    return out


def test_status_before_any_build(data_dir):
    st = firstrun.index_state()
    assert st["built"] is False
    assert st["build"] == {"state": "never_run"}
    assert st["data_dir"] == str(data_dir)
    assert "names_index(action='build')" in st["hint"]


def test_run_builds_to_temp_then_renames(data_dir, monkeypatch):
    fx = _fixtures(data_dir)
    monkeypatch.setattr(B, "_download_latest", lambda force=False: fx["jmnedict"])
    monkeypatch.setattr(B, "_download_asset", lambda prefix, force=False: fx[prefix])
    assert firstrun._run() == 0
    assert not os.path.exists(paths.db_path() + ".building")
    st = firstrun.index_state()
    assert st["built"] is True
    assert st["build"]["state"] == "done"
    for table in ("names", "jmdict", "kanjidic", "krad", "radk"):
        assert st["tables"][table] > 0, table
    assert st["tables"]["wiktionary"] == 0
    assert "gloss_archaic" in st["hint"]


def test_failed_build_is_reported_and_leaves_no_index(data_dir, monkeypatch):
    def boom(force=False):
        raise RuntimeError("network unreachable")
    monkeypatch.setattr(B, "_download_latest", boom)
    assert firstrun._run() == 1
    st = firstrun.index_state()
    assert st["built"] is False
    assert st["build"]["state"] == "failed"
    assert "network unreachable" in st["build"]["error"]
    assert not os.path.exists(paths.db_path())


def test_second_build_refused_while_one_runs(data_dir):
    firstrun._write_status(state="running", pid=os.getpid())
    res = firstrun.start_build()
    assert res["started"] is False
    assert "already running" in res["reason"]


def test_dead_build_reported_as_interrupted(data_dir):
    firstrun._write_status(state="running", pid=999999999)
    assert firstrun.index_state()["build"]["state"] == "interrupted"


def test_alive():
    assert firstrun._alive(None) is False
    assert firstrun._alive(os.getpid()) is True


def test_tool_answers_in_the_envelope(data_dir):
    from bibliograph.sources.names import server
    env = json.loads(server.names_index("status"))
    assert env["operation"] == "names_index"
    assert env["matching_mode"] == "not_a_search"
    assert env["items"][0]["record_type"] == "index_status"
    assert env["items"][0]["extra"]["built"] is False
