"""Build the names index from inside the server, for installs with no command line.

The Claude Desktop bundle gives a user no shell, so ``bibliograph-build-names`` is out
of reach and every names tool would answer INDEX_MISSING. The ``names_index``
tool calls into this module instead:

- ``index_state()`` reports where the index lives, which tables it holds and how
  far any build has got. It never touches the network.
- ``start_build()`` starts one background build and returns at once. The build
  runs in a separate process (``python -m bibliograph.sources.names.firstrun --run``)
  so a slow download never holds a tool call open.

The build writes to ``names.sqlite.building`` and renames it over
``names.sqlite`` only when every table is in, so a half-built index is never
read. Progress goes to ``build-status.json`` and ``build.log`` in the data
directory. Wiktionary (``gloss_archaic``) is not part of this build: its source
file is large and is fetched by hand; see the README.
"""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
import subprocess
import sys
import traceback

from . import paths

STATUS_FILE = "build-status.json"
LOG_FILE = "build.log"
TABLES = ("names", "jmdict", "kanjidic", "krad", "radk", "wiktionary")
SOURCE = ("EDRDG JMnedict, JMdict, KANJIDIC2, KRADFILE and RADKFILE, as packaged by "
          "jmdict-simplified (github.com/scriptin/jmdict-simplified); EDRDG licence, "
          "CC BY-SA 4.0")


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _status_path() -> str:
    return os.path.join(paths.data_dir(create=True), STATUS_FILE)


def _log_path() -> str:
    return os.path.join(paths.data_dir(create=True), LOG_FILE)


def _read_status() -> dict:
    try:
        with open(_status_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _write_status(**fields) -> None:
    status = _read_status()
    status.update(fields)
    tmp = _status_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _status_path())


def _alive(pid) -> bool:
    """Whether a process is still running. Never signals it: on Windows
    os.kill(pid, 0) would terminate the process, so ask the kernel instead."""
    if not pid:
        return False
    if sys.platform.startswith("win"):
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            k32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _table_counts(db: str) -> dict:
    counts = {}
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        return counts
    try:
        for t in TABLES:
            try:
                counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.Error:
                counts[t] = 0
    finally:
        conn.close()
    return counts


def _log_tail(n: int = 5) -> list:
    try:
        with open(_log_path(), encoding="utf-8", errors="replace") as f:
            return [ln.rstrip() for ln in f.readlines()[-n:]]
    except OSError:
        return []


def index_state() -> dict:
    """Where the index is, what it holds, and the state of any build."""
    db = paths.db_path()
    built = os.path.exists(db)
    counts = _table_counts(db) if built else {}
    status = _read_status()
    if status.get("state") == "running" and not _alive(status.get("pid")):
        status["state"] = "interrupted"
        status["note"] = ("The build process is no longer running and did not finish. "
                          "Start it again with action='build'.")
    ready = built and counts.get("names", 0) > 0
    out = {
        "data_dir": paths.data_dir(),
        "db_path": db,
        "built": ready,
        "tables": counts,
        "build": status or {"state": "never_run"},
        "source": SOURCE,
    }
    if status.get("state") in ("running", "failed", "interrupted", "pending_restart"):
        out["log_tail"] = _log_tail()
    if ready and not counts.get("wiktionary"):
        out["hint"] = ("gloss_archaic needs the separate Wiktionary table, which this build "
                       "does not fetch; every other names tool is ready.")
    elif not ready and status.get("state") in (None, "never_run", "failed", "interrupted"):
        out["hint"] = ("The index is not built. With the user's agreement, call "
                       "names_index(action='build'). It downloads the dictionary data and "
                       "builds in the background, usually within a few minutes.")
    return out


def start_build() -> dict:
    """Start one background build, unless one is already running."""
    status = _read_status()
    if status.get("state") == "running" and _alive(status.get("pid")):
        return {"started": False, "reason": "A build is already running.", **index_state()}
    data = paths.data_dir(create=True)
    log = open(_log_path(), "a", encoding="utf-8")
    log.write(f"\n=== build requested {_now()} ===\n")
    log.flush()
    kwargs = {"stdout": log, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL,
              "cwd": data, "env": dict(os.environ, JMNEDICT_DATA_DIR=data,
                                       PYTHONIOENCODING="utf-8")}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen([sys.executable, "-m", "bibliograph.sources.names.firstrun", "--run"],
                            **kwargs)
    log.close()
    _write_status(state="running", pid=proc.pid, started=_now(), finished=None, error=None)
    return {"started": True, **index_state()}


def _run() -> int:
    """The build itself, in the background process."""
    from . import build_index as B

    final = paths.db_path()
    tmp = final + ".building"
    _write_status(state="running", pid=os.getpid(), step="starting")
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
        _write_status(step="JMnedict (names)")
        B.build(B._download_latest(), tmp)
        for step, prefix, fn in (("JMdict", "jmdict-eng", B.build_jmdict),
                                 ("KANJIDIC2", "kanjidic2-en", B.build_kanjidic),
                                 ("KRADFILE", "kradfile", B.build_krad),
                                 ("RADKFILE", "radkfile", B.build_radk)):
            _write_status(step=step)
            fn(B._download_asset(prefix), tmp)
        try:
            os.replace(tmp, final)
        except PermissionError:
            _write_status(state="pending_restart", finished=_now(), step="done",
                          note=("The new index is built at names.sqlite.building but the old "
                                "one is in use. Restart Claude Desktop, then run the build "
                                "again to switch over."))
            return 0
        # The extracted downloads (about 290 MB) are only needed to rebuild; the
        # index itself is about 185 MB. Drop them so a user's disk holds the index
        # alone; a rebuild downloads again (about 25 MB compressed).
        import shutil
        shutil.rmtree(paths.raw_dir(), ignore_errors=True)
        _write_status(state="done", finished=_now(), step="done")
        print(f"Index ready at {final}")
        return 0
    except Exception as e:  # noqa: BLE001 - reported to the user through the status file
        traceback.print_exc()
        _write_status(state="failed", finished=_now(), error=f"{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    if "--run" in sys.argv:
        sys.exit(_run())
    print(json.dumps(index_state(), ensure_ascii=False, indent=2))
