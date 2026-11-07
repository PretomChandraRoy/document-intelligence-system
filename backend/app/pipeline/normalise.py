"""Turn printed text into typed values: money, quantities, dates, currencies.

Printed formats vary by country:
    1,234.56     US and UK
    1,23,456.00  Bangladesh and India (lakh grouping)
    1.234,56     much of Europe
Dates are day-first in Bangladesh, the UK and Europe, month-first in the US.
When a date such as 04/05/2026 could be read either way, the currency is
used as a hint and the result is marked ambiguous so its confidence drops.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CENT = Decimal("0.01")

CURRENCY_SYMBOLS = [
    # longest first so "US$" wins over "$"
    ("US$", "USD"), ("USD", "USD"), ("$", "USD"),
    ("GBP", "GBP"), ("£", "GBP"),
    ("EUR", "EUR"), ("€", "EUR"),
    ("BDT", "BDT"), ("Tk.", "BDT"), ("Tk", "BDT"), ("TK", "BDT"), ("৳", "BDT"), ("Taka", "BDT"),
    ("INR", "INR"), ("₹", "INR"),
]
DAY_FIRST_CURRENCIES = {"BDT", "GBP", "EUR", "INR"}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

_MONEY_RE = re.compile(r"[-(]?\d[\d.,\s]*\d\)?|\d")


def detect_currency(text: str) -> str | None:
    """Find the first currency marker in a piece of text."""
    if not text:
        return None
    for sym, code in CURRENCY_SYMBOLS:
        if sym.isalpha() or sym.endswith("."):
            if re.search(rf"(?<![A-Za-z]){re.escape(sym)}(?![A-Za-z])", text):
                return code
        elif sym in text:
            return code
    return None


def parse_money(raw, decimal_comma: bool | None = None) -> Decimal | None:
    """'Tk 1,23,456.00' -> Decimal('123456.00'); '1.234,56 €' -> Decimal('1234.56')."""
    if raw is None:
        return None
    if isinstance(raw, (int, float, Decimal)):
        return Decimal(str(raw)).quantize(CENT, rounding=ROUND_HALF_UP)
    s = str(raw)
    m = _MONEY_RE.search(s.replace(" ", " "))
    if not m:
        return None
    num = m.group(0)
    negative = num.startswith("-") or (num.startswith("(") and num.endswith(")"))
    num = re.sub(r"[^\d.,]", "", num)
    value = _to_decimal(num, decimal_comma)
    if value is None:
        return None
    if negative:
        value = -value
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def parse_quantity(raw, decimal_comma: bool | None = None) -> Decimal | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float, Decimal)):
        return Decimal(str(raw)).normalize()
    num = re.sub(r"[^\d.,]", "", str(raw))
    value = _to_decimal(num, decimal_comma)
    return value.normalize() if value is not None else None


def _to_decimal(num: str, decimal_comma: bool | None) -> Decimal | None:
    if not num or not any(c.isdigit() for c in num):
        return None
    # OCR often reads a thousands comma as a dot ("4,97.200.00"): when the
    # last separator is followed by exactly two digits, it is the decimal point
    last = max(num.rfind("."), num.rfind(","))
    if last != -1 and len(num) - last - 1 == 2 and (num.count(".") + num.count(",")) > 1:
        return _safe_decimal(re.sub(r"[.,]", "", num[:last]) + "." + num[last + 1:])
    has_dot, has_comma = "." in num, "," in num
    if has_dot and has_comma:
        # whichever separator comes last is the decimal point
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif has_comma:
        parts = num.split(",")
        if decimal_comma or (decimal_comma is None and len(parts) == 2 and len(parts[1]) in (1, 2)):
            num = num.replace(",", ".")
        else:
            num = num.replace(",", "")
    elif has_dot:
        parts = num.split(".")
        if len(parts) > 2 or (decimal_comma and len(parts[1]) == 3):
            num = num.replace(".", "")  # dots are thousands separators
    try:
        return Decimal(num)
    except InvalidOperation:
        return None


def _safe_decimal(s: str) -> Decimal | None:
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_date(raw, currency_hint: str | None = None) -> tuple[date | None, bool]:
    """Return (date, ambiguous). ambiguous is True when day and month could swap."""
    if raw is None:
        return None, False
    if isinstance(raw, datetime):
        return raw.date(), False
    if isinstance(raw, date):
        return raw, False
    s = str(raw).strip()

    m = re.search(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", s)  # ISO, year first
    if m:
        return _safe(int(m[1]), int(m[2]), int(m[3])), False

    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s.-]*([A-Za-z]{3,9})\.?,?[\s.-]*(\d{4})\b", s)
    if m and m[2][:3].lower() in MONTHS:
        return _safe(int(m[3]), MONTHS[m[2][:3].lower()], int(m[1])), False

    m = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", s)
    if m and m[1][:3].lower() in MONTHS:
        return _safe(int(m[3]), MONTHS[m[1][:3].lower()], int(m[2])), False

    m = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\b", s)
    if m:
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        if y < 100:
            y += 2000
        sep = s[m.start(2) - 1]
        if a > 12 and b <= 12:
            return _safe(y, b, a), False
        if b > 12 and a <= 12:
            return _safe(y, a, b), False
        # both could be a month: decide by separator and currency
        if sep == ".":
            day_first = True  # dotted dates are European
        elif currency_hint:
            day_first = currency_hint in DAY_FIRST_CURRENCIES
        else:
            day_first = True
        d = _safe(y, b, a) if day_first else _safe(y, a, b)
        return d, a != b and sep != "."
    return None, False


def _safe(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def money_variants(value: Decimal) -> list[str]:
    """Printed forms of an amount, used to check a value appears in the source text."""
    q = abs(value).quantize(CENT)
    whole, frac = f"{q:f}".split(".")
    plain = f"{int(whole)}.{frac}"
    us = f"{int(whole):,}.{frac}"
    eu = f"{int(whole):,}".replace(",", ".") + "," + frac
    indian = whole
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        indian = ",".join(groups + [tail])
    indian = f"{indian}.{frac}"
    out = {plain, us, eu, indian}
    if frac == "00":
        out |= {str(int(whole)), f"{int(whole):,}"}
    return sorted(out, key=len, reverse=True)


def norm_text(s: str | None) -> str:
    """Lower-case letters and digits only, for tolerant text matching."""
    return re.sub(r"[^0-9a-z]", "", (s or "").lower())
