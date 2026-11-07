"""Field-label vocabulary shared by the spreadsheet parser and the rules extractor.

These are the general phrases accounting documents use for each field, not
phrases copied from any one template. A label is matched after lower-casing
and removing punctuation, so "Invoice No.:" and "INVOICE NO" both match.
"""

from __future__ import annotations

import re

FIELD_LABELS: dict[str, list[str]] = {
    "invoice_number": ["invoice number", "invoice no", "invoice num", "invoice", "invoice id",
                       "inv no", "inv number", "inv", "bill no", "bill number", "document no",
                       "doc no", "reference number"],
    "invoice_date": ["invoice date", "date of issue", "issue date", "issued", "issued on",
                     "bill date", "inv date", "date", "dt", "dated"],
    "supplier_name": ["supplier", "supplier name", "vendor", "vendor name", "seller", "billed by",
                      "from", "company"],
    "customer_name": ["customer", "customer name", "bill to", "billed to", "client", "client name",
                      "buyer", "sold to", "invoice to", "ship to"],
    "currency": ["currency", "currency code", "curr"],
    "subtotal": ["subtotal", "sub total", "net", "net amount", "net total", "total charges",
                 "total before tax", "amount before tax", "taxable amount", "total excl vat",
                 "total excluding tax"],
    "tax": ["tax", "vat", "gst", "sales tax", "mwst", "tax amount", "vat amount", "ust"],
    "total": ["total", "grand total", "gross total", "gross", "amount due", "balance due",
              "total payable", "total due", "invoice total", "total amount", "amount payable",
              "total incl vat", "total including tax"],
}

COLUMN_LABELS: dict[str, list[str]] = {
    "description": ["description", "item", "item description", "items", "service", "services",
                    "particulars", "product", "details", "article"],
    "quantity": ["qty", "quantity", "hours", "units", "hours units", "no of units", "hrs", "pcs"],
    "unit_price": ["unit price", "rate", "price", "unit cost", "price per unit", "unit rate", "cost"],
    "amount": ["amount", "line amount", "line total", "value", "ext price", "extended price", "net value"],
}

# ledger exports repeat invoice fields as columns
LEDGER_COLUMNS: dict[str, list[str]] = {
    "invoice_number": FIELD_LABELS["invoice_number"],
    "invoice_date": FIELD_LABELS["invoice_date"],
    "supplier_name": FIELD_LABELS["supplier_name"],
    "customer_name": FIELD_LABELS["customer_name"],
    "currency": FIELD_LABELS["currency"],
    "description": ["item description"] + COLUMN_LABELS["description"],
    "quantity": COLUMN_LABELS["quantity"],
    "unit_price": COLUMN_LABELS["unit_price"],
    "amount": ["line amount", "line total", "amount"],
    "subtotal": FIELD_LABELS["subtotal"],
    "tax": FIELD_LABELS["tax"],
    "total": ["total", "invoice total", "grand total", "gross total", "total amount"],
}


def norm_label(s) -> str:
    s = re.sub(r"\(.*?\)", " ", str(s or "").lower())      # drop "(15%)"
    s = s.replace("#", " no ").replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def match_label(text, vocab: dict[str, list[str]], exact_only: bool = False) -> str | None:
    """Return the field whose label matches `text`, preferring the longest match."""
    t = norm_label(text)
    if not t:
        return None
    best, best_len = None, 0
    for fieldname, labels in vocab.items():
        for lab in labels:
            if t == lab and len(lab) > best_len:
                best, best_len = fieldname, len(lab) + 1000  # exact beats prefix
            elif not exact_only and (t.startswith(lab + " ")) and len(lab) > best_len and best_len < 1000:
                best, best_len = fieldname, len(lab)
    return best


def tax_rate_in(text: str):
    """'VAT (15%)' -> Decimal('15')."""
    from decimal import Decimal
    m = re.search(r"(\d{1,2}(?:[.,]\d{1,3})?)\s*%", str(text or ""))
    return Decimal(m.group(1).replace(",", ".")) if m else None
