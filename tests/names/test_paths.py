"""Tests for permanent-data-directory resolution."""
import os
import sys


from bibliograph.sources.names import paths  # noqa: E402


def test_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("JMNEDICT_DATA_DIR", str(tmp_path))
    assert paths.data_dir(create=False) == str(tmp_path)
    assert paths.db_path() == os.path.join(str(tmp_path), "names.sqlite")
    assert paths.raw_dir(create=False) == os.path.join(str(tmp_path), "raw")


def test_no_side_effect_without_create(tmp_path, monkeypatch):
    target = tmp_path / "notyet"
    monkeypatch.setenv("JMNEDICT_DATA_DIR", str(target))
    paths.data_dir(create=False)
    assert not target.exists()  # reading the path must not create it


def test_create_makes_dirs(tmp_path, monkeypatch):
    target = tmp_path / "made"
    monkeypatch.setenv("JMNEDICT_DATA_DIR", str(target))
    assert os.path.isdir(paths.data_dir(create=True))
    assert os.path.isdir(paths.raw_dir(create=True))


def test_default_when_env_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("JMNEDICT_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.data_dir(create=False) == os.path.join(str(tmp_path), "bibliograph-names")


def test_legacy_jmnedict_folder_still_used(tmp_path, monkeypatch):
    monkeypatch.delenv("JMNEDICT_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    legacy = tmp_path / "jmnedict-mcp"
    legacy.mkdir()
    (legacy / "names.sqlite").write_bytes(b"")
    assert paths.data_dir(create=False) == str(legacy)
