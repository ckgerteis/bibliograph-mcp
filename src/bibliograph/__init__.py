"""Bibliograph (書誌): a single Model Context Protocol server gathering Japan-studies
bibliographic and archival search over the National Diet Library (catalogue,
national bibliography, magazine index, Digital Collections and its OCR full
text, and the WARP web archive), CiNii Research (articles, books,
dissertations, KAKEN and researchers), J-STAGE, the JDCat humanities and
social-science data catalogue, OpenAlex, Semantic Scholar,
and Japanese name and authority resolution (JMnedict/JMdict/KANJIDIC2 plus Web
NDL Authorities), with open-access PDFs fetched into a named folder under the
same receipts, each source keeping its own rate limits, credit lines and
typed diagnostics inside one shared response envelope and receipt ledger."""

__version__ = "2.0.0"
