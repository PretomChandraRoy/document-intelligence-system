"""Validation rules."""
from datetime import date
from decimal import Decimal as D

from app.pipeline.schema import ExtractedInvoice, ExtractedLine
from app.pipeline.validate import review_status, validate


def good(**kw):
    base = dict(invoice_number="INV-1", invoice_date=date(2026, 3, 1), supplier_name="Acme", customer_name="Bob",
                subtotal=D("100.00"), tax=D("15.00"), total=D("115.00"), currency="BDT",
                line_items=[ExtractedLine("A", D("2"), D("25.00"), D("50.00")),
                            ExtractedLine("B", D("1"), D("50.00"), D("50.00"))])
    base.update(kw)
    return ExtractedInvoice(**base)


def codes(inv, **kw):
    return sorted(i["code"] for i in validate(inv, today=date(2026, 11, 1), **kw))


def test_clean_invoice_passes():
    issues = validate(good(), today=date(2026, 11, 1))
    assert issues == [] and review_status(issues) == "auto_approved"


def test_missing_fields():
    issues = validate(good(customer_name=None, invoice_date=None), today=date(2026, 11, 1))
    assert {(i["code"], i["field"]) for i in issues} == {("missing_field", "customer_name"),
                                                         ("missing_field", "invoice_date")}
    assert review_status(issues) == "needs_review"


def test_total_mismatch():
    issues = validate(good(total=D("120.00")), today=date(2026, 11, 1))
    t = next(i for i in issues if i["code"] == "total_mismatch")
    assert t["severity"] == "error" and t["details"]["difference"] == "5.00"


def test_line_items_do_not_add_up():
    assert "line_items_mismatch" in codes(good(subtotal=D("90.00"), total=D("105.00")))


def test_line_amount_is_not_quantity_times_price():
    inv = good(line_items=[ExtractedLine("A", D("2"), D("25.00"), D("60.00")),
                           ExtractedLine("B", D("1"), D("40.00"), D("40.00"))])
    assert "line_amount_mismatch" in codes(inv)


def test_tax_rate_mismatch():
    assert "tax_rate_mismatch" in codes(good(), tax_rate=D("10"))
    assert "tax_rate_mismatch" not in codes(good(), tax_rate=D("15"))


def test_implausible_values():
    assert "implausible_value" in codes(good(invoice_date=date(2030, 1, 1)))
    assert "implausible_value" in codes(good(subtotal=D("-100.00"), total=D("-85.00"),
                                              line_items=[]))


def test_no_tax_line_is_allowed():
    assert codes(good(tax=None, total=D("100.00"))) == []


def test_low_confidence_flagged():
    assert "low_confidence" in codes(good(), confidence={"total": 0.4})


def test_model_warnings_become_issues():
    w = [{"code": "ungrounded_value", "field": "supplier_name", "message": "discarded"}]
    assert "ungrounded_value" in codes(good(), warnings=w)
