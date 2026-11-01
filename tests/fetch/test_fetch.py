"""fetch: offline tests. PDFs are built here, byte by byte; the network is a MockTransport.

What is pinned: nothing is written without a configured folder; only a real PDF is
saved; a landing page, a private address, an oversize file and a work with no
open-access copy are refused with typed diagnostics; the receipt names the record
and the file's SHA-256; the text layer is reported page by page; fetch_pdf_text
reads only inside the download folder; every envelope validates against the schema.
"""
import json
from pathlib import Path

import httpx
import jsonschema
import pytest

from bibliograph.sources.fetch import server as F

SCHEMA = json.loads((Path(__file__).parents[1] / "response-schema.json").read_text(encoding="utf-8"))
LONG = "This page carries a text layer of some length for the probe. " * 5


def make_pdf(pages, image=None):
    """A minimal valid PDF: one Helvetica text line per page, or an empty page for None.
    image=(x, y, w, h, tx, ty) also paints a one-pixel grey image scaled to that box on
    every page and sets the text at (tx, ty): a scan with an OCR layer when the text
    sits on the picture, a page with a photograph when it does not."""
    objects = {1: b"<< /Type /Catalog /Pages 2 0 R >>",
               3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               4: b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray "
                  b"/BitsPerComponent 8 /Length 1 >>\nstream\n\x80\nendstream"}
    nxt, kids = 5, []
    x, y, w, h, tx, ty = image or (0, 0, 0, 0, 20, 720)
    for text in pages:
        pid, cid = nxt, nxt + 1
        nxt += 2
        kids.append(f"{pid} 0 R")
        paint = f"q {w} 0 0 {h} {x} {y} cm /Im1 Do Q " if image else ""
        stream = (paint + (f"BT /F1 9 Tf {tx} {ty} Td ({text}) Tj ET" if text else "")).encode("latin-1")
        objects[cid] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        objects[pid] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                        f"/Resources << /Font << /F1 3 0 R >> /XObject << /Im1 4 0 R >> >> "
                        f"/Contents {cid} 0 R >>").encode()
    objects[2] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>".encode()
    out, offsets = bytearray(b"%PDF-1.4\n"), {}
    for i in range(1, nxt):
        offsets[i] = len(out)
        out += f"{i} 0 obj\n".encode() + objects[i] + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {nxt}\n0000000000 65535 f \n".encode()
    for i in range(1, nxt):
        out += f"{offsets[i]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {nxt} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


PDF = make_pdf([LONG, None])
WORK = {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/x", "display_name": "A title",
        "open_access": {"is_oa": True, "oa_status": "gold", "oa_url": "https://example.org/landing"},
        "best_oa_location": {"pdf_url": "https://example.org/a.pdf", "license": "cc-by", "version": "publishedVersion",
                             "source": {"display_name": "Example Journal"}},
        "locations": []}


def codes(env):
    return [d["code"] for d in env["diagnostics"]]


def valid(env):
    errs = list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(env))
    assert not errs, errs[0].message
    return env


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setenv(F.DOWNLOAD_ENV, str(tmp_path))
    monkeypatch.delenv("MCP_RECEIPT_DIR", raising=False)
    monkeypatch.delenv("MCP_RECEIPT_LOG", raising=False)
    monkeypatch.setattr(F, "MIN_REQUEST_INTERVAL", 0.0)
    monkeypatch.setattr(F, "_lock_obj", None)

    async def ok_host(url):
        # example.org stands in for a public host; the download is pinned to this TEST-NET
        # address, and the mock transport routes on the Host header.
        return (None, "203.0.113.7") if "example.org" in url else ("not a public address", None)
    monkeypatch.setattr(F, "vet", ok_host)

    async def oa(endpoint, params=None):
        return dict(WORK), None
    monkeypatch.setattr(F._OA, "_oa_request", oa)
    yield tmp_path
    F._TRANSPORT = None


