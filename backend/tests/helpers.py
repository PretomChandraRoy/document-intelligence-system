"""Comparison helpers shared by the tests."""
import re
from decimal import Decimal


def same(field, got, want):
    if got is None or want is None:
        return got == want
    if field in ("subtotal", "tax", "total"):
        return Decimal(str(got)) == Decimal(want)
    if field in ("supplier_name", "customer_name"):
        return " ".join(str(got).lower().split()) == " ".join(want.lower().split())
    return str(got) == str(want)


def mismatches(extracted: dict, truth: dict) -> list[str]:
    bad = [f for f in ("invoice_number", "invoice_date", "supplier_name", "customer_name",
                       "subtotal", "tax", "total", "currency") if not same(f, extracted.get(f), truth.get(f))]
    a, b = extracted.get("line_items") or [], truth.get("line_items") or []
    if len(a) != len(b) or any(Decimal(str(x["amount"])) != Decimal(y["amount"]) for x, y in zip(a, b)):
        bad.append("line_items")
    return bad


def norm(s):
    return re.sub(r"[^0-9a-z]", "", (s or "").lower())
