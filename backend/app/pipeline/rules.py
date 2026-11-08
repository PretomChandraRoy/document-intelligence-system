"""Tier 1 extraction: deterministic rules over the page text.

The text arrives as lines in which a wide horizontal gap has been kept as
four spaces (see text.py), so a line splits into "segments" that correspond
to columns or to label/value pairs.

Rules used:
* A header field is a segment starting with a known label ("Invoice No:",
  "Amount Due"); its value is the rest of that segment, the next segment on
  the line, or the segment in the same column on the next line.
* A line item is a line ending in three numbers: quantity, unit price and
  amount. When quantity times price equals the amount, the row was almost
  certainly read correctly.
* The supplier is usually the first prominent name on the page, so the first
  line that is not a title, a label or an address is taken, with lower
  confidence.

The rules never guess: a field they cannot find stays None and the
language model is asked instead.
"""

from __future__ import annotations

import re
from decimal import Decimal

from .labels import COLUMN_LABELS, FIELD_LABELS, match_label, tax_rate_in
from .normalise import CENT, detect_currency, parse_date, parse_money, parse_quantity
from .schema import ExtractedInvoice, ExtractedLine, MONEY_FIELDS

SEG_SPLIT = re.compile(r"\s{3,}")
NUM_TOKEN = re.compile(r"^-?\(?\d[\d.,]*\)?$")
TITLES = {"invoice", "tax invoice", "statement of services", "statement", "bill", "receipt",
          "commercial invoice", "proforma invoice", "credit note"}
PERCENT = re.compile(r"\(?\s*\d{1,2}(?:[.,]\d{1,3})?\s*%\s*\)?")
CONTINUATION = re.compile(r"continued|page\s+\d+\s+of\s+\d+", re.I)


def _label_regex(label: str) -> re.Pattern:
    words = [re.escape(w) for w in label.split()]
    # allow punctuation between label words: "INV. NO. :" matches "inv no"
    body = r"[\s.:#/-]*".join(words)
    return re.compile(rf"^\s*{body}(?![a-z])[\s.:#-]*(?P<rest>.*)$", re.I)


_LABEL_PATTERNS = sorted(
    [(f, lab, _label_regex(lab)) for f, labs in FIELD_LABELS.items() for lab in labs],
    key=lambda t: -len(t[1]),
)


def split_segments(line: str) -> list[tuple[int, str]]:
    out, pos = [], 0
    for part in SEG_SPLIT.split(line):
        idx = line.find(part, pos)
        if part.strip():
            out.append((idx, part.strip()))
        pos = idx + len(part)
    return out


def _labelled(segment: str) -> tuple[str, str, str] | None:
    """('total', 'Amount Due', '$1,234.00') for 'Amount Due  $1,234.00'."""
    for field, lab, rx in _LABEL_PATTERNS:
        m = rx.match(segment)
        if m:
            return field, lab, m.group("rest").strip(" :#")
    return None


def _valid(field: str, value: str, currency: str | None):
    value = value.strip(" :;#.-")
    if not value:
        return None
    if field == "invoice_number":
        tok = value.split()[0].strip(" :#")
        return tok if re.search(r"\d", tok) and len(tok) <= 30 else None
    if field == "invoice_date":
        d, amb = parse_date(value, currency)
        return (d, amb) if d else None
    if field in MONEY_FIELDS:
        value = PERCENT.sub(" ", value)  # "(6.25%)" is a rate, not an amount
        if not re.search(r"\d", value):
            return None
        v = parse_money(value, decimal_comma=(currency == "EUR") or None)
        return v
    if field == "currency":
        return detect_currency(value) or (value.upper()[:3] if re.fullmatch(r"[A-Za-z]{3}", value) else None)
    if field in ("customer_name", "supplier_name"):
        if match_label(value, FIELD_LABELS) or len(value) < 2 or not re.search(r"[A-Za-z]", value):
            return None
        return value
    return value


