"""Stage 4a: validation rules.

Works on anything with the invoice attributes (an ExtractedInvoice or the
database Invoice), so the same rules run after extraction and again after a
manual correction.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from .schema import REQUIRED_FIELDS

CENT = Decimal("0.01")
LABELS = {"invoice_number": "invoice number", "invoice_date": "invoice date",
          "supplier_name": "supplier name", "customer_name": "customer name",
          "subtotal": "subtotal", "tax": "tax", "total": "total", "currency": "currency"}


def issue(code, severity, field, message, **details) -> dict:
    return {"code": code, "severity": severity, "field": field, "message": message,
            "details": {k: (str(v) if isinstance(v, (Decimal, date)) else v) for k, v in details.items()}}


def validate(inv, *, confidence: dict | None = None, warnings: list[dict] | None = None,
             tax_rate: Decimal | None = None, low_confidence: float = 0.6,
             today: date | None = None) -> list[dict]:
    today = today or date.today()
    out: list[dict] = []
    lines = list(inv.line_items or [])

    for f in REQUIRED_FIELDS:
        if getattr(inv, f) in (None, ""):
            out.append(issue("missing_field", "error", f, f"The {LABELS[f]} is not on the document"))

    sub, tax, total = inv.subtotal, inv.tax, inv.total
    if sub is not None and total is not None:
        expected = sub + (tax or Decimal("0"))
        if abs(expected - total) > CENT:
            out.append(issue("total_mismatch", "error", "total",
                             f"Subtotal {sub} plus tax {tax or 0} is {expected}, but the total says {total}",
                             expected=expected, found=total, difference=total - expected))
    if lines and sub is not None and all(li.amount is not None for li in lines):
        s = sum(li.amount for li in lines)
        if abs(s - sub) > CENT:
            out.append(issue("line_items_mismatch", "error", "subtotal",
                             f"The {len(lines)} line items add up to {s}, but the subtotal says {sub}",
                             expected=s, found=sub, difference=sub - s))
    elif lines and sub is None and total is not None and all(li.amount is not None for li in lines):
        s = sum(li.amount for li in lines) + (tax or Decimal("0"))
        if abs(s - total) > CENT:
            out.append(issue("line_items_mismatch", "error", "total",
                             f"The line items plus tax add up to {s}, but the total says {total}",
                             expected=s, found=total))
    for i, li in enumerate(lines):
        if li.quantity is not None and li.unit_price is not None and li.amount is not None:
            exp = (Decimal(li.quantity) * Decimal(li.unit_price)).quantize(CENT)
            if abs(exp - li.amount) > CENT:
                out.append(issue("line_amount_mismatch", "warning", f"line_items[{i}].amount",
                                 f"Line {i + 1}: {li.quantity} x {li.unit_price} is {exp}, but the amount says {li.amount}",
                                 expected=exp, found=li.amount))
    if tax_rate is not None and sub is not None and tax is not None:
        exp = (sub * tax_rate / 100).quantize(CENT)
        if abs(exp - tax) > CENT:
            out.append(issue("tax_rate_mismatch", "warning", "tax",
                             f"{tax_rate}% of {sub} is {exp}, but the tax says {tax}", expected=exp, found=tax))

    for f in ("subtotal", "tax", "total"):
        v = getattr(inv, f)
        if v is not None and v < 0:
            out.append(issue("implausible_value", "warning", f, f"The {LABELS[f]} is negative ({v})"))
        if v is not None and abs(v) >= Decimal("1000000000"):
            out.append(issue("implausible_value", "warning", f, f"The {LABELS[f]} is unusually large ({v})"))
    d = inv.invoice_date
    if d is not None and (d > today + timedelta(days=1) or d.year < 2000):
        out.append(issue("implausible_value", "warning", "invoice_date", f"The invoice date {d} is implausible"))

    for w in warnings or []:
        out.append(issue(w["code"], "warning", w.get("field"), w["message"], **(w.get("details") or {})))

    flagged = {i["field"] for i in out}
    for f, c in (confidence or {}).items():
        if c < low_confidence and f not in flagged and (f == "line_items" or getattr(inv, f, None) is not None):
            out.append(issue("low_confidence", "warning", f,
                             f"The {LABELS.get(f, f.replace('_', ' '))} was read with low confidence ({c:.0%}); please check",
                             confidence=c))
    return out


def review_status(issues: list[dict]) -> str:
    return "needs_review" if any(i["severity"] in ("error", "warning") for i in issues) else "auto_approved"
