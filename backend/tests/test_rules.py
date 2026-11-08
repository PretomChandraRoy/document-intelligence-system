"""Tier 1 rules extractor on digital PDFs of every layout."""
import pytest

from app.pipeline.ingest import ingest
from app.pipeline.rules import arithmetic_consistent, extract_rules
from tests.helpers import mismatches


def text_of(path):
    return "\n".join(p.text or "" for p in ingest(path, "pdf").pages)


@pytest.mark.parametrize("name", ["classic.pdf", "modern.pdf", "receipt.pdf", "homecare.pdf", "long.pdf"])
def test_all_fields_on_each_layout(files, name):
    f = files[name]
    inv = extract_rules(text_of(f.path))
    assert mismatches(inv.as_dict(), f.gt) == []
    assert arithmetic_consistent(inv)


def test_multi_page_line_items_are_all_collected(files):
    inv = extract_rules(text_of(files["long.pdf"].path))
    assert len(inv.line_items) == 50


def test_missing_field_stays_empty(files):
    inv = extract_rules(text_of(files["missing_date.pdf"].path))
    assert inv.invoice_date is None
    assert "invoice_date" in inv.missing()


def test_printed_wrong_total_is_read_as_printed(files):
    f = files["wrong_total.pdf"]
    inv = extract_rules(text_of(f.path))
    assert str(inv.total) == f.gt["total"]          # faithful reading...
    assert not arithmetic_consistent(inv)            # ...and the inconsistency is visible


def test_tax_rate_is_captured(files):
    inv = extract_rules(text_of(files["classic.pdf"].path))
    assert inv.tax_rate is not None


def test_ocr_text_with_detached_colons():
    # real OCR output from a mildly degraded receipt scan
    text = ("WILLIAMS,    ALI AND BAILEY\n"
            "INV. NO.    : BD/26-27/4761    DT.    :    13 Apr 2026\n"
            "CUSTOMER: Thompson-Williams    eg    CURRENCY:    GBP\n"
            "INV. NO.    : 87847\n")
    inv = extract_rules(text)
    assert inv.invoice_number == "BD/26-27/4761"
    assert str(inv.invoice_date) == "2026-04-13"
    assert inv.customer_name == "Thompson-Williams"
    assert inv.currency == "GBP"


def test_ocr_text_with_split_label_and_name():
    text = ("BOONE    LLC\n"
            "INV.    NO.    :    BD/26-27/9294    DT.    :    July 8,    2026\n"
            "CUSTOMER:    Kylie Morales\n"
            "ITEM    QTY    RATE    AMOUNT\n")
    inv = extract_rules(text)
    assert inv.invoice_number == "BD/26-27/9294"
    assert inv.supplier_name == "BOONE LLC"
    assert str(inv.invoice_date) == "2026-07-08"
    assert inv.customer_name == "Kylie Morales"


def test_heading_without_colon_takes_value_from_below():
    text = "BILLED TO    DETAILS\nAmanda Lewis    Invoice # 86225\n"
    assert extract_rules(text).customer_name == "Amanda Lewis"
