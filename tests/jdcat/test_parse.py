"""jdcat: parsing and envelopes against responses captured 7 October 2026. No network."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from bibliograph.sources.jdcat import server as S

FIX = Path(__file__).parent / "fixtures"
SCHEMA = json.loads((Path(__file__).parents[1] / "response-schema.json").read_text(encoding="utf-8"))


def _json(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _xml(name):
    return (FIX / name).read_text(encoding="utf-8")


def _validate(env):
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(env, SCHEMA)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _no_spacing(monkeypatch):
    monkeypatch.setattr(S, "MIN_REQUEST_INTERVAL", 0.0)


# ------------------------------------------------------------------ search hits

def test_newspaper_clipping_hit():
    hits = _json("search_kinro_seishonen.json")["hits"]["hits"]
    it = S.item_from_hit(next(h for h in hits if h["id"] == 228802))
    assert it["title"]["ja"] == "教育重役の設置要望 : 勤労青少年指導の協力会議"
    assert it["title"]["en"].startswith("Request for establishment")
    assert it["authors"] == [{"ja": "大阪朝日新聞", "en": None}]
    assert it["ids"]["doi"] == "10.24546/0100360436"
    assert it["ids"]["oai_id"] == "oai:jdcat.jsps.go.jp:00228802"
    assert it["ids"]["url_ja"] == "https://jdcat.jsps.go.jp/records/228802"
    assert it["source"]["holding_org"] == "神戸大学附属図書館"
    assert it["source"]["year"] is None  # a coverage date is not a publication year
    assert it["extra"]["temporal"] == ["1942-12-13"]
    assert it["record_type"] == "publication"
    assert "https://lib.kobe-u.ac.jp/da/secondaryuse/" in it["extra"]["rights"]


def test_survey_study_hit_takes_the_doi_from_the_study_id_not_the_citation_prose():
    hits = _json("search_kinro_seishonen.json")["hits"]["hits"]
    it = S.item_from_hit(next(h for h in hits if h["id"] == 211390))
    assert it["ids"]["doi"] == "10.34500/SSJDA.c045"
    assert it["extra"]["dois"] == ["10.34500/SSJDA.c045"]
    assert it["authors"] == [{"ja": "ベネッセコーポレーション", "en": None}]
    assert it["record_type"] == "quantitative_survey"
    assert it["extra"]["temporal"][0] == "1995"


def test_yearbook_table_keeps_every_corporate_creator_in_order():
    hits = _json("search_hanzai_kenkyo_ier.json")["hits"]["hits"]
    it = S.item_from_hit(hits[0])
    ja = [a["ja"] for a in it["authors"]]
    assert ja[:4] == ["内務省", "朝鮮総督府", "台湾総督府", "樺太庁"]
    assert all(a["en"] for a in it["authors"])
    assert it["ids"]["doi"] and it["ids"]["doi"].startswith("10.50914/")
    assert it["record_type"] == "official_statistics"
    assert "朝鮮" in it["extra"]["geographic_coverage"]


def test_facets_are_reported_per_label_and_never_summed():
    f = S.facets_from(_json("search_kinro_seishonen.json"))
    labels = {b["label"] for b in f["Distributor"]["buckets"]}
    assert {"神戸大学附属図書館", "Kobe University Library"} <= labels
    assert "path" not in f


# ------------------------------------------------------------------ envelopes

def test_search_envelope_validates_and_carries_facets():
    p = S.SearchInput(query="勤労青少年", size=3)
    env = S.search_envelope(p, _json("search_kinro_seishonen.json"), [])
    _validate(env)
    assert env["result"]["total"] == 3 and env["result"]["returned"] == 3
    assert env["searched_for"]["term"] == "勤労青少年"
    assert env["facets"]["Distributor"]["buckets"]
    codes = {d["code"] for d in env["diagnostics"]}
    assert "FACET_COUNTS_PER_LABEL" in codes
    assert "robots.txt" in env["coverage_note"]


def test_zero_result_is_a_typed_nil_search():
    p = S.SearchInput(query="zzqqxxnotaword")
    env = S.search_envelope(p, _json("search_zero.json"), [])
    _validate(env)
    assert env["items"] == [] and env["result"]["breadth"] == "none"
    assert "ZERO_RESULTS" in {d["code"] for d in env["diagnostics"]}


def test_unknown_filter_label_is_flagged():
    p = S.SearchInput(query="勤労青少年", distributor=["Kobe Univ"])
    env = S.search_envelope(p, _json("search_kinro_seishonen.json"), [])
    assert "FILTER_LABEL_NOT_IN_FACETS" in {d["code"] for d in env["diagnostics"]}


def test_filters_and_date_window_are_sent_as_the_service_names_them():
    p = S.SearchInput(query="朝鮮", distributor=["神戸大学附属図書館", "SSJDA"],
                      data_type=["出版物: テキスト"], date_from="1930", date_to="1935", page=2)
    pairs = S.search_params(p)
    assert ("Distributor", "神戸大学附属図書館") in pairs and ("Distributor", "SSJDA") in pairs
    assert ("Data Type", "出版物: テキスト") in pairs
    assert ("date_range1_from", "1930") in pairs and ("date_range1_to", "1935-12-31") in pairs
    assert ("page", "2") in pairs


def test_half_open_date_window_is_refused_before_any_request():
    with pytest.raises(ValidationError):
        S.SearchInput(query="朝鮮", date_from="1930")


def test_size_is_capped():
    with pytest.raises(ValidationError):
        S.SearchInput(query="朝鮮", size=S.MAX_RECORDS + 1)


# ------------------------------------------------------------------ get_record

@pytest.mark.parametrize("raw,expected", [
    ("7058", 7058),
    ("oai:jdcat.jsps.go.jp:00007058", 7058),
    ("https://jdcat.jsps.go.jp/records/7058", 7058),
    ("doi:10.1/x", None),
])
def test_record_identifiers(raw, expected):
    assert S.parse_record_id(raw) == expected


def test_oai_record_yearbook_table():
    item, err, header = S.item_from_oai(_xml("oai_getrecord_00007058.xml"))
    assert err is None
    assert item["ids"]["doi"] == "10.50914/0002001104"
    assert [a["ja"] for a in item["authors"]][:2] == ["内務省", "朝鮮総督府"]
    assert item["extra"]["temporal"] == ["1932", "1936", "1936"]
    assert item["extra"]["jdcat_id"] == "7058"
    assert header["datestamp"]


def test_oai_record_clipping_doi_from_doi_typed_relation():
    item, err, _ = S.item_from_oai(_xml("oai_getrecord_00228802.xml"))
    assert err is None and item["ids"]["doi"] == "10.24546/0100360436"
    assert item["source"]["holding_org"] == "神戸大学附属図書館"


def test_oai_missing_record_is_not_found():
    env = S.record_envelope("99999999", "oai:jdcat.jsps.go.jp:99999999",
                            _xml("oai_getrecord_missing.xml"), [])
    _validate(env)
    assert env["items"] == [] and "NOT_FOUND" in {d["code"] for d in env["diagnostics"]}


def test_get_record_tool_end_to_end(monkeypatch):
    async def fake_get(url, params=None):
        assert params["identifier"] == "oai:jdcat.jsps.go.jp:00211390"
        return httpx.Response(200, text=_xml("oai_getrecord_00211390.xml")), []
    monkeypatch.setattr(S, "_get", fake_get)
    env = json.loads(_run(S.jdcat_get_record(S.GetRecordInput(record="211390"))))
    _validate(env)
    assert env["items"][0]["ids"]["doi"] == "10.34500/SSJDA.c045"
    assert env["endpoint"] == S.OAI_URL


def test_search_tool_end_to_end(monkeypatch):
    async def fake_get(url, params=None):
        return httpx.Response(200, json=_json("search_hanzai_kenkyo_ier.json")), []
    monkeypatch.setattr(S, "_get", fake_get)
    env = json.loads(_run(S.jdcat_search(S.SearchInput(
        query="犯罪検挙件数", distributor=["一橋大学経済研究所"], size=2))))
    _validate(env)
    assert env["result"]["returned"] == 2 and env["result"]["total"] == 12


def test_transport_failure_is_not_a_zero(monkeypatch):
    async def fake_get(url, params=None):
        return None, [S.M.diag("error", "READ_TIMEOUT", "timeout", None)]
    monkeypatch.setattr(S, "_get", fake_get)
    env = json.loads(_run(S.jdcat_search(S.SearchInput(query="朝鮮"))))
    codes = {d["code"] for d in env["diagnostics"]}
    assert "READ_TIMEOUT" in codes and "ZERO_RESULTS" not in codes


def test_bad_identifier_makes_no_request(monkeypatch):
    async def fake_get(url, params=None):
        raise AssertionError("no request should be made")
    monkeypatch.setattr(S, "_get", fake_get)
    env = json.loads(_run(S.jdcat_get_record(S.GetRecordInput(record="not-an-id"))))
    assert env["diagnostics"][0]["code"] == "BAD_IDENTIFIER"


@pytest.mark.parametrize("given,sent", [("1919", "1919-12-31"), ("1920-02", "1920-02-29"),
                                        ("1919-06-15", "1919-06-15")])
def test_upper_bound_is_closed_out(given, sent):
    assert S.window_end(given) == sent


# ------------------------------------------------------------------ malformed input (review, 7 Oct 2026)

def test_total_in_elasticsearch7_shape_is_unwrapped():
    payload = _json("search_kinro_seishonen.json")
    payload["hits"]["total"] = {"value": 3, "relation": "eq"}
    env = S.search_envelope(S.SearchInput(query="勤労青少年"), payload, [])
    assert env["result"]["total"] == 3
    assert "ZERO_RESULTS" not in {d["code"] for d in env["diagnostics"]}


@pytest.mark.parametrize("payload", [[], {"hits": 5}, {"hits": {"hits": 7}}])
def test_wrong_shaped_payload_is_an_api_error_not_a_crash(payload):
    env = S.search_envelope(S.SearchInput(query="x"), payload, [])
    _validate(env)
    codes = {d["code"] for d in env["diagnostics"]}
    assert "API_ERROR" in codes and "ZERO_RESULTS" not in codes


def test_strings_where_lists_belong_are_not_split_into_characters():
    hit = {"id": 1, "metadata": {"title": "Hello", "contributor": {"contributorName": "神戸大学"},
                                 "creator": {"creatorName": "山田"}, "_oai": "x",
                                 "geoLocation": ["日本"], "subject": "x"}}
    it = S.item_from_hit(hit)
    assert it["title"]["en"] == "Hello"
    assert it["source"]["holding_org"] == "神戸大学"
    assert it["authors"] == [{"ja": "山田", "en": None}]


def test_flattened_creator_fallback_pairs_adjacent_ja_en_names():
    hit = {"id": 1, "metadata": {"creator": {"creatorName": [
        "内務省", "Japan. Ministry of Home Affairs", "朝鮮総督府",
        "Office of the Governor-General of Korea", "SSJDA"]}}}
    assert S.item_from_hit(hit)["authors"] == [
        {"ja": "内務省", "en": "Japan. Ministry of Home Affairs"},
        {"ja": "朝鮮総督府", "en": "Office of the Governor-General of Korea"},
        {"ja": None, "en": "SSJDA"},
    ]


def test_korean_title_goes_to_the_ko_slot():
    hit = {"id": 1, "metadata": {"title": ["조선총독부 통계"]}}
    assert S.item_from_hit(hit)["title"]["ko"] == "조선총독부 통계"


def test_doi_of_a_related_work_is_not_the_records_own():
    hit = {"id": 1, "metadata": {"relation": {
        "@attributes": {"relationType": [["isPartOf"]]},
        "relatedIdentifier": [{"identifierType": "DOI", "value": "https://doi.org/10.9999/other)"}]}}}
    it = S.item_from_hit(hit)
    assert it["ids"]["doi"] is None
    assert it["extra"]["dois"] == ["10.9999/other"] and it["extra"]["own_doi_found"] is False


@pytest.mark.parametrize("a,b", [("2020", "2020-13"), ("2020-00", "2020"), ("2020-02-31", "2020"),
                                 ("1936", "1932")])
def test_impossible_or_reversed_date_windows_are_refused(a, b):
    with pytest.raises(ValidationError):
        S.SearchInput(query="x", date_from=a, date_to=b)


def test_record_url_with_query_string():
    assert S.parse_record_id("https://jdcat.jsps.go.jp/records/7058?lang=ja") == 7058
