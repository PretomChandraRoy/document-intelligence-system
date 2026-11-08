"""REST API end to end: upload, processing, results, corrections, search, groups, failures.

Celery runs inline in tests, so each upload is fully processed before the
response comes back.
"""
import pytest

from app.pipeline import llm
from tests.helpers import mismatches


def upload(client, files, *names):
    payload = [("files", (n, open(files[n].path, "rb"))) for n in names]
    r = client.post("/api/v1/documents", files=payload)
    assert r.status_code == 202, r.text
    return r.json()


def doc(client, doc_id):
    r = client.get(f"/api/v1/documents/{doc_id}")
    assert r.status_code == 200
    return r.json()


def first_invoice(client, d):
    return client.get(f"/api/v1/invoices/{d['invoices'][0]['id']}").json()


# -- authentication ---------------------------------------------------------------------
def test_requests_without_key_are_rejected(client):
    r = client.get("/api/v1/documents", headers={"X-API-Key": ""})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorised"
    r = client.get("/api/v1/documents", headers={"X-API-Key": "wrong-key-wrong-key"})
    assert r.status_code == 401


def test_health_needs_no_key(client):
    r = client.get("/health", headers={"X-API-Key": ""})
    assert r.status_code == 200 and r.json()["database"] == "ok"


# -- upload and processing ------------------------------------------------------------------
@pytest.mark.parametrize("name", ["classic.pdf", "scan_clean.png", "form.xlsx", "ledger.csv", "mixed.pdf"])
def test_upload_processes_each_format(client, files, name):
    res = upload(client, files, name)
    d = doc(client, res["accepted"][0]["id"])
    assert d["status"] in ("completed", "needs_review"), d
    assert d["progress_done"] == d["progress_total"] and d["stage"] == "done"
    assert len(d["invoices"]) == len(files[name].truth)


def test_extracted_json_matches_the_document(client, files):
    d = doc(client, upload(client, files, "classic.pdf")["accepted"][0]["id"])
    inv = first_invoice(client, d)
    assert mismatches(inv, files["classic.pdf"].gt) == []
    assert inv["extraction_method"] == "rules"
    assert isinstance(inv["total"], str)          # money is a string, not a float
    assert inv["review_status"] == "auto_approved"


def test_multi_file_upload_with_one_rejected(client, files):
    res = upload(client, files, "classic.pdf", "notes.docx", "form.xls")
    assert len(res["accepted"]) == 2
    assert res["rejected"] == [{"filename": "notes.docx", "code": "unsupported_format",
                                "message": "Accepted formats: PDF, JPG, PNG, TIFF, XLSX, XLS, CSV"}]


def test_bundle_becomes_three_invoices(client, files):
    d = doc(client, upload(client, files, "bundle.pdf")["accepted"][0]["id"])
    assert sorted(i["invoice_number"] for i in d["invoices"]) == sorted(t["invoice_number"] for t in files["bundle.pdf"].truth)


def test_exact_reupload_is_detected(client, files):
    a = upload(client, files, "classic.pdf")["accepted"][0]
    b = upload(client, files, "classic.pdf")["accepted"][0]
    assert b["exact_duplicate_of"] == a["id"]


@pytest.mark.parametrize("name,code", [
    ("encrypted.pdf", "encrypted"), ("truncated.pdf", "corrupted"), ("empty.png", "empty_file"),
    ("renamed.xlsx", "corrupted"), ("truncated.jpg", "corrupted"), ("header_only.csv", "no_data"),
])
def test_bad_files_fail_cleanly(client, files, name, code):
    d = doc(client, upload(client, files, name)["accepted"][0]["id"])
    assert d["status"] == "failed" and d["error_code"] == code and d["error_message"]
    assert d["invoices"] == []


def test_history_records_each_stage(client, files):
    d = doc(client, upload(client, files, "scanned.pdf")["accepted"][0]["id"])
    runs = client.get(f"/api/v1/documents/{d['id']}/history").json()
    assert runs[0]["status"] == "succeeded"
    assert {"ingest", "ocr", "extract", "post"} <= set(runs[0]["stage_timings_ms"])
    assert any("page(s)" in e["message"] for e in runs[0]["events"])