def extract_rules(text: str, page_start: int | None = None, page_end: int | None = None) -> ExtractedInvoice:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    inv = ExtractedInvoice(method="rules", page_start=page_start, page_end=page_end)
    currency = detect_currency(text)

    found: dict[str, tuple] = {}
    for li, line in enumerate(lines):
        segs = split_segments(line)
        for si, (col, seg) in enumerate(segs):
            hit = _labelled(seg)
            if not hit:
                continue
            field, lab, rest = hit
            # OCR often separates the colon from both label and value
            # ("INV. NO.    :    87847"), so skip segments with no letters or digits
            after = [s for _, s in segs[si + 1:] if re.search(r"[A-Za-z0-9]", s)]
            if field in MONEY_FIELDS:
                # money: value is the rest of the segment or the last segment of the line
                candidates = [rest] + after[::-1]
            elif rest:
                candidates = [rest]
            elif after:
                # OCR can also split the label itself ("INV.    NO.    : 123"),
                # so look at the next two segments
                candidates = after[:2]
                if field == "invoice_date":
                    candidates.insert(0, " ".join(after[:3]))  # "July 8,    2026"
                # a label alone may have its value below it in the same column.
                # "Customer:" with a colon introduces a value on the same line;
                # a heading such as "BILLED TO" has its value underneath
                if li + 1 < len(lines):
                    below = [s for c, s in split_segments(lines[li + 1]) if abs(c - col) <= 6]
                    candidates = candidates + below if seg.rstrip().endswith(":") else below + candidates
            elif li + 1 < len(lines):
                candidates = [s for c, s in split_segments(lines[li + 1]) if abs(c - col) <= 6]
            else:
                candidates = []
            for cand in candidates:
                v = _valid(field, cand, currency)
                if v is None:
                    continue
                # totals: keep the last occurrence; header fields: the first
                if field in MONEY_FIELDS or field not in found:
                    found[field] = (v, line.strip(), seg)
                break

    for f, (v, evidence, seg) in found.items():
        if f == "invoice_date":
            d, amb = v
            inv.invoice_date = d
            inv.confidence[f] = 0.6 if amb else 0.9
        else:
            setattr(inv, f, v)
            inv.confidence[f] = 0.9
        inv.evidence[f] = evidence
        if f == "tax":
            inv.tax_rate = tax_rate_in(seg)

    if inv.currency is None and currency:
        inv.currency = currency
        inv.confidence["currency"] = 0.85
        inv.evidence["currency"] = next((ln for ln in lines if detect_currency(ln) == currency), "")

    if inv.supplier_name is None:
        sup = _supplier_guess(lines)
        if sup:
            inv.supplier_name, line = sup
            inv.confidence["supplier_name"] = 0.75
            inv.evidence["supplier_name"] = line

    inv.line_items = _line_items(lines, currency)
    if inv.line_items:
        inv.confidence["line_items"] = 0.9
    return inv


def _is_name_part(seg: str) -> bool:
    low = seg.lower().strip(" :")
    return not (low in TITLES or _labelled(seg) or re.search(r"\d", seg) or re.fullmatch(r"[-=_\s.,]+", seg))


def _supplier_guess(lines: list[str]) -> tuple[str, str] | None:
    for line in lines[:6]:
        segs = [s for _, s in split_segments(line)]
        if not segs or len(segs[0]) < 3 or not _is_name_part(segs[0]):
            continue
        # a wide gap inside a name ("BOONE    LLC") splits it; join the parts
        # until a title such as "INVOICE" or anything with digits
        parts = [segs[0]]
        for s in segs[1:]:
            if not _is_name_part(s):
                break
            parts.append(s)
        return " ".join(parts), line.strip()
    return None


def _line_items(lines: list[str], currency: str | None) -> list[ExtractedLine]:
    decimal_comma = currency == "EUR" or None
    items: list[ExtractedLine] = []
    in_table = False
    for line in lines:
        segs = [s for _, s in split_segments(line)]
        labels = {match_label(s, COLUMN_LABELS, exact_only=True) for s in segs}
        if {"description", "amount"} <= labels or {"description", "quantity"} <= labels:
            in_table = True
            continue
        if not in_table:
            continue
        hit = _labelled(segs[0]) if segs else None
        if hit and hit[0] in MONEY_FIELDS:
            in_table = False  # totals block reached
            continue
        if CONTINUATION.search(line):
            continue
        row = _parse_row(line, decimal_comma)
        if row:
            items.append(row)
    return items


def _parse_row(line: str, decimal_comma) -> ExtractedLine | None:
    tokens = line.split()
    nums = []
    while tokens and NUM_TOKEN.match(tokens[-1]) and len(nums) < 3:
        nums.insert(0, tokens.pop())
    if len(nums) < 3 or not tokens:
        return None
    desc = " ".join(tokens).strip()
    qty = parse_quantity(nums[0], decimal_comma)
    price = parse_money(nums[1], decimal_comma)
    amount = parse_money(nums[2], decimal_comma)
    if qty is None or price is None or amount is None:
        return None
    return ExtractedLine(desc, qty, price, amount)


def arithmetic_consistent(inv: ExtractedInvoice) -> bool:
    """Do the numbers agree with each other? Used to decide if rules can be trusted."""
    if inv.total is None:
        return False
    if inv.subtotal is not None:
        if abs(inv.subtotal + (inv.tax or Decimal("0")) - inv.total) > CENT:
            return False
        if inv.line_items:
            if any(li.amount is None for li in inv.line_items):
                return False
            if abs(sum(li.amount for li in inv.line_items) - inv.subtotal) > CENT:
                return False
    elif inv.line_items:
        if abs(sum(li.amount or 0 for li in inv.line_items) + (inv.tax or 0) - inv.total) > CENT:
            return False
    for li in inv.line_items:
        if li.quantity is not None and li.unit_price is not None and li.amount is not None:
            if abs((li.quantity * li.unit_price).quantize(CENT) - li.amount) > CENT:
                return False
    return True