def serve(table):
    def handler(req):
        asked = f"{req.url.scheme}://{req.headers['host']}{req.url.raw_path.decode()}"
        for prefix, resp in table:
            if asked.startswith(prefix):
                return resp(req) if callable(resp) else resp
        return httpx.Response(404)
    F._TRANSPORT = httpx.MockTransport(handler)


async def run(via, record):
    return valid(json.loads(await F.fetch_pdf(F.FetchPdfInput(via=via, record=record))))


async def text(file, **kw):
    return valid(json.loads(await F.fetch_pdf_text(F.PdfTextInput(file=file, **kw))))


# ---------------------------------------------------------------- refusals before anything is fetched

async def test_no_folder_no_fetch(monkeypatch):
    monkeypatch.delenv(F.DOWNLOAD_ENV, raising=False)
    env = await run("openalex", "W1")
    assert codes(env) == ["DOWNLOAD_DIR_NOT_SET"] or "DOWNLOAD_DIR_NOT_SET" in codes(env)
    assert env["items"] == []


async def test_placeholder_counts_as_unset(monkeypatch):
    monkeypatch.setenv(F.DOWNLOAD_ENV, "${user_config.download_dir}")
    assert F.download_dir() is None


async def test_bad_openalex_identifier(folder):
    env = await run("openalex", "not-an-id")
    assert "BAD_IDENTIFIER" in codes(env)


# ---------------------------------------------------------------- the happy path

