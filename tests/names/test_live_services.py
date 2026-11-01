"""Live integration smoke for Web NDL Authorities. Network-gated.

This hits the NDL SPARQL endpoint for real, so it is skipped unless
RUN_LIVE_TESTS=1 — keeping the default suite hermetic and offline.

    RUN_LIVE_TESTS=1 python -m pytest tests/names/test_live_services.py -q
"""

import os

import pytest

from bibliograph.sources.names import authorities

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1",
    reason="live network test; set RUN_LIVE_TESTS=1 to run",
)

# Surname Saitō, two interchangeable writings, plus the kana reading.
_VARIANTS = {"kanji": ["斎藤", "斉藤"], "kana": ["さいとう"], "hepburn_plain": ["saito"]}


def test_ndl_returns_personal_records_with_ids():
    cands = authorities.search_ndl_authorities(_VARIANTS, max_results=10)
    assert cands, "expected at least one NDL personal-name record"
    assert all(c.get("error") is None for c in cands)
    assert any(c["ids"].get("ndla") for c in cands)
