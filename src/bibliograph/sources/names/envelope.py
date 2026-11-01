"""The family response envelope for jmnedict's tools.

jmnedict answers from dictionaries, not catalogues, so its records do not fit
make_item's bibliographic fields. They go into the envelope unchanged instead:

* a dictionary tool returns ONE item whose ``extra`` is the tool's whole answer
  (the name-forms bundle, the readings, the gloss, the kanji facts), with
  ``record_type`` naming what kind of answer it is;
* name_authority returns one item per Web NDL Authorities record
  (``record_type`` "authority", the heading in ``authors``, the record in
  ``extra``) and keeps ``plan`` as a top-level key (``plan.query_forms``), so
  the searched name forms stay visible.

Everything the old bare dict carried is still there, one level down. What the
envelope adds is the rest of the family's paperwork: the query as given, typed
diagnostics, a receipt hash, the attribution line, and deposit to the receipts
ledger through mediation.emit().

Diagnostic codes used here (beside mediation's RECEIPT_* codes):
  OK             the dictionary (or authority lookup) answered.
  NOTE           a caveat the tool attaches to its answer (a lead, not a fact).
  ZERO_RESULTS   no entry for the term. For gloss_term a soft signal only; for
                 name_authority, no heading was found under the forms searched.
  INDEX_MISSING  the local dictionary index is not built.
  SERVICE_ERROR  Web NDL Authorities did not answer a name_authority lookup.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from ... import mediation as M
from . import authorities

SERVER = "jmnedict"

EDRDG = ("JMnedict, JMdict, KANJIDIC2 and RADKFILE/KRADFILE: Electronic Dictionary "
         "Research and Development Group (EDRDG), used under the Group's licence "
         "(CC BY-SA 4.0), https://www.edrdg.org/edrdg/licence.html.")
WIKTIONARY = ("Wiktionary, via kaikki.org (wiktextract), CC BY-SA 4.0 and GFDL; "
              "https://kaikki.org/.")
NDLA = ("Web NDL Authorities, National Diet Library (https://id.ndl.go.jp/auth/ndla/), "
        "metadata under the NDL's terms (PDL1.0, CC BY 4.0 compatible).")

KIND = {
    "name_query_variants": "name_forms",
    "resolve_name_readings": "name_readings",
    "resolve_name_kanji": "name_writings",
    "infer_name_order": "name_order",
    "gloss_term": "gloss",
    "gloss_archaic": "gloss_archaic",
    "kanji_by_radical": "kanji_candidates",
    "kanji_info": "kanji",
    "names_index": "index_status",
}


def _attribution(operation: str) -> str:
    if operation == "gloss_archaic":
        return WIKTIONARY
    if operation == "name_authority":
        return NDLA + " Name forms: " + EDRDG
    return EDRDG


def _notes(result: dict) -> list[dict]:
    out = []
    notes = result.get("notes") or []
    if isinstance(notes, str):
        notes = [notes]
    for n in notes:
        out.append(M.diag("info", "NOTE", str(n)))
    return out


def respond(operation: str, params: dict, compute: Callable[[], dict]) -> str:
    """Run one tool, wrap its answer in the family envelope, deposit, serialise."""
    # The term the caller chose is the first argument (the name, term, kanji or
    # components); the rest are qualifiers and stay in params.
    first = next(iter(params.values()), "")
    input_terms = first if isinstance(first, str) else ""
    diagnostics: list[dict] = []
    items: list[dict] = []
    extra_keys: dict[str, Any] = {}
    try:
        result = compute()
    except FileNotFoundError as e:
        result = {"error": str(e)}
    except Exception as e:  # noqa: BLE001
        # Until 1 Nov 2026 anything but a missing index escaped to the client
        # as a bare "Error executing tool", which is how the 31 Oct thread
        # fault went undiagnosable from Claude's side.
        result = {"internal_error": f"{type(e).__name__}: {e}"}

    if "internal_error" in result:
        diagnostics.append(M.diag(
            "error", "SERVER_ERROR",
            f"The {operation} tool failed inside bibliograph: {str(result['internal_error'])[:300]}",
            "This is a fault in bibliograph, not an absence of data, and the index may be "
            "fine. Report the message with the version bibliograph_status gives."))
    elif "error" in result:
        diagnostics.append(M.diag(
            "error", "INDEX_MISSING", str(result["error"]),
            "Build the index: with the user's agreement call names_index(action='build'), "
            "or run bibliograph-build-names --all from a shell."))
    elif operation == "name_authority":
        variants = result.get("variants") or {}
        records = result.get("records") or []
        needles, kana = authorities._ndl_forms(variants)
        extra_keys["plan"] = {"query_forms": needles + kana}
        for rec in records:
            if "error" in rec:
                diagnostics.append(M.diag(
                    "warning", "SERVICE_ERROR", str(rec["error"]),
                    "Web NDL Authorities did not answer; rerun later."))
                continue
            items.append(M.make_item(
                authors=[{"ja": rec.get("kanji_name"), "en": None}],
                matched_in="authority", record_type="authority", extra=rec))
        if not items and not any(d["code"] == "SERVICE_ERROR" for d in diagnostics):
            diagnostics.append(M.diag(
                "info", "ZERO_RESULTS",
                "No heading found under the forms searched."))
    elif result.get("found") is False:
        diagnostics.append(M.diag("info", "ZERO_RESULTS",
                                  "No dictionary entry for this term.", result.get("hint")))
    else:
        items.append(M.make_item(matched_in="dictionary",
                                 record_type=KIND.get(operation, operation), extra=result))
        diagnostics += _notes(result)
        if result.get("hint"):
            diagnostics.append(M.diag("info", "NOTE", str(result["hint"])))

    if not any(d["level"] == "error" for d in diagnostics) and items:
        diagnostics.insert(0, M.diag("info", "OK", f"{len(items)} record(s) returned."))

    env = M.build_envelope(
        server=SERVER, operation=operation, input_terms=input_terms,
        normalized=input_terms.strip(), params=params,
        matching_mode={"name_authority": "authority_lookup",
                       "names_index": "not_a_search"}.get(operation, "dictionary_lookup"),
        total=len(items), start=1, items=items, diagnostics=diagnostics,
        attribution=_attribution(operation))
    env.update(extra_keys)
    return M.emit(env)