async def test_openalex_pdf_saved_with_provenance_and_receipt(folder):
    serve([("https://example.org/a.pdf", httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"}))])
    env = await run("openalex", "W1")
    assert "SAVED" in codes(env) and "PARTIAL_TEXT_LAYER" in codes(env)
    it = env["items"][0]
    ex = it["extra"]
    assert ex["text_layer"] == "partial" and ex["pages_without_text"] == "2" and ex["page_count"] == 2
    assert ex["licence"] == "cc-by" and ex["oa_status"] == "gold"
    saved = Path(ex["saved_path"])
    assert saved.read_bytes() == PDF and saved.parent == folder
    prov = json.loads((folder / ex["provenance_file"]).read_text(encoding="utf-8"))
    assert prov["sha256"] == ex["sha256"] and len(prov["fetches"]) == 1
    assert prov["fetches"][0]["licence"] == "cc-by" and prov["fetches"][0]["doi"] == "10.1/x"
    assert env["receipt"]["result_ids"] == ["10.1/x", f"sha256:{ex['sha256']}"]
    assert it["title"]["en"] == "A title" and it["ids"]["doi"] == "10.1/x"


async def test_same_file_twice_is_not_written_twice(folder):
    serve([("https://example.org/a.pdf", httpx.Response(200, content=PDF))])
    await run("openalex", "W1")
    env = await run("openalex", "W1")
    assert "ALREADY_SAVED" in codes(env)
    assert len(list(folder.glob("*.pdf"))) == 1


async def test_supplied_url_flags_no_licence_check(folder):
    serve([("https://example.org/b.pdf", httpx.Response(200, content=make_pdf([LONG])))])
    env = await run("url", "https://example.org/b.pdf?token=SECRET123")
    assert "SUPPLIED_URL_NO_LICENCE_CHECK" in codes(env)
    assert "SECRET123" not in json.dumps(env)
    assert env["items"][0]["extra"]["text_layer"] == "full"


async def test_semantic_scholar_resolver(folder, monkeypatch):
    async def s2(method, url, params=None, json_body=None):
        assert url.endswith("/paper/DOI:10.2/y")
        return {"paperId": "abc", "title": "S2 title", "externalIds": {"DOI": "10.2/y"},
                "openAccessPdf": {"url": "https://example.org/c.pdf", "status": "GREEN"}}, None
    monkeypatch.setattr(F._S2, "_api_request", s2)
    serve([("https://example.org/c.pdf", httpx.Response(200, content=make_pdf([LONG])))])
    env = await run("semantic_scholar", "10.2/y")
    assert "SAVED" in codes(env) and "LICENCE_NOT_STATED" in codes(env)
    assert env["items"][0]["extra"]["file"].startswith("s2-abc-")


# ---------------------------------------------------------------- refusals after resolution

async def test_landing_page_is_not_saved(folder, monkeypatch):
    work = dict(WORK, best_oa_location={"pdf_url": None}, locations=[])
    async def oa(endpoint, params=None):
        return work, None
    monkeypatch.setattr(F._OA, "_oa_request", oa)
    serve([("https://example.org/landing", httpx.Response(200, text="<html>login</html>",
                                                          headers={"content-type": "text/html"}))])
    env = await run("openalex", "W1")
    assert "NOT_A_PDF" in codes(env) and env["items"] == []
    assert list(folder.iterdir()) == []


async def test_no_open_access_copy(folder, monkeypatch):
    async def oa(endpoint, params=None):
        return {"id": "W2", "open_access": {"is_oa": False}, "best_oa_location": None, "locations": []}, None
    monkeypatch.setattr(F._OA, "_oa_request", oa)
    env = await run("openalex", "W2")
    assert "NO_OA_COPY" in codes(env) and env["items"] == []


async def test_redirect_onto_a_private_address_is_refused(folder):
    serve([("https://example.org/a.pdf", httpx.Response(302, headers={"location": "http://10.0.0.5/b.pdf"}))])
    env = await run("openalex", "W1")
    assert "ADDRESS_REFUSED" in codes(env)
    assert list(folder.iterdir()) == []


async def test_real_address_check_refuses_loopback_and_odd_schemes():
    for bad in ("http://127.0.0.1/x.pdf", "http://[::1]/x.pdf", "http://10.0.0.5/x.pdf",
                "file:///etc/passwd", "ftp://example.org/x.pdf", "http://169.254.169.254/latest"):
        assert await F.public_host(bad), bad
    from bibliograph.sources.fetch.server import _ip_is_public
    assert not _ip_is_public("127.0.0.1") and not _ip_is_public("10.1.2.3") and not _ip_is_public("::1")
    assert _ip_is_public("8.8.8.8")


async def test_oversize_file_refused(folder, monkeypatch):
    monkeypatch.setattr(F, "MAX_BYTES", 100)
    serve([("https://example.org/a.pdf", httpx.Response(200, content=PDF))])
    env = await run("openalex", "W1")
    assert "FILE_TOO_LARGE" in codes(env)
    assert list(folder.glob("*.pdf")) == []


async def test_http_error_tries_next_candidate(folder, monkeypatch):
    work = dict(WORK, locations=[{"is_oa": True, "pdf_url": "https://example.org/mirror.pdf"}])
    async def oa(endpoint, params=None):
        return work, None
    monkeypatch.setattr(F._OA, "_oa_request", oa)
    serve([("https://example.org/a.pdf", httpx.Response(403)),
           ("https://example.org/mirror.pdf", httpx.Response(200, content=PDF))])
    env = await run("openalex", "W1")
    assert "SAVED" in codes(env)
    assert env["items"][0]["extra"]["attempts_refused"][0]["refused"] == "HTTP_STATUS"


# ---------------------------------------------------------------- the text layer

async def test_text_by_page_and_empty_pages_named(folder):
    serve([("https://example.org/a.pdf", httpx.Response(200, content=PDF))])
    name = (await run("openalex", "W1"))["items"][0]["extra"]["file"]
    env = await text(name, pages="1")
    page = env["items"][0]["extra"]["pages"][0]
    assert page["page"] == 1 and "text layer" in page["text"]
    assert env["items"][0]["title"]["en"] == "A title"
    env = await text(name, pages="2")
    assert "NO_TEXT_LAYER" in codes(env)
    env = await text(name, pages="2-9")
    assert "PAGES_OUT_OF_RANGE" in codes(env)


async def test_text_budget_truncates_and_says_where(folder):
    serve([("https://example.org/b.pdf", httpx.Response(200, content=make_pdf([LONG, LONG, LONG])))])
    name = (await run("url", "https://example.org/b.pdf"))["items"][0]["extra"]["file"]
    env = await text(name, max_chars=500)
    assert "TEXT_TRUNCATED" in codes(env)
    assert [p["page"] for p in env["items"][0]["extra"]["pages"]] == [1]


async def test_text_refuses_files_outside_the_folder(folder, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere") / "x.pdf"
    outside.write_bytes(PDF)
    for f in (str(outside), "../x.pdf", "notes.txt"):
        env = await text(f)
        assert "FILE_REFUSED" in codes(env), f
    env = await text("missing.pdf")
    assert "FILE_NOT_FOUND" in codes(env)
    env = await text("missing.pdf", pages="0")
    assert "FILE_NOT_FOUND" in codes(env) or "BAD_PAGES" in codes(env)


async def test_unreadable_pdf_is_reported_not_raised(folder):
    serve([("https://example.org/a.pdf", httpx.Response(200, content=b"%PDF-1.4\n garbage without structure"))])
    env = await run("openalex", "W1")
    assert "SAVED" in codes(env) and "PDF_UNREADABLE" in codes(env)


# ---------------------------------------------------------------- helpers

def test_helpers():
    assert F.page_ranges([1, 2, 3, 7, 9, 10]) == "1-3, 7, 9-10"
    assert F.parse_pages("3,1-2, 7") == [1, 2, 3, 7] and F.parse_pages(None) is None
    with pytest.raises(ValueError):
        F.parse_pages("one")
    assert "REDACTED" in F.redact_url("https://a.org/x.pdf?X-Amz-Signature=abc&id=1")
    assert "id=1" in F.redact_url("https://a.org/x.pdf?X-Amz-Signature=abc&id=1")
    assert F.slug_for("openalex", "W123") == "oa-W123"
    assert F.slug_for("url", "https://www.jstage.jst.go.jp/a/_pdf") == "url-www.jstage.jst.go.jp"
    assert F.looks_like_pdf(b"\n\n%PDF-1.7") and not F.looks_like_pdf(b"<html>")


def test_scan_with_ocr_layer_is_named_and_a_photo_page_is_not():
    short = "OCR layer text sitting on a scanned page"
    scan = F.page_texts(make_pdf([short, short], image=(40, 60, 520, 680, 60, 400)))
    layer, _, diags = F.text_layer_diags(scan, sorted(scan["texts"]))
    assert scan["image_pages"] == [1, 2] and layer == "ocr"
    assert [d["code"] for d in diags] == ["OCR_TEXT_LAYER"]
    photo = F.page_texts(make_pdf([short], image=(40, 60, 520, 300, 60, 720)))
    layer, _, diags = F.text_layer_diags(photo, sorted(photo["texts"]))
    assert photo["image_pages"] == [] and layer == "full" and diags == []


# ---------------------------------------------------------------- second-model review, 7 Oct 2026

async def test_real_vet_refuses_a_redirect_to_a_private_ip(monkeypatch, tmp_path):
    """No stand-in for vet: an IP-literal public host redirects to 10.0.0.5."""
    monkeypatch.setenv(F.DOWNLOAD_ENV, str(tmp_path))
    monkeypatch.setattr(F, "MIN_REQUEST_INTERVAL", 0.0)
    monkeypatch.setattr(F, "_lock_obj", None)
    serve([("https://8.8.8.8/a.pdf", httpx.Response(302, headers={"location": "http://10.0.0.5/b.pdf"}))])
    try:
        env = await run("url", "https://8.8.8.8/a.pdf")
    finally:
        F._TRANSPORT = None
    assert "ADDRESS_REFUSED" in codes(env) and "10.0.0.5" in json.dumps(env)
    assert list(tmp_path.iterdir()) == []


def test_only_global_addresses_are_public():
    for ip in ("100.64.0.1", "fec0::1", "::ffff:127.0.0.1", "2002:7f00:1::1", "64:ff9b::a00:1", "0.0.0.0"):
        assert not F._ip_is_public(ip), ip
    assert F._ip_is_public("8.8.8.8") and F._ip_is_public("2001:4860:4860::8888")


def test_redaction_drops_userinfo_and_fragment():
    r = F.redact_url("https://user:pw@example.com:8443/x.pdf?id=1&auth=z&jwt=q#access_token=abc")
    assert r == "https://example.com:8443/x.pdf?id=1&auth=REDACTED&jwt=REDACTED"


def test_pinned_keeps_host_for_tls():
    target, headers, ext = F.pinned("https://example.org:8443/a.pdf?x=1", "93.184.216.34")
    assert target == "https://93.184.216.34:8443/a.pdf?x=1"
    assert headers == {"Host": "example.org:8443"} and ext == {"sni_hostname": "example.org"}
    assert F.pinned("http://example.org/a", "2001:db8::1")[0] == "http://[2001:db8::1]/a"


def test_text_inside_a_form_xobject_is_read():
    stream = b"BT /F1 9 Tf 20 720 Td (Text drawn inside a form XObject on this page) Tj ET"
    objs = {1: b"<< /Type /Catalog /Pages 2 0 R >>", 2: b"<< /Type /Pages /Kids [5 0 R] /Count 1 >>",
            3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            4: b"<< /Type /XObject /Subtype /Form /BBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> "
               b"/Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            6: b"<< /Length 8 >>\nstream\n/Fm1 Do\nendstream",
            5: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /XObject << /Fm1 4 0 R >> >> "
               b"/Contents 6 0 R >>"}
    out, off = bytearray(b"%PDF-1.4\n"), {}
    for i in range(1, 7):
        off[i] = len(out)
        out += f"{i} 0 obj\n".encode() + objs[i] + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 7\n0000000000 65535 f \n" + b"".join(f"{off[i]:010d} 00000 n \n".encode() for i in range(1, 7))
    out += f"trailer\n<< /Size 7 /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    probe = F.page_texts(bytes(out))
    assert "form XObject" in probe["texts"][1]


def test_first_page_longer_than_the_budget_is_cut_and_said():
    probe = F.page_texts(make_pdf([LONG, LONG]), None, 600, 100)
    assert len(probe["texts"][1]) == 100 and probe["page_cut"] == 1 and probe["truncated_at"] == 1


async def test_page_limit_without_a_range_is_said(folder, monkeypatch):
    monkeypatch.setattr(F, "PROBE_PAGE_LIMIT", 2)
    serve([("https://example.org/b.pdf", httpx.Response(200, content=make_pdf(["short page text here ok yes"] * 4)))])
    name = (await run("url", "https://example.org/b.pdf"))["items"][0]["extra"]["file"]
    env = await text(name)
    d = next(d for d in env["diagnostics"] if d["code"] == "TEXT_TRUNCATED")
    assert "first 2 of 4" in d["message"] and "3-4" in d["hint"]


async def test_second_source_for_the_same_file_is_recorded(folder, monkeypatch):
    serve([("https://example.org/a.pdf", httpx.Response(200, content=PDF))])
    first = await run("openalex", "W1")
    second = await run("url", "https://example.org/a.pdf")
    assert "ALREADY_SAVED" in codes(second)
    prov = json.loads((folder / first["items"][0]["extra"]["provenance_file"]).read_text(encoding="utf-8"))
    assert [f["resolved_via"] for f in prov["fetches"]] == ["openalex", "url"]


async def test_failed_write_leaves_no_part_file(folder, monkeypatch):
    def boom(a, b):
        raise PermissionError("locked")
    monkeypatch.setattr(F.os, "replace", boom)
    serve([("https://example.org/a.pdf", httpx.Response(200, content=PDF))])
    env = await run("openalex", "W1")
    assert "DOWNLOAD_DIR_UNUSABLE" in codes(env)
    assert list(folder.iterdir()) == []


async def test_network_paths_and_bad_ids_refused(folder):
    env = await text("\\\\server\\share\\x.pdf")
    assert "FILE_REFUSED" in codes(env)
    env = await run("semantic_scholar", "abc?fields=x")
    assert "BAD_IDENTIFIER" in codes(env)
    env = await run("openalex", "10.1/x#frag")
    assert "BAD_IDENTIFIER" in codes(env)
