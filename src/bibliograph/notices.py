"""Usage notifications a source's provider asks its users to file, and whether one is recorded.

Some providers ask continuous users to tell them who they are and how they use the
service. The NDL does so for the NDL Search API (section 17 of its API help). That
obligation falls on each user, not on this package, so bibliograph cannot file it for anyone.
What it can do is refuse to hide whether a filing is on record: a source whose notice is
missing says so in every response. (NDL Lab's full-text API asks for no application for
non-commercial use, so ndl_dl has no notice here; see its module docstring.)

A filing is recorded by a marker file, written by the user after filing, holding the
date and what was declared. Markers live in the bibliograph notices folder:

    BIBLIOGRAPH_NOTICES_DIR, if set; otherwise
    %APPDATA%\\bibliograph\\notices  (Windows)  or  ~/.config/bibliograph/notices  (elsewhere)

A per-source environment variable naming the marker file directly overrides the folder.
The check runs only for the source concerned, so a missing NDL marker never affects
cinii, openalex or anything else.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

NOTICES = {
    # source key: (marker file name, overriding environment variable)
    "ndl": ("NDL-API-NOTIFICATION.txt", "BIBLIOGRAPH_NDL_NOTIFICATION_FILE"),
}


def notices_dir() -> Path:
    env = os.environ.get("BIBLIOGRAPH_NOTICES_DIR")
    if env:
        return Path(env)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "bibliograph" / "notices"
    return Path.home() / ".config" / "bibliograph" / "notices"


def marker_path(source: str) -> Optional[Path]:
    """Where this source's marker is looked for first (the override, else the folder)."""
    if source not in NOTICES:
        return None
    name, env = NOTICES[source]
    override = os.environ.get(env)
    return Path(override) if override else notices_dir() / name


def recorded(source: str, extra_candidates: tuple[Path, ...] = ()) -> bool:
    """True when a non-empty marker for this source exists."""
    first = marker_path(source)
    for p in ((first,) if first else ()) + tuple(extra_candidates):
        try:
            if p and p.is_file() and p.stat().st_size > 0:
                return True
        except OSError:
            continue
    return False
