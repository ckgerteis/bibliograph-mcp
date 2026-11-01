"""Permanent data-directory resolution.

The dictionary datasets — the raw downloads (hundreds of MB) and the built
SQLite index — must live in a stable location *outside the code repo*, so that
updating or reinstalling the code never wipes a slow rebuild, and so the builder
and the server always agree on where the data is.

Resolution order for the data directory:
  1. ``JMNEDICT_DATA_DIR`` environment variable, if set (recommended — the MCP
     config sets this explicitly).
  2. A per-OS default under the user's local application data:
       Windows : %LOCALAPPDATA%\\bibliograph-names
       Linux   : $XDG_DATA_HOME/bibliograph-names  (or ~/.local/share/bibliograph-names)
       macOS   : ~/Library/Application Support/bibliograph-names
     An index already built under the old jmnedict-mcp folder name is used
     in preference, so an upgrade does not force a rebuild.

Directory creation is explicit (``create=True``) so importing this module has no
filesystem side effects — the builder creates the dirs, readers do not.
"""

from __future__ import annotations

import os
import sys


def _default_base() -> str:
    env = os.environ.get("JMNEDICT_DATA_DIR")
    if env:
        return env
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local"
        )
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "share"
        )
    # bibliograph's own default. An index built under the retired jmnedict-mcp
    # default is still found, so an upgrade does not force a rebuild.
    legacy = os.path.join(base, "jmnedict-mcp")
    if os.path.exists(os.path.join(legacy, "names.sqlite")):
        return legacy
    return os.path.join(base, "bibliograph-names")


def data_dir(create: bool = False) -> str:
    """Return the permanent data directory. If create=True, ensure it exists.

    When JMNEDICT_DATA_DIR is set it is used verbatim; otherwise a per-OS default
    is used.
    """
    d = os.environ.get("JMNEDICT_DATA_DIR") or _default_base()
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def db_path() -> str:
    """Path to the built SQLite index inside the data directory."""
    return os.path.join(data_dir(create=False), "names.sqlite")


def raw_dir(create: bool = False) -> str:
    """Directory for cached raw downloads (jmnedict json, kaikki jsonl)."""
    r = os.path.join(data_dir(create=create), "raw")
    if create:
        os.makedirs(r, exist_ok=True)
    return r
