"""AI extraction: tier choice, grounding (no invented values), merging and fall-back."""
import json

from app.pipeline import llm
from app.pipeline.extract import extract_invoice
from app.pipeline.ingest import ingest
from app.pipeline.llm import ground
from tests.helpers import mismatches


def text_of(path):
    return "\n".join(p.text or "" for p in ingest(path, "pdf").pages)


def model_answer(gt, **override):
    out = {f: {"value": gt[f], "evidence": gt[f]} for f in
           ("invoice_number", "invoice_date", "supplier_name", "customer_name", "subtotal", "tax", "total", "currency")}
    out["line_items"] = gt["line_items"]
    for k, v in override.items():
        out[k] = v
    return out


def test_consistent_rules_result_skips_the_model(files):
    client = llm.MockClient()
    inv = extract_invoice(text_of(files["classic.pdf"].path), client)
    assert inv.method == "rules" and client.calls == 0


def test_inconsistent_result_asks_the_model(files):
    client = llm.MockClient()
    inv = extract_invoice(text_of(files["wrong_total.pdf"].path), client)
    assert client.calls == 1
    assert str(inv.total) == files["wrong_total.pdf"].gt["total"]


def test_invented_value_is_discarded():
    source = "INVOICE\nInvoice No: INV-1\nTotal: 100.00"
    raw = {"invoice_number": {"value": "INV-1", "evidence": "Invoice No: INV-1"},
           "invoice_date": {"value": "2026-03-01", "evidence": "dated 1 March"},   # not in the text
           "supplier_name": {"value": "Acme Ltd", "evidence": None},             # not in the text
           "customer_name": {"value": None, "evidence": None},
           "subtotal": {"value": None, "evidence": None}, "tax": {"value": None, "evidence": None},
           "total": {"value": "100.00", "evidence": "Total: 100.00"},
           "currency": {"value": None, "evidence": None},
           "line_items": [{"description": "Widgets", "quantity": "2", "unit_price": "50", "amount": "100.00"}]}
    inv = ground(raw, source)
    assert inv.invoice_number == "INV-1" and str(inv.total) == "100.00"
    assert inv.invoice_date is None and inv.supplier_name is None
    assert inv.line_items == []                      # "Widgets" is not in the text
    fields = {w["field"] for w in inv.warnings}
    assert {"invoice_date", "supplier_name", "line_items"} <= fields


def test_null_stays_null(files):
    f = files["missing_date.pdf"]
    client = llm.MockClient()
    client.scripted = [model_answer(f.gt)]
    inv = extract_invoice(text_of(f.path), client)
    assert inv.invoice_date is None


def test_model_fills_a_field_the_rules_missed(files):
    f = files["classic.pdf"]
    text = text_of(f.path).replace("Bill To:", "Attention")   # rules can no longer find the customer
    client = llm.MockClient()
    client.scripted = [model_answer(f.gt)]
    inv = extract_invoice(text, client)
    assert inv.customer_name == f.gt["customer_name"] and inv.method == "llm"


def test_disagreement_is_flagged_for_review(files):
    f = files["missing_date.pdf"]
    client = llm.MockClient()
    other = "Somebody Else" if f.gt["customer_name"] != "Somebody Else" else "Another"
    text = text_of(f.path) + f"\n{other}"
    client.scripted = [model_answer(f.gt, customer_name={"value": other, "evidence": other})]
    inv = extract_invoice(text, client)
    assert inv.confidence["customer_name"] < 0.6
    assert any(w["field"] == "customer_name" for w in inv.warnings)


def test_long_invoice_is_sent_in_parts(files, monkeypatch):
    monkeypatch.setattr(llm, "SINGLE_CALL_MAX_CHARS", 1000)
    f = files["long.pdf"]
    pages = [p.text for p in ingest(f.path, "pdf").pages]
    client = llm.MockClient()
    inv = extract_invoice("\n\n".join(pages), client, page_texts=pages, force_llm=True)
    assert client.calls == 1 + len(pages)     # header call + one call per page
    assert len(inv.line_items) == 50


def test_model_unavailable_falls_back_to_rules_with_low_confidence(files):
    inv = extract_invoice(text_of(files["wrong_total.pdf"].path), None)
    assert inv.method == "rules"
    assert max(inv.confidence.values()) <= 0.5


def test_low_ocr_confidence_caps_field_confidence(files):
    inv = extract_invoice(text_of(files["classic.pdf"].path), llm.MockClient(), ocr_confidence=35)
    assert max(inv.confidence.values()) <= 0.46


def test_ollama_request_shape(monkeypatch):
    sent = {}

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": json.dumps({"line_items": []})}}

    def fake_post(url, json=None, timeout=None):
        sent.update(url=url, body=json)
        return R()
    monkeypatch.setattr(llm.httpx, "post", fake_post)
    c = llm.OllamaClient("http://h:11434", "qwen3:8b", "nomic-embed-text")
    c.chat_json("sys", "user", llm.schema_of(llm.LinesOut))
    assert sent["url"].endswith("/api/chat")
    assert sent["body"]["options"]["temperature"] == 0
    assert sent["body"]["format"]["type"] == "object" and sent["body"]["think"] is False


def test_ollama_timeout_raises_retryable_error(monkeypatch):
    import httpx
    import pytest

    def boom(*a, **k):
        raise httpx.ConnectTimeout("timeout")
    monkeypatch.setattr(llm.httpx, "post", boom)
    with pytest.raises(llm.LLMError):
        llm.OllamaClient("http://h", "m", "e").chat_json("s", "u", {})
