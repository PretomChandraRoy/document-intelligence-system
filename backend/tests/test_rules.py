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
