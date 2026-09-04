"""CLI tests against a temporary Claude Desktop config. No network."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from bibliograph import cli, installer


def test_status_runs(capsys):
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "bibliograph" in out and "cinii" in out


def test_install_dry_run_writes_nothing(tmp_path, capsys, monkeypatch):
    cfg = tmp_path / "claude_desktop_config.json"
    monkeypatch.setattr(installer, "default_receipts_dir", lambda: tmp_path / "receipts")
    rc = cli.main(["install", "--dry-run", "--no-receipts", "--config-path", str(cfg)])
    assert rc == 0
    assert not cfg.exists()
    assert "Would register" in capsys.readouterr().out


def test_install_writes_config_and_leaves_others(tmp_path, monkeypatch):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(json.dumps({"mcpServers": {"other_tool": {"command": "x"}}}), encoding="utf-8")
    monkeypatch.setattr("sys.stdin", open(__file__))  # non-interactive: no prompts
    rc = cli.main(["install", "--servers", "jstage,ndl", "--receipts-dir", str(tmp_path / "r"),
                   "--session", "t", "--config-path", str(cfg)])
    assert rc == 0
    data = json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"]
    assert data["other_tool"] == {"command": "x"}
    assert data["jstage"]["env"]["MCP_RECEIPT_DIR"] == str((tmp_path / "r").resolve())
    assert data["ndl"]["env"]["MCP_RECEIPT_SESSION"] == "t"
    assert Path(data["jstage"]["command"]).name.startswith("jstage-mcp")
    assert (tmp_path / "r" / "README.md").exists()
    backups = list(tmp_path.glob("claude_desktop_config.json.*.bak"))
    assert len(backups) == 1


def test_install_refuses_receipts_fork(tmp_path, capsys):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(json.dumps({"mcpServers": {"cinii": {"command": "x", "env": {"MCP_RECEIPT_DIR": str(tmp_path / "a")}}}}), encoding="utf-8")
    rc = cli.main(["install", "--servers", "ndl", "--receipts-dir", str(tmp_path / "b"), "--config-path", str(cfg), "--dry-run"])
    assert rc == 1
    assert "differs from the folder" in capsys.readouterr().err


def test_receipts_verify_dir_empty(tmp_path, capsys):
    rc = cli.main(["receipts", "verify-dir", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert "files" in out and out["files"] == []
