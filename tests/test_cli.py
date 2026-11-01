"""The public `bibliograph` command: one entry, values kept, nothing removed."""
import json

from bibliograph import cli


def test_install_writes_one_entry_and_keeps_others(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(json.dumps({"mcpServers": {
        "cinii": {"command": "x"}, "other": {"command": "y"},
        "bibliograph": {"command": "old", "env": {"CINII_APPID": "keepme"}}}}), encoding="utf-8")
    monkeypatch.setattr(cli, "config_path", lambda: cfg)
    assert cli.main(["install", "--yes", "--receipts-dir", str(tmp_path / "r"), "--session", "s1"]) == 0
    data = json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"]
    assert set(data) == {"cinii", "other", "bibliograph"}
    env = data["bibliograph"]["env"]
    assert env["CINII_APPID"] == "keepme" and env["MCP_RECEIPT_SESSION"] == "s1"
    assert data["bibliograph"]["command"].endswith(("bibliograph-mcp", "bibliograph-mcp.exe"))
    assert list(tmp_path.glob("claude_desktop_config.json.bak-*"))
    assert "cinii" in capsys.readouterr().out  # the 1.x entry is named for removal


def test_dry_run_writes_nothing_and_hides_values(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "claude_desktop_config.json"
    monkeypatch.setattr(cli, "config_path", lambda: cfg)
    monkeypatch.setenv("X", "1")
    cli.main(["install", "--yes", "--dry-run", "--session", "secret-slug"])
    assert not cfg.exists()
    assert "secret-slug" not in capsys.readouterr().out


def test_receipts_passes_through(tmp_path, capsys):
    import pytest
    with pytest.raises(SystemExit):
        cli.main(["receipts", "verify-dir", str(tmp_path)])
