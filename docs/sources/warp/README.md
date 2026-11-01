# warp-mcp

An MCP server for the **NDL Web Archiving Project (WARP, 国立国会図書館インターネット資料収集保存事業)**, the National Diet Library's web archive, through WARP's Memento (RFC 7089) interface.

Since the 2010 amendment of the National Diet Library Law, WARP collects the websites of Japanese national and local government, public corporations and national universities by statute. For those pages it is usually the archive that actually holds a capture, where the Internet Archive holds nothing or a thin sample.

## Tools

| Tool | What it does | Requests to WARP |
|---|---|---|
| `warp_list_captures` | Captures held for one exact URL: total, first, last, count per year, and up to 100 captures within an optional date range | 1 |
| `warp_nearest_capture` | The capture nearest a date, with the captures just before and after | 1 |
| `warp_read_capture` | Opens one capture and returns its text, paginated, optionally with the page's links rewritten to their original URLs | 2, plus 1 per archived redirect (max 3) |

## Undertakings

WARP's help page states that its Memento API needs no application (「APIの利用に、必要な手続き等はありません」). Its Q&A states that WARP is meant to be browsed, has no bulk-download or data API, and will block heavy mechanical access. The server is therefore built to behave like one reader in a browser:

- serial requests only, across all tools, at least 3 seconds apart;
- one TimeMap per list or nearest-capture call, no pagination through TimeMaps;
- no crawling and no link following beyond archived redirects on the page asked for (at most three);
- nothing cached or stored except the receipt line (below).

A read timeout, 429 or 503 is reported as `warp_unavailable` with advice to wait: the NDL throttles without always sending 429.

## Terms of use and access

