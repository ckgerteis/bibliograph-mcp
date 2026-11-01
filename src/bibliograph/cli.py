"""The `bibliograph` command (public distribution only).

    bibliograph install [--name bibliograph] [--receipts-dir DIR] [--session SLUG] [--dry-run] [--yes]
    bibliograph status
    bibliograph doctor
    bibliograph receipts verify FILE | verify-dir DIR | manifest DIR

Since 2.0.0 bibliograph is one MCP server (`bibliograph-mcp`) gathering every
source in one process. `install` registers that one server in Claude Desktop,
pointed at the interpreter running this command, with one receipts folder and
one session slug, asking once for each credential and keeping any value
already registered. It backs the config up first and never removes another
entry: servers registered by bibliograph 1.x (cinii, jstage, ndl, ...) are
named so they can be removed by hand, because leaving them doubles every tool.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from . import __version__

SERVER_CMD = "bibliograph-mcp"
# Keys bibliograph 1.x wrote; their tools are all inside bibliograph-mcp now.
LEGACY_KEYS = ("cinii", "jstage", "ndl", "korea_scholarship", "openalex", "semantic_scholar")
# (variable, prompt, required)
CREDENTIALS = [
    ("CINII_APPID", "CiNii application id (free, https://support.nii.ac.jp/en/cinii/api/developer); "
                    "needed only for researcher-number lookups", False),
    ("OPENALEX_API_KEY", "OpenAlex API key (free, https://openalex.org/settings/api); without one, "
                         "everyone on your network shares $0.10 of OpenAlex use a day", False),
    ("SEMANTIC_SCHOLAR_API_KEY", "Semantic Scholar API key (free on request); without one, calls share "
                                 "a throttled pool", False),
    ("CROSSREF_MAILTO", "Contact email for Crossref's faster polite pool", False),
    ("KCI_API_KEY", "KCI Open API key, for the Korean citation index's REST tools", False),
]


def config_path() -> Path:
    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise SystemExit("APPDATA is not set; cannot find Claude Desktop's config.")
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def server_exe() -> Path:
    import sysconfig
    scripts = Path(sysconfig.get_path("scripts") or Path(sys.executable).parent)
    exe = scripts / (SERVER_CMD + (".exe" if sys.platform == "win32" else ""))
    if not exe.exists():
        found = shutil.which(SERVER_CMD)
        if found:
            return Path(found)
    return exe


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except ValueError as exc:
        raise SystemExit(f"{path} is not valid JSON ({exc}); fix or move it, then rerun.")
    return data if isinstance(data, dict) else {}


def build_entry(existing: dict, answers: dict) -> dict:
    """The one mcpServers entry. Existing env values are kept unless answered anew."""
    env = dict((existing or {}).get("env") or {})
    for k, v in answers.items():
        if v:
            env[k] = v
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return {"command": str(server_exe()), "args": [], "env": env}


def _ask(prompt: str, current: Optional[str], assume_yes: bool) -> Optional[str]:
    if assume_yes or not sys.stdin.isatty():
        return current
    shown = " [already set: keep]" if current else " [blank to skip]"
    got = input(f"{prompt}{shown}: ").strip()
    return got or current


def cmd_install(a: argparse.Namespace) -> int:
    path = config_path()
    cfg = load_config(path)
    servers = cfg.setdefault("mcpServers", {})
    old = servers.get(a.name) if isinstance(servers.get(a.name), dict) else {}
    old_env = old.get("env") or {}
    answers: dict = {}
    for var, prompt, _req in CREDENTIALS:
        answers[var] = _ask(prompt, old_env.get(var), a.yes)
    answers["MCP_RECEIPT_DIR"] = a.receipts_dir or _ask(
        "Receipts folder (a hash-chained record of every query; blank for none)",
        old_env.get("MCP_RECEIPT_DIR"), a.yes)
    answers["MCP_RECEIPT_SESSION"] = a.session or _ask(
        "Session slug for the receipts (e.g. a project name)", old_env.get("MCP_RECEIPT_SESSION"), a.yes)
    entry = build_entry(old, answers)
    legacy = [k for k in LEGACY_KEYS if k in servers]
    if a.dry_run:
        shown = dict(entry, env={k: ("<set>" if v else v) for k, v in entry["env"].items()})
        print(json.dumps({a.name: shown}, indent=2))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            backup = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(path, backup)
            print(f"Backed up {path.name} to {backup.name}")
        servers[a.name] = entry
        path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Registered '{a.name}' -> {entry['command']}")
    if not entry["command"] or not Path(entry["command"]).exists():
        print(f"warning: {SERVER_CMD} was not found next to this interpreter; is bibliograph-mcp installed here?")
    if legacy:
        print("\nbibliograph 1.x entries are still registered: " + ", ".join(legacy) + ".\n"
              "Their tools are all inside bibliograph-mcp now; remove those entries from\n"
              f"{path} so Claude Desktop does not list every tool twice.")
    print("\nRestart Claude Desktop to load it.")
    return 0


def handshake(exe: str, timeout: float = 30.0) -> tuple[dict, list[str], str]:
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "bibliograph-doctor", "version": __version__}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    proc = subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8")
    got: dict = {}
    done = threading.Event()

    def reader():
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("{"):
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("id") in (1, 2):
                    got[d["id"]] = d
                    if len(got) == 2:
                        break
        done.set()

    threading.Thread(target=reader, daemon=True).start()
    for m in msgs:
        proc.stdin.write(json.dumps(m) + "\n")
    proc.stdin.flush()
    done.wait(timeout)
    try:
        proc.stdin.close()
        proc.wait(timeout=5)
    except Exception:  # noqa: BLE001
        proc.kill()
    err = proc.stderr.read() if proc.stderr else ""
    info = got.get(1, {}).get("result", {}).get("serverInfo", {})
    tools = sorted(t["name"] for t in got.get(2, {}).get("result", {}).get("tools", []))
    return info, tools, err


def cmd_status(a: argparse.Namespace) -> int:
    path = config_path()
    entry = load_config(path).get("mcpServers", {}).get(a.name)
    print(f"bibliograph {__version__}  python {sys.version.split()[0]}  {sys.executable}")
    print(f"Claude Desktop config: {path}{'' if path.exists() else '  (absent)'}")
    if isinstance(entry, dict):
        env = entry.get("env") or {}
        print(f"  '{a.name}' registered -> {entry.get('command')}")
        print(f"  receipts {'on: ' + env['MCP_RECEIPT_DIR'] if env.get('MCP_RECEIPT_DIR') else 'off'}"
              + (f"; session {env['MCP_RECEIPT_SESSION']}" if env.get("MCP_RECEIPT_SESSION") else ""))
    else:
        print(f"  '{a.name}' not registered; run `bibliograph install`")
    return 0


def cmd_doctor(a: argparse.Namespace) -> int:
    exe = server_exe()
    if not exe.exists():
        print(f"FAIL: {SERVER_CMD} not found at {exe}")
        return 1
    info, tools, err = handshake(str(exe))
    if not tools:
        print(f"FAIL: {SERVER_CMD} did not answer initialize and tools/list.\n{err[-2000:]}")
        return 1
    print(f"OK: {info.get('name')} {info.get('version')} answered with {len(tools)} tools.")
    skipped = [l for l in err.splitlines() if "skipped" in l]
    for l in skipped:
        print("  " + l)
    return 0


def cmd_receipts(a: argparse.Namespace) -> int:
    from . import ledger
    sys.argv = ["bibliograph receipts", *a.rest]
    ledger._cli()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bibliograph", description="Register and check the bibliograph MCP server.")
    p.add_argument("--version", action="version", version=f"bibliograph {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("install", help="register bibliograph-mcp in Claude Desktop")
    i.add_argument("--name", default="bibliograph", help="the mcpServers key (default: bibliograph)")
    i.add_argument("--receipts-dir")
    i.add_argument("--session")
    i.add_argument("--dry-run", action="store_true", help="print the entry; write nothing")
    i.add_argument("--yes", action="store_true", help="ask nothing; keep registered values")
    i.set_defaults(fn=cmd_install)
    s = sub.add_parser("status", help="what is registered")
    s.add_argument("--name", default="bibliograph")
    s.set_defaults(fn=cmd_status)
    d = sub.add_parser("doctor", help="start bibliograph-mcp and list its tools")
    d.set_defaults(fn=cmd_doctor)
    r = sub.add_parser("receipts", help="verify or summarise a receipts folder")
    r.add_argument("rest", nargs=argparse.REMAINDER)
    r.set_defaults(fn=cmd_receipts)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    a = build_parser().parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
