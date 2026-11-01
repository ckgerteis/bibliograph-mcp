"""bibliograph - one MCP server for Japan-studies bibliographic and archival search.

Each source is its own module under bibliograph.sources and registers its tools on its
own server object, exactly as it did when it shipped as a separate package. This
module gathers those tools into one server named "bibliograph". Nothing about a
source's behaviour changes here: its rate limits, NDL undertakings, credit lines,
diagnostics and receipts are its own, and every tool keeps its old name.

    bibliograph-mcp                      all sources
    bibliograph-mcp --only cinii,ndl     only those sources (a smaller tool list)
    bibliograph-mcp --with PKG.MODULE    also load an outside package that honours the
                                    bibliograph contract (e.g. korea_scholarship_mcp.server)
    bibliograph-mcp --list               print the source keys and exit

BIBLIOGRAPH_ONLY and BIBLIOGRAPH_WITH (comma-separated) do the same from the environment,
for clients that cannot pass arguments.

A source that fails to import is skipped and reported by bibliograph_status; it never
takes the other sources down with it.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata as md
import json
import os
import sys
import time
from typing import Iterable, Optional

try:  # mcp SDK 1.x
    from mcp.server.fastmcp import FastMCP as _MCPServer
except ModuleNotFoundError:  # mcp SDK 2.x
    from mcp.server.mcpserver import MCPServer as _MCPServer

from . import __version__

# key -> module. Order is the order tools are listed in: the NDL group, then the
# other Japanese sources, then the worldwide indexes, then the name tools, then
# fetch, which acts on what the others found.
SOURCES: dict[str, str] = {
    "ndl": "bibliograph.sources.ndl.server",
    "ndl_dl": "bibliograph.sources.ndl_dl.server",
    "warp": "bibliograph.sources.warp.server",
    "cinii": "bibliograph.sources.cinii.server",
    "jstage": "bibliograph.sources.jstage.server",
    "jdcat": "bibliograph.sources.jdcat.server",
    "openalex": "bibliograph.sources.openalex.server",
    "semantic_scholar": "bibliograph.sources.semantic_scholar.server",
    "crossref": "bibliograph.sources.crossref.server",
    "names": "bibliograph.sources.names.server",
    "fetch": "bibliograph.sources.fetch.server",
}


# Sources loaded only on request in the public build: key -> enabling variable.
OPT_IN: dict[str, str] = {"jdcat": "BIBLIOGRAPH_ENABLE_JDCAT"}


def _split(v: Optional[str]) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def _new_server() -> _MCPServer:
    try:
        return _MCPServer("bibliograph", version=__version__)
    except TypeError:  # mcp 1.x FastMCP takes no version: set it on the low-level server
        srv = _MCPServer("bibliograph")
        low = getattr(srv, "_mcp_server", None)
        if low is not None and hasattr(low, "version"):
            low.version = __version__
        return srv


def _registry(srv) -> dict:
    """The SDK's tool table. Internal in mcp 1.26 and 2.2; test_server.py pins it."""
    return srv._tool_manager._tools


