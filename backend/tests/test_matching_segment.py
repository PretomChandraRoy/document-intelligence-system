"""Duplicate keys, field comparison, and splitting multi-invoice PDFs."""
from decimal import Decimal as D

from app.pipeline.ingest import ingest
from app.pipeline.matching import compare, dedupe_key
from app.pipeline.schema import ExtractedInvoice, ExtractedLine
from app.pipeline.segment import segment_pages


def test_dedupe_key_ignores_case_punctuation_and_legal_suffix():
    assert dedupe_key("Padma Trading Co.", "INV-0042") == dedupe_key("PADMA TRADING", "inv 42")
    assert dedupe_key("Acme GmbH", None) is None


def test_compare_reports_differing_fields():
    a = ExtractedInvoice(invoice_number="1", total=D("10.00"), line_items=[ExtractedLine("x", D(1), D(10), D(10))])
    b = ExtractedInvoice(invoice_number="1", total=D("12.00"), line_items=[ExtractedLine("x", D(1), D(10), D(10))])
    mismatched, rows = compare([a, b])
    assert mismatched == ["total"]
    assert next(r for r in rows if r["field"] == "total")["values"] == ["10.00", "12.00"]


def test_bundle_is_split_into_invoices(files):
    f = files["bundle.pdf"]
    pages = [(p.number, p.text) for p in ingest(f.path, "pdf").pages]
    segs = segment_pages(pages)
    assert len(segs) == 3
    assert [s.invoice_number for s in segs] == [t["invoice_number"] for t in f.truth]


def test_long_invoice_stays_one_segment(files):
    pages = [(p.number, p.text) for p in ingest(files["long.pdf"].path, "pdf").pages]
    assert len(pages) > 1 and len(segment_pages(pages)) == 1
