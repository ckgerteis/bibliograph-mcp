"""The `bibliograph` command.

    bibliograph install [--servers a,b] [--receipts-dir DIR] [--session SLUG] [--dry-run]
    bibliograph status
    bibliograph doctor
    bibliograph receipts verify-dir DIR | manifest DIR

`install` registers the servers that this environment already contains (they
are dependencies of this package) in Claude Desktop, with one receipts folder
and one session slug, asking for each credential once. It does not create a
second virtual environment: whatever interpreter runs `bibliograph` is the one
Claude Desktop will be pointed at. To build a fresh environment first, use
`install.py --all` from any of the six repositories, which this module wraps.
"""
from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
import time
from pathlib import Path

from . import __version__
from . import installer as I

SERVERS = I.SERVERS


# ---------------------------------------------------------------- helpers

def _scripts_dir() -> Path:
    return Path(sys.executable).parent


def _installed() -> dict[str, dict]:
    """Which of the six are importable from this interpreter, with versions."""
    out = {}
    for name, m in SERVERS.items():
        try:
            mod = importlib.import_module(m["pkg"])
            out[name] = {"version": getattr(mod, "__version__", "?"),
                         "exe": str(_scripts_dir() / (m["cmd"] + (".exe" if sys.platform == "win32" else "")))}
        except Exception as exc:  # noqa: BLE001 — a missing server is a report, not a crash
            out[name] = {"error": f"{type(exc).__name__}: {exc}"}
    return out


def _handshake(exe: str, timeout: float = 20.0) -> tuple[dict, list[str], str]:
    """initialize + tools/list over stdio. Returns (serverInfo, tool names, stderr)."""
    import threading

    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "bibliograph-doctor", "version": __version__}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    proc = subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8")
    got: dict[int, dict] = {}
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
                        done.set()
                        return
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


# ---------------------------------------------------------------- commands

def cmd_status(args: argparse.Namespace) -> int:
    cfg_path = I.config_path()
    cfg = I.load_config(cfg_path) if cfg_path.exists() else {}
    registered = cfg.get("mcpServers", {}) if isinstance(cfg, dict) else {}
    print(f"bibliograph {__version__}  python {sys.version.split()[0]}  {sys.executable}")
    print(f"Claude Desktop config: {cfg_path}{'' if cfg_path.exists() else '  (absent)'}")
    print()
    for name, m in SERVERS.items():
        inst = _installed()[name]
        reg = registered.get(name)
        v = inst.get("version", "-")
        where = "registered" if reg else "not registered"
        if reg and isinstance(reg, dict):
            env = reg.get("env") or {}
            where += f"; receipts {'on: ' + env['MCP_RECEIPT_DIR'] if env.get('MCP_RECEIPT_DIR') else 'off'}"
            if env.get("MCP_RECEIPT_SESSION"):
                where += f"; session {env['MCP_RECEIPT_SESSION']}"
        print(f"  {name:<18} {v:<8} {where}" + (f"  [{inst['error']}]" if "error" in inst else ""))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    ok = True
    inst = _installed()
    print("Handshake over stdio, one server at a time:")
    for name, m in SERVERS.items():
        if "error" in inst[name]:
            print(f"  FAIL {name}: not importable ({inst[name]['error']})")
            ok = False
            continue
        exe = inst[name]["exe"]
        if not Path(exe).exists():
            print(f"  FAIL {name}: console script missing at {exe}")
            ok = False
            continue
        t0 = time.monotonic()
        info, tools, err = _handshake(exe)
        dt = time.monotonic() - t0
        if not info:
            print(f"  FAIL {name}: no initialize reply in {dt:.1f}s" + (f"; stderr: {err.strip()[:200]}" if err.strip() else ""))
            ok = False
        else:
            print(f"  ok   {name:<18} {info.get('name')} {info.get('version')}  {len(tools)} tools  ({dt:.1f}s)")
    print()
    print("Vendored modules byte-identical across the installed family:")
    try:
        I.verify_identity(Path(sys.executable), [n for n in SERVERS if "error" not in inst[n]])
    except I.InstallError as exc:
        print(f"  FAIL {exc}")
        ok = False
    print()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def cmd_install(args: argparse.Namespace) -> int:
    inst = _installed()
    missing = [n for n in SERVERS if "error" in inst[n]]
    if args.servers:
        names = [s.strip() for s in args.servers.split(",") if s.strip()]
        bad = [n for n in names if n not in SERVERS]
        if bad:
            print(f"error: unknown server(s) {', '.join(bad)}; known: {', '.join(SERVERS)}", file=sys.stderr)
            return 2
    else:
        names = [n for n in SERVERS if n not in missing]
    absent = [n for n in names if n in missing]
    if absent:
        print(f"error: not importable from {sys.executable}: {', '.join(absent)}. "
              f"pip install bibliograph-mcp into this interpreter first.", file=sys.stderr)
        return 1

    # Reuse install.py's planning for config, receipts and credentials, but
    # with this environment as the venv and no pip step.
    ns = argparse.Namespace(
        servers=",".join(names), all=False, from_pypi=False, venv=str(sys.prefix),
        receipts_dir=args.receipts_dir, session=args.session, no_receipts=args.no_receipts,
        force_receipts_dir=args.force_receipts_dir, notification_filed=None,
        python_version=None, config_path=args.config_path, dry_run=args.dry_run, print_config=False,
    )
    try:
        plan_ = I.plan(ns, Path.cwd())
        plan_.python_exe = Path(sys.executable)
        installed = {n: {"exe": inst[n]["exe"], "version": inst[n]["version"]} for n in names}
        if not args.dry_run:
            I.verify_identity(plan_.python_exe, names)
        if plan_.chosen_dir and not args.dry_run:
            plan_.chosen_dir.mkdir(parents=True, exist_ok=True)
            I.write_receipts_readme(plan_.chosen_dir, names)
        servers_now = I.register(plan_, installed, dry_run=args.dry_run)
    except I.InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print()
    print("Registered in Claude Desktop:" if not args.dry_run else "Would register:")
    for n in names:
        print(f"  {n:<18} {installed[n]['version']:<8} {installed[n]['exe']}")
    if plan_.chosen_dir:
        print(f"Receipts: {plan_.chosen_dir}" + (f"  session {plan_.chosen_session}" if plan_.chosen_session else ""))
    others = sorted(set(servers_now) - set(names))
    if others:
        print(f"Left untouched: {', '.join(others)}")
    if not args.dry_run:
        print("Restart Claude Desktop to load them.")
    return 0