class Suite:
    """The gathered server and the record of what loaded."""

    def __init__(self, only: Iterable[str] = (), extra: Iterable[str] = ()):
        self.mcp = _new_server()
        self.loaded: list[dict] = []
        self.skipped: list[dict] = []
        self.modules: dict = {}
        only = list(only)
        unknown = [k for k in only if k not in SOURCES]
        for k in unknown:
            self.skipped.append({"source": k, "reason": "unknown source key; see --list"})
        keys = [k for k in SOURCES if k in only] if only else []
        for k in ([] if only else SOURCES):
            gate = OPT_IN.get(k)
            if gate and os.environ.get(gate, "").strip().lower() not in ("1", "true", "yes", "on"):
                self.skipped.append({"source": k, "reason": f"opt-in; set {gate}=1 to load (see README, JDCat access)"})
            else:
                keys.append(k)
        for key in keys:
            self._load(key, SOURCES[key])
        for module in extra:
            self._load(module.split(".")[0], module, outside=True)
        self._add_status()

    def _load(self, key: str, module: str, outside: bool = False) -> None:
        t0 = time.perf_counter()
        try:
            mod = importlib.import_module(module)
            src = next(v for v in vars(mod).values() if isinstance(v, _MCPServer))
            version = getattr(mod, "__version__", None)
            if outside:
                version = version or md.version(module.split(".")[0].replace("_", "-"))
        except Exception as exc:  # noqa: BLE001 - one failed source must not stop the rest
            self.skipped.append({"source": key, "reason": f"{type(exc).__name__}: {exc}"})
            print(f"[bibliograph] skipped {key}: {type(exc).__name__}: {exc}", file=sys.stderr)
            return
        self.modules[key] = mod
        table = _registry(self.mcp)
        names = []
        for name, tool in _registry(src).items():
            if name in table:
                print(f"[bibliograph] duplicate tool {name} from {key}; kept the first", file=sys.stderr)
                continue
            table[name] = tool
            names.append(name)
        self.loaded.append({"source": key, "version": version, "outside": outside,
                            "tools": names, "import_seconds": round(time.perf_counter() - t0, 3)})

    def status(self) -> dict:
        try:
            mcp_version = md.version("mcp")
        except md.PackageNotFoundError:  # pragma: no cover
            mcp_version = None
        out = {"bibliograph": __version__, "python": sys.version.split()[0], "mcp": mcp_version,
               "loaded": self.loaded, "skipped": self.skipped}
        # A source may report its own allowance (openalex: the day's budget).
        # Asked at call time, so the figure is current; a failure is reported, not raised.
        budgets = {}
        for key, mod in self.modules.items():
            fn = getattr(mod, "budget_snapshot", None)
            if callable(fn):
                try:
                    budgets[key] = fn()
                except Exception as exc:  # noqa: BLE001
                    budgets[key] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
        if budgets:
            out["budgets"] = budgets
        return out

    def _add_status(self) -> None:
        suite = self

        @self.mcp.tool(name="bibliograph_status")
        def bibliograph_status() -> str:
            """Which sources this bibliograph server loaded, each with its version and
tools, and any source that was skipped with the reason. Name these versions when
a search result is cited: a count is reproducible only against the release that
made it. Also reports the day's OpenAlex budget (spent, remaining, reset time and
OpenAlex's current price per request type): check it before a large sweep."""
            return json.dumps(suite.status(), ensure_ascii=False, indent=1)


def _parse(argv: Optional[list[str]]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="bibliograph-mcp", description="bibliograph: one MCP server "
                                "for Japan-studies bibliographic and archival search.")
    p.add_argument("--only", help="comma-separated source keys to load (default: all)")
    p.add_argument("--with", dest="extra", help="comma-separated outside modules to load")
    p.add_argument("--list", action="store_true", help="print the source keys and exit")
    p.add_argument("--version", action="version", version=f"bibliograph-mcp {__version__}")
    return p.parse_args(argv)


def _default_with() -> list[str]:
    """The public build loads korea-scholarship-mcp (a dependency) unless --only,
    --with or BIBLIOGRAPH_NO_DEFAULT_WITH says otherwise."""
    if os.environ.get("BIBLIOGRAPH_NO_DEFAULT_WITH"):
        return []
    return ["korea_scholarship_mcp.server"]


def build(argv: Optional[list[str]] = None) -> Suite:
    a = _parse(argv)
    only = _split(a.only) or _split(os.environ.get("BIBLIOGRAPH_ONLY"))
    extra = (_split(a.extra) or _split(os.environ.get("BIBLIOGRAPH_WITH"))
             or ([] if only else _default_with()))  # --only means only
    return Suite(only=only, extra=extra)


def main(argv: Optional[list[str]] = None) -> None:
    a = _parse(argv)
    if a.list:
        for k, m in SOURCES.items():
            print(f"{k:18} {m}")
        return
    build(argv).mcp.run()


if __name__ == "__main__":
    main()
