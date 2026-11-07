"""Money, quantity, date and currency parsing across regional formats."""
from datetime import date
from decimal import Decimal

import pytest

from app.pipeline.normalise import detect_currency, money_variants, parse_date, parse_money, parse_quantity


@pytest.mark.parametrize("raw,expected", [
    ("Tk 1,23,456.00", "123456.00"),     # Bangladeshi lakh grouping
    ("1.234,56 €", "1234.56"),           # European decimal comma
    ("$1,519.12", "1519.12"),
    ("USD 7,60,995.73", "760995.73"),
    ("(12.50)", "-12.50"),               # accounting negative
    ("-3.00", "-3.00"),
    ("105,40", "105.40"),
    (1519.12, "1519.12"),                # native spreadsheet number
])
def test_parse_money(raw, expected):
    assert parse_money(raw) == Decimal(expected)


def test_decimal_comma_hint():
    assert parse_money("1.234", decimal_comma=True) == Decimal("1234.00")
    assert parse_quantity("37,5", decimal_comma=True) == Decimal("37.5")


def test_no_number():
    assert parse_money("Total") is None
    assert parse_money(None) is None


@pytest.mark.parametrize("raw,hint,expected,ambiguous", [
    ("2026-02-01", None, date(2026, 2, 1), False),
    ("26 Jun 2026", None, date(2026, 6, 26), False),
    ("November 7, 2026", None, date(2026, 11, 7), False),
    ("25/01/2026", "USD", date(2026, 1, 25), False),   # 25 cannot be a month
    ("07/11/2026", "BDT", date(2026, 11, 7), True),    # day first in Bangladesh
    ("11/07/2026", "USD", date(2026, 11, 7), True),    # month first in the US
    ("09.03.2026", None, date(2026, 3, 9), False),     # dotted dates are European
    ("Issued: 06 Jun 2026", None, date(2026, 6, 6), False),
])
def test_parse_date(raw, hint, expected, ambiguous):
    assert parse_date(raw, hint) == (expected, ambiguous)


def test_invalid_date():
    assert parse_date("31/02/2026", "BDT") == (None, False)
    assert parse_date("no date here") == (None, False)


@pytest.mark.parametrize("text,code", [
    ("Total BDT 1,000", "BDT"), ("Tk. 500", "BDT"), ("€ 5", "EUR"), ("£12", "GBP"),
    ("US$5", "USD"), ("TOTAL 5", None),
])
def test_detect_currency(text, code):
    assert detect_currency(text) == code


def test_money_variants_cover_print_styles():
    v = money_variants(Decimal("123456.00"))
    assert {"1,23,456.00", "123,456.00", "123.456,00", "123456.00"} <= set(v)