def cmd_receipts(args: argparse.Namespace) -> int:
    # Every server vendors the same ledger; use the first importable one.
    for m in SERVERS.values():
        try:
            ledger = importlib.import_module(m["pkg"] + ".ledger")
            break
        except Exception:  # noqa: BLE001
            continue
    else:
        print("error: no server package importable; nothing to verify with", file=sys.stderr)
        return 1
    if args.action == "verify-dir":
        res = ledger.verify_dir(args.dir)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("ok", False) else 1
    if args.action == "manifest":
        res = ledger.verify_dir(args.dir)
        out = Path(args.dir) / "manifest.json"
        out.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {out}")
        return 0 if res.get("ok", False) else 1
    return 2


# ---------------------------------------------------------------- entry

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bibliograph", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"bibliograph {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("install", help="register the installed servers in Claude Desktop")
    i.add_argument("--servers", help="comma-separated subset (default: every server importable here)")
    i.add_argument("--receipts-dir", help="folder for the hash-chained receipts (asked for if omitted)")
    i.add_argument("--force-receipts-dir", action="store_true",
                   help="allow --receipts-dir to differ from the folder already-registered servers use")
    i.add_argument("--session", help="project or article slug stamped on every receipt")
    i.add_argument("--no-receipts", action="store_true")
    i.add_argument("--config-path", help="claude_desktop_config.json to write (default: the platform's)")
    i.add_argument("--dry-run", action="store_true")
    i.set_defaults(fn=cmd_install)

    s = sub.add_parser("status", help="versions and registration state of the six")
    s.set_defaults(fn=cmd_status)

    d = sub.add_parser("doctor", help="stdio handshake with each server; vendored-file identity")
    d.set_defaults(fn=cmd_doctor)

    r = sub.add_parser("receipts", help="verify a receipts folder as one deposit")
    r.add_argument("action", choices=["verify-dir", "manifest"])
    r.add_argument("dir")
    r.set_defaults(fn=cmd_receipts)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