def test_original_file_and_page_image(client, files):
    d = doc(client, upload(client, files, "classic.pdf")["accepted"][0]["id"])
    r = client.get(f"/api/v1/documents/{d['id']}/file")
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
    r = client.get(f"/api/v1/documents/{d['id']}/pages/1/image")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


# -- validation and review -------------------------------------------------------------------
def test_wrong_total_is_flagged_for_review(client, files):
    d = doc(client, upload(client, files, "wrong_total.pdf")["accepted"][0]["id"])
    inv = first_invoice(client, d)
    assert d["status"] == "needs_review" and inv["review_status"] == "needs_review"
    assert "total_mismatch" in {i["code"] for i in inv["issues"]}


def test_correction_revalidates_and_is_audited(client, files):
    d = doc(client, upload(client, files, "wrong_total.pdf")["accepted"][0]["id"])
    inv = first_invoice(client, d)
    from decimal import Decimal
    fixed = str(Decimal(inv["subtotal"]) + Decimal(inv["tax"] or "0"))
    r = client.patch(f"/api/v1/invoices/{inv['id']}", json={"corrected_by": "Pretom", "fields": {"total": fixed, "currency": "USD"},
                                                            "note": "checked with supplier"})
    assert r.status_code == 200, r.text
    after = r.json()
    assert after["total"] == fixed and after["review_status"] == "reviewed"
    assert all(i["resolved"] for i in after["issues"] if i["code"] == "total_mismatch")
    hist = client.get(f"/api/v1/invoices/{inv['id']}/corrections").json()
    t = next(h for h in hist if h["field_path"] == "total")
    assert t["new_value"] == fixed and t["corrected_by"] == "Pretom"
    assert doc(client, d["id"])["status"] == "completed"


def test_approval_blocked_by_errors_but_can_accept_with_issues(client, files):
    d = doc(client, upload(client, files, "wrong_total.pdf")["accepted"][0]["id"])
    inv_id = d["invoices"][0]["id"]
    r = client.post(f"/api/v1/invoices/{inv_id}/review", json={"reviewed_by": "Pretom"})
    assert r.status_code == 409
    r = client.post(f"/api/v1/invoices/{inv_id}/review",
                    json={"reviewed_by": "Pretom", "decision": "accept_with_issues", "note": "supplier error"})
    assert r.status_code == 200 and r.json()["review_status"] == "reviewed"