WARP's own FAQ (https://warp.ndl.go.jp/info/qanda, English: https://warp.ndl.go.jp/en/info/qanda)
says it offers no API and no bulk download, because browser viewing is the
expected way to use it, and asks users to refrain from large-scale automated
access, which the NDL may block. Its site policy
(https://warp.ndl.go.jp/info/sitepolicy, English: https://warp.ndl.go.jp/en/info/sitepolicy)
says archived content stays under its original publisher's copyright — reuse
needs that rights holder's permission, not WARP's or this server's — and that
linking to a WARP page is welcome provided the link says WARP is the
destination.

This server is built to those terms: one URL at a time, requests serialised
and spaced at least `MIN_REQUEST_INTERVAL` (3.0 s) apart, no tool that takes
more than one URL, nothing listed across many URLs, and nothing harvested or
stored beyond the optional receipt line. Finding by subject is a separate,
explicitly licensed route — WARP catalogue records come from the NDL Search
API (ndl-mcp's `ndl_search_warp`, dpid `warp`), covered by the user's NDL
filing, not from WARP itself.

The intended path through the tools: `ndl_search_warp` to find an archived
site by subject → `warp_list_captures` or `warp_nearest_capture` with its URL
to find a capture → `warp_read_capture` to read it. The `viewer_url` each tool
returns is the citable form of a capture; the page's content remains the
original publisher's.

## Response format

Since 0.2.0, all three tools answer in the family's typed JSON envelope
(`mediation.py`, shared with cinii-mcp, jstage-mcp, ndl-mcp and the rest of
the family): the query as given, `matching_mode` `"exact_url"` (WARP is
looked up by exact URL, never searched), typed `diagnostics[]`, a loggable
receipt, and attribution — deposited to the receipts ledger through
`mediation.emit()` (a single deposit per call; there is no separate ledger
write any more).

- **Each capture is one item** (`record_type: "web_capture"`), with the URL
  in `ids.url_ja` by default (`ids.url_en` only when `warp_read_capture` has
  read a page title and it is not Japanese-scripted), `source.year` from the
  capture's timestamp, and capture-specific facts — `timestamp`,
  `datetime_utc`, `viewer_url`, `status`, `captures_by_year`,
  `first_capture`/`last_capture`, `text`, `offset`, `links`, `redirects`,
  and the rest — in `extra`. `warp_nearest_capture` and `warp_read_capture`
  each return exactly one item; `warp_list_captures` returns one per capture
  shown.
- **`result.total`** is WARP's own count of captures for the URL (the whole
  TimeMap, not just what was returned).
- **An empty TimeMap, or a 404 for the exact URL/timestamp asked, is not
  proof of absence.** The envelope's optional `suggestions[]` carries the
  spellings to try instead (scheme, `www.`, trailing slash, `index.html`).
- **The capture timestamp can differ from the one requested.**
  `/web/<ts>/<url>` is a viewer page whose iframe points at the actual
  capture; `extra.capture_timestamp` and `extra.viewer_url` report the
  iframe's actual timestamp, and `CAPTURE_TIMESTAMP_DIFFERS_FROM_REQUEST`
  flags it.
- **`extra.status: "ndl_premises_only"`**: WARP holds the capture but serves
  it only inside NDL buildings (HTTP 403, "Available only within the
  facilities of the National Diet Library, Japan."). A finding about
  access, not an absence.
- WARP's full-text search has no API and is not available here.

### Diagnostic codes

| Code | Level | Meaning |
|---|---|---|
| `INVALID_INPUT` | error | A malformed argument (URL, date or timestamp). |
| `WARP_UNAVAILABLE` | error | Timeout, 429 or 503 — treat as throttling, wait, do not retry in a loop. |
| `EMPTY_TIMEMAP` | info | WARP's TimeMap for this exact URL held nothing. See `suggestions`. |
| `MEMENTO_DATE_UNPARSEABLE` | warning | TimeMap lines whose date could not be read were left out; the message gives the number, and the capture count excludes them. |
| `TRUNCATED_BY_LIMIT` | info | More captures were in range than `limit` returned. |
| `NO_CAPTURES_IN_RANGE` | info | Captures exist for the URL, none in `from_date`/`to_date`. |
| `NDL_PREMISES_ONLY` | info | The capture is viewable only inside NDL buildings. |
| `CAPTURE_TIMESTAMP_DIFFERS_FROM_REQUEST` | info | The iframe resolved to a different capture than the timestamp asked for. |
| `REDIRECT_HOP_LIMIT` | warning | Stopped after `MAX_REDIRECT_HOPS` archived redirects. |
| `REDIRECT_TARGET_UNPARSEABLE` | warning | An archived redirect's `Location` could not be parsed. |
| `REDIRECT_TARGET_NOT_ARCHIVED` | warning | A redirect's target has no archived capture of its own. |
| `NON_HTML` | info | The capture is not HTML/XML/text (e.g. a PDF); this server does not download it. |
| `NO_CAPTURE_FRAME` | error | WARP's viewer page carried no capture iframe (layout change). |
| `ENCODING_UNCERTAIN` | warning | The page was decoded with replacement characters. |
| `VIEWER_<http_status>` | error | WARP's viewer page answered with that HTTP status for the URL/timestamp asked (e.g. `VIEWER_404`, `VIEWER_500`). |
| `CAPTURE_<http_status>` | warning | The capture itself carries that archived HTTP error status (e.g. `CAPTURE_500`). |

`mediation`'s own `OK`, `RECEIPT_NOT_DEPOSITED` and `RECEIPT_WRITE_FAILED`
diagnostics can also appear; see the family's `response-schema.json`.

## Install (Claude Desktop, shared venv)

```
<venv>\Scripts\python.exe -m pip install <path-to>\warp_mcp-0.1.0-py3-none-any.whl
```

```json
"warp": {
  "command": "<venv>\\Scripts\\warp-mcp.exe",
  "env": {
    "MCP_RECEIPT_DIR": "<receipts folder>",
    "MCP_RECEIPT_SESSION": "<project slug>"
  }
}
```

Python 3.10 to 3.13. Dependencies: `mcp`, `httpx`.

## Receipts

`ledger.py` is vendored byte-identical from the family (sha256 `0b12aca3…b038`). With `MCP_RECEIPT_DIR` set, every tool call appends one hash-chained line to `<dir>/warp.jsonl`. Verify with `warp-mcp-ledger verify <file>`.

## Attribution

Every response carries: 国立国会図書館インターネット資料収集保存事業（WARP）, National Diet Library. Archived pages remain the work of their original publishers; WARP's terms govern reuse.

## Licence

MIT. Author: Christopher Gerteis (ORCID 0000-0003-4977-6152).
