"""Complete a receipt's `result_ids` for sources the shared contract cannot name.

`mediation.make_receipt` reads five identifier slots (doi, kci_id, crid, naid,
oai_id), in that order, and those slots belong to particular authorities: crid
is a CiNii Research ID, naid a CiNii NAID. Sources whose records carry none of
them - NDL Search without a DOI, NDL Next Digital Library, WARP captures, and
OpenAlex and Semantic Scholar works without a DOI - produced receipts with an
empty `result_ids`, so the ledger recorded that a search ran but not what it
returned.

This module is bibliograph's own and is deliberately not part of mediation.py,
which must stay byte-identical with korea-scholarship-mcp's copy. Each source
passes a function that names its records in a self-describing form
(`NDLBibID:...`, `info:ndljp/pid/...`, a WARP capture URL, `openalex:W...`,
`s2:...`). The contract slots still win where they are filled, in the same
order make_receipt uses, so a record with a DOI is receipted by its DOI as
before.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from . import conform as _conform

_CONTRACT_SLOTS = ("doi", "kci_id", "crid", "naid", "oai_id")


def complete(env: dict, local_id: Callable[[dict], Optional[str]]) -> dict:
    """Rewrite env["receipt"]["result_ids"] in place and return env.

    One entry per item that can be named, in item order. A `local_id` that
    raises or returns a non-string is treated as naming nothing, so a malformed
    item can never cost the caller its response.
    """
    if not isinstance(env, dict):
        return env
    receipt = env.get("receipt")
    if not isinstance(receipt, dict):
        return env
    ids: list[str] = []
    items = env.get("items")
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        slots: Any = it.get("ids") or {}
        ident = None
        if isinstance(slots, dict):
            ident = next((slots[k] for k in _CONTRACT_SLOTS
                          if isinstance(slots.get(k), str) and slots[k].strip()), None)
        if not ident:
            try:
                ident = local_id(it)
            except Exception:  # noqa: BLE001 - a receipt must never break a response
                ident = None
        if isinstance(ident, str) and ident.strip():
            ids.append(ident.strip())
    receipt["result_ids"] = ids
    return env


def build_items(records, build, *args) -> tuple[list[dict], int]:
    """Build items from records, counting the ones that will not build.

    A record of an unexpected shape is left out and counted, so the caller can
    say so in a diagnostic rather than fail the whole response (fuzz, 7 Oct 2026).
    Lives here because both callers already import this module.
    """
    items: list[dict] = []
    malformed = 0
    if records is not None and not isinstance(records, list):
        return items, 1  # a results field of the wrong shape: report it, do not read it as empty
    for r in records or []:
        if not isinstance(r, dict):
            malformed += 1
            continue
        try:
            items.append(build(r, *args))
        except Exception:  # noqa: BLE001
            malformed += 1
    return items, malformed


def extra_of(it: dict) -> dict:
    ex = it.get("extra")
    return ex if isinstance(ex, dict) else {}


def prefixed(prefix: str, value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return f"{prefix}{s}" if s else None

def finish(env: dict, local_id: Optional[Callable[[dict], Optional[str]]] = None) -> dict:
    """Conform the envelope to the family schema, then complete its receipt."""
    return complete(_conform.envelope(env), local_id or (lambda it: None))