def test_invalid_correction_is_rejected(client, files):
    d = doc(client, upload(client, files, "classic.pdf")["accepted"][0]["id"])
    r = client.patch(f"/api/v1/invoices/{d['invoices'][0]['id']}",
                     json={"corrected_by": "x", "fields": {"total": "not-a-number"}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"


# -- duplicates and cross-verification ----------------------------------------------------------
def test_duplicate_across_formats(client, files):
    upload(client, files, "dup_a.pdf", "dup_b.png")
    groups = client.get("/api/v1/groups").json()["items"]
    assert len(groups) == 1 and groups[0]["status"] == "consistent"
    assert {m["format"] for m in groups[0]["members"]} == {"pdf", "png"}


def test_pdf_excel_cross_verification_finds_the_difference(client, files):
    upload(client, files, "cross.pdf", "cross.xlsx")
    g = client.get("/api/v1/groups", params={"status": "mismatch"}).json()["items"]
    assert len(g) == 1 and "total" in g[0]["mismatched_fields"]
    inv = client.get(f"/api/v1/invoices/{g[0]['members'][0]['invoice_id']}").json()
    assert any(i["code"] == "cross_mismatch" and i["field"] == "total" for i in inv["issues"])


def test_manual_cross_verify(client, files):
    a = doc(client, upload(client, files, "classic.pdf")["accepted"][0]["id"])["invoices"][0]["id"]
    b = doc(client, upload(client, files, "modern.pdf")["accepted"][0]["id"])["invoices"][0]["id"]
    r = client.post("/api/v1/cross-verify", json={"invoice_ids": [a, b], "save_group": True})
    assert r.status_code == 200 and "invoice_number" in r.json()["mismatched_fields"]
    assert r.json()["group_id"]


# -- search -------------------------------------------------------------------------------------
def test_keyword_semantic_and_filtered_search(client, files):
    upload(client, files, "classic.pdf", "modern.pdf", "homecare.pdf")
    hc = files["homecare.pdf"].gt
    word = hc["line_items"][0]["description"].split()[0]
    for mode in ("keyword", "semantic", "hybrid"):
        r = client.get("/api/v1/search", params={"q": word, "mode": mode})
        assert r.status_code == 200
        assert r.json()["results"][0]["invoice_number"] == hc["invoice_number"], mode
    r = client.get("/api/v1/search", params={"q": word, "currency": "GBP"})
    assert all(x["currency"] == "GBP" for x in r.json()["results"])
    r = client.get("/api/v1/invoices", params={"supplier": hc["supplier_name"][:6]})
    assert r.json()["total"] >= 1


def test_export_csv(client, files):
    upload(client, files, "classic.pdf")
    r = client.get("/api/v1/invoices/export")
    assert r.status_code == 200 and files["classic.pdf"].gt["invoice_number"] in r.text


# -- reprocessing and failure handling -------------------------------------------------------------
def test_reprocess_creates_a_new_run(client, files):
    d = doc(client, upload(client, files, "classic.pdf")["accepted"][0]["id"])
    r = client.post(f"/api/v1/documents/{d['id']}/reprocess", json={"from_stage": "extract"})
    assert r.status_code == 202 and r.json()["attempt"] == 2
    again = doc(client, d["id"])
    assert again["status"] == "completed" and len(again["invoices"]) == 1


def test_reprocess_failed_in_bulk(client, files):
    upload(client, files, "encrypted.pdf", "empty.png")
    r = client.post("/api/v1/documents/reprocess-failed")
    assert r.json()["queued"] == 2


def test_model_outage_falls_back_to_rules(client, files):
    class Down(llm.MockClient):
        def chat_json(self, *a, **k):
            raise llm.LLMError("connection refused")
    llm.set_client(Down())
    d = doc(client, upload(client, files, "wrong_total.pdf")["accepted"][0]["id"])
    assert d["status"] == "needs_review" and len(d["invoices"]) == 1
    runs = client.get(f"/api/v1/documents/{d['id']}/history").json()
    assert any("used rules only" in e["message"] for e in runs[0]["events"])


def test_unexpected_error_marks_document_failed(client, files, monkeypatch):
    from app import services
    monkeypatch.setattr(services, "parse_workbook", lambda pages: 1 / 0)
    d = doc(client, upload(client, files, "form.xlsx")["accepted"][0]["id"])
    assert d["status"] == "failed" and d["error_code"] == "internal"


def test_stats(client, files):
    upload(client, files, "classic.pdf", "encrypted.pdf")
    s = client.get("/api/v1/stats").json()
    assert s["documents"]["total"] == 2 and s["documents"]["failed"] == 1
    assert s["failure_reasons"] == {"encrypted": 1}


def test_reprocessing_does_not_leave_empty_groups(client, files):
    a = upload(client, files, "dup_a.pdf")["accepted"][0]["id"]
    upload(client, files, "dup_b.png")
    assert client.get("/api/v1/groups").json()["total"] == 1
    client.post(f"/api/v1/documents/{a}/reprocess", json={"from_stage": "extract"})
    groups = client.get("/api/v1/groups").json()["items"]
    assert len(groups) == 1 and len(groups[0]["members"]) == 2


def test_semantic_search_drops_unrelated_invoices(client, files):
    upload(client, files, "classic.pdf", "modern.pdf", "homecare.pdf")
    hc = files["homecare.pdf"].gt
    query = " ".join(li["description"] for li in hc["line_items"])
    r = client.get("/api/v1/search", params={"q": query, "mode": "semantic"}).json()["results"]
    # the home care invoice ranks first and the unrelated office-supply invoices are left out
    assert r[0]["invoice_number"] == hc["invoice_number"] and len(r) < 3
