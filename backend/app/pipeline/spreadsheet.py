"""Read invoices out of spreadsheet tables without a language model.

Two layouts cover most accounting exports:

* Ledger: a header row of column names, then one row per line item, with
  the invoice fields repeated on every row. Rows are grouped by invoice
  number, so one file can hold many invoices.
* Form: label cells ("Invoice No", "Vendor", "Gross Total") with the value
  in the next cell to the right, plus an items table. The labels and the
  table may be spread over several sheets.

Numbers and dates stored as real spreadsheet cells are taken as they are;
only text cells need parsing. Anything that matches neither layout is left
for the language model (see extract.py).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from .ingest import PageData
from .labels import COLUMN_LABELS, FIELD_LABELS, LEDGER_COLUMNS, match_label, norm_label, tax_rate_in
from .normalise import detect_currency, parse_date, parse_money, parse_quantity
from .schema import ExtractedInvoice, ExtractedLine, MONEY_FIELDS

NATIVE = 0.99   # value came from a typed cell
PARSED = 0.95   # value parsed from a text cell
AMBIGUOUS_DATE = 0.6


def parse_workbook(pages: list[PageData]) -> list[ExtractedInvoice]:
    decimal_comma = any(p.table and p.table[0] == ["__decimal_comma__"] for p in pages)
    tables = [(p.sheet_name, [r for r in p.table if r != ["__decimal_comma__"]]) for p in pages if p.table]

    invoices: list[ExtractedInvoice] = []
    form_tables = []
    for name, rows in tables:
        ledger = _ledger(name, rows, decimal_comma)
        if ledger is not None:
            invoices.extend(ledger)
        else:
            form_tables.append((name, rows))
    if form_tables:
        inv = _form(form_tables, decimal_comma)
        if inv is not None:
            invoices.append(inv)
    return invoices


# -- helpers ------------------------------------------------------------------
def _is_text(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def _money(v, decimal_comma):
    if v is None or v == "":
        return None, None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return parse_money(v), NATIVE
    return parse_money(v, decimal_comma), PARSED


def _qty(v, decimal_comma):
    if v is None or v == "":
        return None
    return parse_quantity(v, decimal_comma if isinstance(v, str) else None)


def _date(v, currency):
    if v is None or v == "":
        return None, None
    if isinstance(v, (datetime, date)):
        d, _ = parse_date(v)
        return d, NATIVE
    d, ambiguous = parse_date(str(v), currency)
    return d, (AMBIGUOUS_DATE if ambiguous else PARSED) if d else None


def _text(v):
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)  # invoice numbers stored as numbers, e.g. 58213.0
    s = str(v).strip()
    return s or None


# -- ledger layout --------------------------------------------------------------
def _ledger(sheet: str, rows: list[list], decimal_comma: bool) -> list[ExtractedInvoice] | None:
    for hi, row in enumerate(rows[:10]):
        cols = {}
        for ci, cell in enumerate(row):
            if _is_text(cell):
                f = match_label(cell, LEDGER_COLUMNS, exact_only=True)
                if f and f not in cols:
                    cols[f] = ci
        if "invoice_number" in cols and ("amount" in cols or "total" in cols) and len(cols) >= 4:
            break
    else:
        return None

    groups: dict[str, list[tuple[int, list]]] = {}
    order: list[str] = []
    current = None
    for ri, row in enumerate(rows[hi + 1:], start=hi + 2):
        num = _text(row[cols["invoice_number"]]) if cols["invoice_number"] < len(row) else None
        if num:
            current = num
        if current is None:
            continue
        if current not in groups:
            groups[current] = []
            order.append(current)
        groups[current].append((ri, row))

    def cell(row, f):
        i = cols.get(f)
        return row[i] if i is not None and i < len(row) else None

    out = []
    for num in order:
        members = groups[num]
        first_ri, first = members[0]
        inv = ExtractedInvoice(method="spreadsheet", sheet_name=sheet, invoice_number=num)
        inv.confidence["invoice_number"] = NATIVE
        inv.evidence["invoice_number"] = f"{sheet} row {first_ri}"
        for f in ("supplier_name", "customer_name"):
            v = _text(cell(first, f))
            if v:
                setattr(inv, f, v)
                inv.confidence[f] = NATIVE
                inv.evidence[f] = f"{sheet} row {first_ri}: {v}"
        cur = _text(cell(first, "currency"))
        if cur:
            inv.currency = detect_currency(cur) or (cur.upper() if len(cur) == 3 else None)
            inv.confidence["currency"] = NATIVE
        d, c = _date(cell(first, "invoice_date"), inv.currency)
        if d:
            inv.invoice_date, inv.confidence["invoice_date"] = d, c
        for f in MONEY_FIELDS:
            v, c = _money(cell(first, f), decimal_comma)
            if v is not None:
                setattr(inv, f, v)
                inv.confidence[f] = c
                inv.evidence[f] = f"{sheet} row {first_ri}: {cell(first, f)}"
        for ri, row in members:
            desc = _text(cell(row, "description"))
            amt, _ = _money(cell(row, "amount"), decimal_comma)
            if desc is None and amt is None:
                continue
            price, _ = _money(cell(row, "unit_price"), decimal_comma)
            inv.line_items.append(ExtractedLine(desc, _qty(cell(row, "quantity"), decimal_comma), price, amt))
        out.append(inv)
    return out


# -- form layout ----------------------------------------------------------------
def _form(tables: list[tuple[str, list[list]]], decimal_comma: bool) -> ExtractedInvoice | None:
    inv = ExtractedInvoice(method="spreadsheet")
    found = False
    raw: dict[str, tuple] = {}

    for sheet, rows in tables:
        header_at = None
        for ri, row in enumerate(rows):
            # items table header?
            cols = {}
            for ci, cell in enumerate(row):
                if _is_text(cell):
                    f = match_label(cell, COLUMN_LABELS, exact_only=True)
                    if f and f not in cols:
                        cols[f] = ci
            if "description" in cols and "amount" in cols and header_at is None:
                header_at = ri
                items_cols = cols
                inv.sheet_name = inv.sheet_name or sheet
                continue
            if header_at is not None and ri > header_at and not _label_row(row):
                desc = _text(row[items_cols["description"]]) if items_cols["description"] < len(row) else None
                amt_cell = row[items_cols["amount"]] if items_cols["amount"] < len(row) else None
                if desc is None and amt_cell in (None, ""):
                    if inv.line_items:
                        header_at = -1  # blank row ends the table
                    continue
                if header_at != -1 and desc:
                    g = lambda f: row[items_cols[f]] if f in items_cols and items_cols[f] < len(row) else None
                    inv.line_items.append(ExtractedLine(
                        desc, _qty(g("quantity"), decimal_comma),
                        _money(g("unit_price"), decimal_comma)[0], _money(amt_cell, decimal_comma)[0]))
                    continue
            # label / value pairs
            for ci, cell in enumerate(row):
                if not _is_text(cell):
                    continue
                f = match_label(cell, FIELD_LABELS, exact_only=True)
                if not f or f in raw:
                    continue
                value = next((v for v in row[ci + 1:] if v not in (None, "")), None)
                if value is None:
                    continue
                raw[f] = (value, f"{sheet} row {ri + 1}: {cell} = {value}", cell)
                found = True

    if not found and not inv.line_items:
        return None

    for f in ("invoice_number", "supplier_name", "customer_name"):
        if f in raw:
            setattr(inv, f, _text(raw[f][0]))
            inv.confidence[f] = NATIVE
            inv.evidence[f] = raw[f][1]
    if "currency" in raw:
        cur = _text(raw["currency"][0])
        inv.currency = detect_currency(cur) or (cur.upper() if cur and len(cur) == 3 else None)
        inv.confidence["currency"] = NATIVE
    if "invoice_date" in raw:
        d, c = _date(raw["invoice_date"][0], inv.currency)
        if d:
            inv.invoice_date, inv.confidence["invoice_date"] = d, c
            inv.evidence["invoice_date"] = raw["invoice_date"][1]
    for f in MONEY_FIELDS:
        if f in raw:
            v, c = _money(raw[f][0], decimal_comma)
            if v is not None:
                setattr(inv, f, v)
                inv.confidence[f] = c
                inv.evidence[f] = raw[f][1]
    if "tax" in raw:
        inv.tax_rate = tax_rate_in(raw["tax"][2])
    return inv


def _label_row(row: list) -> bool:
    """A totals row such as ['', '', 'Subtotal', 1080.22]."""
    texts = [c for c in row if _is_text(c)]
    return len(texts) == 1 and match_label(texts[0], FIELD_LABELS, exact_only=True) in MONEY_FIELDS
