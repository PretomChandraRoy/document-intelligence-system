"""Stage 4b: find the same invoice in other documents and compare them.

A duplicate (submitted twice) and a cross-verification pair (a PDF and its
spreadsheet record) are the same situation: two documents describing one
invoice. Both are found with a match key, then compared field by field.
"""

from __future__ import annotations

import re
from decimal import Decimal

LEGAL_SUFFIXES = {"ltd", "limited", "llc", "inc", "co", "company", "corp", "corporation", "plc",
                  "gmbh", "ag", "kg", "ev", "sa", "bv", "pvt", "private", "the", "and"}
COMPARE_FIELDS = ("invoice_number", "invoice_date", "supplier_name", "customer_name",
                  "subtotal", "tax", "total", "currency")


def norm_supplier(name: str | None) -> str | None:
    if not name:
        return None
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower().replace("&", " and ")).split()
    words = [w for w in words if w not in LEGAL_SUFFIXES]
    return " ".join(words) or None


def norm_number(num: str | None) -> str | None:
    if not num:
        return None
    # INV-0042 and inv 42 are the same number: drop separators and leading zeros of digit runs
    s = re.sub(r"(?<!\d)0+(?=\d)", "", re.sub(r"[^A-Z0-9]", "", num.upper()))
    return s or None


def dedupe_key(supplier: str | None, number: str | None) -> str | None:
    s, n = norm_supplier(supplier), norm_number(number)
    return f"{s}|{n}" if s and n else None


def _norm_value(field: str, v):
    if v is None:
        return None
    if field in ("supplier_name",):
        return norm_supplier(v)
    if field == "customer_name":
        return " ".join(re.sub(r"[^a-z0-9 ]", " ", v.lower()).split())
    if field == "invoice_number":
        return norm_number(v)
    if isinstance(v, Decimal):
        return v.quantize(Decimal("0.01"))
    return v


def compare(invoices: list) -> tuple[list[str], list[dict]]:
    """Return (mismatched_fields, comparison rows) for objects with invoice attributes."""
    rows, mismatched = [], []
    for f in COMPARE_FIELDS:
        vals = [getattr(i, f) for i in invoices]
        normed = {_norm_value(f, v) for v in vals}
        match = len(normed) == 1
        rows.append({"field": f, "values": [None if v is None else str(v) for v in vals], "match": match})
        if not match:
            mismatched.append(f)

    def lines_of(inv):
        return [(_norm_desc(li.description), _q(li.quantity), _m(li.unit_price), _m(li.amount))
                for li in inv.line_items]
    sets = [lines_of(i) for i in invoices]
    li_match = all(s == sets[0] for s in sets[1:])
    rows.append({"field": "line_items",
                 "values": [f"{len(s)} items, sum {sum((x[3] or 0) for x in s)}" for s in sets],
                 "match": li_match})
    if not li_match:
        mismatched.append("line_items")
    return mismatched, rows


def _norm_desc(s):
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split())


def _q(v):
    return None if v is None else Decimal(v).normalize()


def _m(v):
    return None if v is None else Decimal(v).quantize(Decimal("0.01"))
