"""Error classification: J-STAGE answering with an error status is API_ERROR;
failing to reach J-STAGE is TRANSPORT_ERROR. Run with pytest, or directly."""
from __future__ import annotations

import sys

import httpx

from bibliograph.sources.jstage.server import _annotate_name_match, _error_diag


def _status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://api.jstage.jst.go.jp/searchapi/do")
    return httpx.HTTPStatusError("x", request=req, response=httpx.Response(code, request=req))


def test_http_status_is_api_error():
    for code in (400, 404, 500, 503):
        d = _error_diag(_status_error(code))
        assert d["code"] == "API_ERROR", (code, d)
        assert str(code) in d["message"]


def test_transport_failures_are_transport_error():
    req = httpx.Request("GET", "https://api.jstage.jst.go.jp/searchapi/do")
    for exc in (httpx.ConnectTimeout("t", request=req), httpx.ConnectError("c", request=req),
                httpx.ReadTimeout("r", request=req)):
        assert _error_diag(exc)["code"] == "TRANSPORT_ERROR", exc


def test_malformed_answer_is_api_error():
    assert _error_diag(KeyError("result"))["code"] == "API_ERROR"


def _item(ja=None, en=None):
    return {"authors": [{"ja": ja, "en": en}], "extra": {}}


def test_annotate_name_match_sets_extra_and_grades():
    items = [_item(ja="田中明彦"), _item(en="Suzuki Ichiro")]
    diag = _annotate_name_match(items, "田中明")
    assert items[0]["extra"]["name_match"] == "partial"
    assert items[1]["extra"]["name_match"] == "none"
    assert diag["code"] == "LOOSE_NAME_MATCH" and diag["level"] == "info"
    assert "1 partial" in diag["message"] and "1 none" in diag["message"]


def test_annotate_name_match_returns_none_when_all_exact():
    items = [_item(ja="田中明")]
    assert _annotate_name_match(items, "田中明") is None
    assert items[0]["extra"]["name_match"] == "exact"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
    sys.exit(0)
