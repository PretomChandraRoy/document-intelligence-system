"""The internal result type every extractor produces, whatever its method."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

HEADER_FIELDS = ("invoice_number", "invoice_date", "supplier_name", "customer_name",
                 "subtotal", "tax", "total", "currency")
REQUIRED_FIELDS = ("invoice_number", "invoice_date", "supplier_name", "customer_name",
                   "total", "currency")
MONEY_FIELDS = ("subtotal", "tax", "total")


@dataclass
class ExtractedLine:
    description: str | None
    quantity: Decimal | None
    unit_price: Decimal | None
    amount: Decimal | None


@dataclass
class ExtractedInvoice:
    invoice_number: str | None = None
    invoice_date: date | None = None
    supplier_name: str | None = None
    customer_name: str | None = None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    currency: str | None = None
    line_items: list[ExtractedLine] = field(default_factory=list)

    method: str = "rules"  # spreadsheet | rules | llm | manual
    confidence: dict[str, float] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)
    warnings: list[dict] = field(default_factory=list)  # e.g. ungrounded values
    tax_rate: Decimal | None = None  # printed rate, if any (for the tax-rate rule)
    raw_model_output: dict | None = None

    page_start: int | None = None
    page_end: int | None = None
    sheet_name: str | None = None

    def missing(self) -> list[str]:
        return [f for f in REQUIRED_FIELDS if getattr(self, f) in (None, "")]

    def as_dict(self) -> dict:
        def s(v):
            if v is None:
                return None
            return v.isoformat() if isinstance(v, date) else str(v)
        out = {f: s(getattr(self, f)) for f in HEADER_FIELDS}
        out["line_items"] = [{"description": li.description, "quantity": s(li.quantity),
                              "unit_price": s(li.unit_price), "amount": s(li.amount)}
                             for li in self.line_items]
        return out
