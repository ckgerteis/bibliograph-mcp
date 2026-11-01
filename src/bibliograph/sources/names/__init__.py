"""jmnedict-mcp - local MCP for Japanese name forms and authority lookups.

Names core (name_query_variants, resolve_name_readings, resolve_name_kanji,
infer_name_order) and name_authority (the live Web NDL Authorities lookup in
authorities.py) are both implemented and tested, alongside the
JMdict/KANJIDIC2/Wiktionary reference tools. The pure name-matching helpers
that once lived here (and backed the now-removed find_scholar) moved to
bibliograph.namematch, for reuse by the other sources. See BUILD_NOTES.md for the
repair history and the behaviour each tool promises.
"""

__version__ = "0.2.1"
