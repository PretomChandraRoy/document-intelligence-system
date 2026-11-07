"""Synthetic invoice model and random generation.

Every value is generated first as data (the ground truth), then rendered
into a document. All money arithmetic uses Decimal so that the labels are
exact to the cent, the same way an accounting system would store them.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from faker import Faker

CENT = Decimal("0.01")


def money(x) -> Decimal:
    return Decimal(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Locales: each one fixes the currency, tax regime and the formatting habits
# a real document from that market would use. Formatting variety is what
# makes extraction hard, so it is deliberate.
# ---------------------------------------------------------------------------
LOCALES = {
    "bd": {
        "currency": "BDT",
        "symbols": ["Tk", "BDT", "Tk."],
        "date_styles": ["dmy_slash", "d_mon_y", "dmy_dash"],
        "money_styles": ["indian", "us"],
        "tax_rates": [Decimal("15"), Decimal("7.5"), Decimal("5")],
        "tax_labels": ["VAT", "VAT", "Tax"],
    },
    "us": {
        "currency": "USD",
        "symbols": ["$", "USD", "US$"],
        "date_styles": ["mdy_slash", "month_d_y", "iso"],
        "money_styles": ["us"],
        "tax_rates": [Decimal("0"), Decimal("6.25"), Decimal("8.875"), Decimal("7")],
        "tax_labels": ["Sales Tax", "Tax"],
    },
    "uk": {
        "currency": "GBP",
        "symbols": ["£", "GBP"],
        "date_styles": ["dmy_slash", "d_mon_y"],
        "money_styles": ["us"],
        "tax_rates": [Decimal("20")],
        "tax_labels": ["VAT"],
    },
    "eu": {
        "currency": "EUR",
        "symbols": ["€", "EUR"],
        "date_styles": ["dmy_dot", "d_mon_y"],
        "money_styles": ["eu", "us"],
        "tax_rates": [Decimal("19"), Decimal("21")],
        "tax_labels": ["VAT", "MwSt."],
    },
    "homecare": {
        "currency": "USD",
        "symbols": ["$", "USD"],
        "date_styles": ["mdy_slash", "month_d_y"],
        "money_styles": ["us"],
        "tax_rates": [Decimal("0")],
        "tax_labels": ["Tax"],
    },
}

BD_PREFIX = ["Rahman", "Karim", "Padma", "Meghna", "Jamuna", "Sonali", "Bengal",
             "Delta", "Green Valley", "Riverside", "Shapla", "Golden Harvest",
             "Lalbagh", "Sundarban", "Teesta", "Rupsha", "Chittagong Port",
             "Northern", "Dhanmondi", "Banani"]
BD_SUFFIX = ["Traders", "Enterprise", "Trading Co.", "Supplies Ltd.",
             "Technologies Ltd.", "Logistics", "Printing & Packaging",
             "Office Solutions", "Engineering Works", "Distributors"]
BD_PEOPLE = ["Md. Arifur Rahman", "Nusrat Jahan", "Tanvir Ahmed", "Farhana Akter",
             "Sabbir Hossain", "Mehedi Hasan", "Sharmin Sultana", "Rakibul Islam",
             "Anika Tabassum", "Shafiqul Alam", "Jannatul Ferdous", "Imran Kabir"]

ITEMS = {
    "general": [
        ("A4 Paper 80gsm (ream)", 4, 12), ("Laser Toner Cartridge", 40, 120),
        ("Ergonomic Office Chair", 90, 320), ("Wireless Keyboard and Mouse Set", 18, 60),
        ("27-inch LED Monitor", 140, 380), ("Network Switch 24-port", 120, 420),
        ("Cat6 Ethernet Cable (305 m box)", 70, 160), ("Software Licence (annual)", 80, 900),
        ("IT Support Services (hours)", 25, 95), ("Website Maintenance (monthly)", 150, 700),
        ("Courier Delivery Charge", 5, 40), ("Printed Brochures (pack of 100)", 30, 110),
        ("Cleaning Services (monthly)", 120, 600), ("Bottled Water 19L", 2, 8),
        ("Stationery Bundle", 10, 45), ("Data Entry Services (batch)", 60, 250),
        ("Cloud Hosting (monthly)", 30, 400), ("UPS 1200VA", 80, 210),
        ("Filing Cabinet, 4 drawer", 110, 290), ("Training Workshop (per seat)", 50, 300),
    ],
    "homecare": [
        ("Personal Care Aide services", 22, 34), ("Home Health Aide services", 25, 38),
        ("Companion Care services", 20, 30), ("Skilled Nursing Visit (RN)", 95, 160),
        ("Respite Care services", 24, 36), ("Overnight Care", 180, 300),
        ("Medication Reminder visit", 30, 55), ("Care Coordination fee", 40, 120),
        ("Mileage reimbursement", 0.6, 0.7),
    ],
}

INVOICE_NUMBER_PATTERNS = [
    lambda r: f"INV-2026-{r.randint(1, 99999):05d}",
    lambda r: f"BD/26-27/{r.randint(1, 9999):04d}",
    lambda r: f"A{r.randint(10000, 99999)}",
    lambda r: f"{r.randint(2025, 2026)}/{r.randint(1, 12):02d}/{r.randint(1, 999):04d}",
    lambda r: f"SI-{r.randint(100000, 999999)}",
    lambda r: f"{r.randint(10000, 99999)}",
]
HOMECARE_NUMBER = lambda r: f"HC-{r.randint(100000, 999999)}"


@dataclass
class LineItem:
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal


@dataclass
class Invoice:
    """One invoice. Field values are what is PRINTED on the document.

    `None` means the value is genuinely absent from the document, so a
    correct extractor must return null for it rather than guess.
    """
    invoice_id: str
    locale: str
    invoice_number: str | None
    invoice_date: date | None
    supplier_name: str | None
    customer_name: str | None
    subtotal: Decimal | None
    tax: Decimal | None
    total: Decimal | None
    currency: str | None
    line_items: list[LineItem]
    # presentation choices (not ground truth, but needed to render)
    tax_rate: Decimal = Decimal("0")
    tax_label: str = "Tax"
    currency_display: str = "symbol"  # symbol | code | none
    currency_symbol: str = "$"
    date_style: str = "iso"
    money_style: str = "us"
    supplier_address: str = ""
    customer_address: str = ""
    service_period: str | None = None
    # injected defects, used to build expected validation flags
    defects: list[str] = field(default_factory=list)

    def ground_truth(self) -> dict:
        return {
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date.isoformat() if self.invoice_date else None,
            "supplier_name": self.supplier_name,
            "customer_name": self.customer_name,
            "subtotal": _s(self.subtotal),
            "tax": _s(self.tax),
            "total": _s(self.total),
            "currency": self.currency,
            "line_items": [
                {"description": li.description, "quantity": _s(li.quantity),
                 "unit_price": _s(li.unit_price), "amount": _s(li.amount)}
                for li in self.line_items
            ],
        }

    def expected_flags(self) -> list[str]:
        """Validation flags a correct validator should raise for this invoice."""
        flags = []
        for f in ["invoice_number", "invoice_date", "supplier_name", "customer_name",
                  "total", "currency"]:
            if getattr(self, f) is None:
                flags.append(f"missing:{f}")
        if self.subtotal is not None and self.total is not None:
            tax = self.tax or Decimal("0")
            if abs(self.subtotal + tax - self.total) > CENT:
                flags.append("total_mismatch")
        if self.line_items and self.subtotal is not None:
            if abs(sum(li.amount for li in self.line_items) - self.subtotal) > CENT:
                flags.append("line_items_mismatch")
        for li in self.line_items:
            if abs(li.quantity * li.unit_price - li.amount) > CENT:
                flags.append("line_amount_mismatch")
                break
        return sorted(set(flags))

    def clone(self, new_id: str) -> "Invoice":
        c = copy.deepcopy(self)
        c.invoice_id = new_id
        return c


def _s(d):
    if d is None:
        return None
    # normalise "28.00" and "28.0" quantities to plain strings without trailing zeros
    return format(d.normalize(), "f") if d == d.to_integral() else format(d, "f")


class InvoiceFactory:
    def __init__(self, seed: int = 42):
        self.r = random.Random(seed)
        self.fakers = {
            "us": Faker("en_US"), "uk": Faker("en_GB"), "eu": Faker("de_DE"),
            "homecare": Faker("en_US"),
        }
        for i, f in enumerate(self.fakers.values()):
            f.seed_instance(seed + i)
        self.counter = 0

    def _party(self, locale: str, kind: str) -> tuple[str, str]:
        r = self.r
        if locale == "bd":
            if kind == "person":
                name = r.choice(BD_PEOPLE)
            else:
                name = f"{r.choice(BD_PREFIX)} {r.choice(BD_SUFFIX)}"
            area = r.choice(["Motijheel", "Gulshan-2", "Uttara Sector 7", "Mirpur 10",
                             "Agrabad", "Tejgaon I/A", "Kuril", "Banani"])
            city = "Chattogram" if area == "Agrabad" else "Dhaka"
            addr = f"House {r.randint(1, 120)}, Road {r.randint(1, 30)}, {area}, {city}"
            return name, addr
        f = self.fakers[locale]
        if kind == "person":
            name = f.name()
        elif locale == "homecare":
            stem = r.choice(["Maple Grove", "Willow Creek", "Harbor Light", "Silver Oak",
                             "Brightpath", "Evergreen", "Gentle Hands", "Hearthside"])
            name = f"{stem} {r.choice(['Home Care LLC', 'Home Health Services', 'Care Partners Inc.'])}"
        else:
            name = f.company()
        addr = f.address().replace("\n", ", ")
        return name, addr

    def make(self, locale: str | None = None, n_items: int | None = None) -> Invoice:
        r = self.r
        self.counter += 1
        locale = locale or r.choice(["bd", "bd", "us", "uk", "eu", "homecare"])
        L = LOCALES[locale]
        kind = "homecare" if locale == "homecare" else "general"

        supplier, s_addr = self._party(locale, "company")
        customer, c_addr = self._party(locale, "person" if (kind == "homecare" or r.random() < 0.3) else "company")

        if n_items is None:
            n_items = r.choice([1, 2, 3, 3, 4, 5, 6, 8]) if kind == "general" else r.choice([1, 2, 3, 4])
        catalogue = ITEMS[kind]
        # BDT prices are scaled to realistic taka values
        scale = Decimal("110") if locale == "bd" else Decimal("1")
        items = []
        for _ in range(n_items):
            desc, lo, hi = r.choice(catalogue)
            if kind == "homecare":
                if "Mileage" in desc:
                    qty = Decimal(r.randint(20, 180))
                    price = money(r.uniform(lo, hi))
                elif "Visit" in desc or "fee" in desc or "Overnight" in desc:
                    qty = Decimal(r.randint(1, 8))
                    price = money(r.uniform(lo, hi))
                else:
                    qty = Decimal(r.choice([4, 8, 12, 16, 20, 24, 28, 32, 37.5, 40])).quantize(Decimal("0.1")).normalize()
                    price = money(r.uniform(lo, hi))
            else:
                qty = Decimal(r.choice([1, 1, 2, 3, 5, 10, 12, 20, 25, 50]))
                price = money(Decimal(str(r.uniform(lo, hi))) * scale)
                if locale == "bd":
                    price = price.quantize(Decimal("1"))  # taka prices are usually whole
            items.append(LineItem(desc, qty, money(price), money(qty * price)))

        subtotal = money(sum(li.amount for li in items))
        rate = r.choice(L["tax_rates"])
        tax = money(subtotal * rate / 100)
        total = subtotal + tax

        inv_date = date(2026, 1, 1) + timedelta(days=r.randint(0, 300))
        number = HOMECARE_NUMBER(r) if kind == "homecare" else r.choice(INVOICE_NUMBER_PATTERNS)(r)

        display = r.choices(["symbol", "code", "none"], weights=[6, 3, 1])[0]
        symbol = r.choice(L["symbols"])

        inv = Invoice(
            invoice_id=f"inv{self.counter:04d}", locale=locale,
            invoice_number=number, invoice_date=inv_date,
            supplier_name=supplier, customer_name=customer,
            subtotal=subtotal, tax=tax, total=total,
            currency=None if display == "none" else L["currency"],
            line_items=items, tax_rate=rate, tax_label=r.choice(L["tax_labels"]),
            currency_display=display, currency_symbol=symbol if display == "symbol" else L["currency"],
            date_style=r.choice(L["date_styles"]), money_style=r.choice(L["money_styles"]),
            supplier_address=s_addr, customer_address=c_addr,
        )
        if kind == "homecare":
            start = inv_date - timedelta(days=r.choice([7, 14, 30]))
            inv.service_period = f"{start.isoformat()}|{(inv_date - timedelta(days=1)).isoformat()}"
            # home care invoices are usually tax exempt and often omit the tax line
            if r.random() < 0.5:
                inv.tax = None
                inv.defects.append("no_tax_line")
        if rate == 0 and inv.tax is not None and r.random() < 0.5:
            inv.tax = None
            inv.defects.append("no_tax_line")
        return inv

    # -- defect injection -----------------------------------------------------
    def inject(self, inv: Invoice, defect: str) -> Invoice:
        r = self.r
        if defect == "wrong_total":
            delta = money(r.choice([1, -1]) * r.uniform(1, 50) * (110 if inv.locale == "bd" else 1))
            inv.total = inv.total + delta
        elif defect == "wrong_subtotal":
            # line items no longer add up to the printed subtotal; total stays
            # consistent with the printed subtotal so only one rule fires
            delta = money(r.uniform(5, 40) * (110 if inv.locale == "bd" else 1))
            inv.subtotal = inv.subtotal + delta
            inv.total = inv.subtotal + (inv.tax or Decimal("0"))
        elif defect == "wrong_line_amount":
            li = r.choice(inv.line_items)
            li.amount = li.amount + money(r.uniform(1, 20))
            inv.subtotal = money(sum(x.amount for x in inv.line_items))
            inv.total = inv.subtotal + (inv.tax or Decimal("0"))
        elif defect.startswith("missing_"):
            fieldname = defect[len("missing_"):]
            setattr(inv, fieldname, None)
            if fieldname == "currency":
                inv.currency_display = "none"
        else:
            raise ValueError(defect)
        inv.defects.append(defect)
        return inv


def fmt_money(value: Decimal, style: str) -> str:
    neg = value < 0
    q = abs(value).quantize(CENT)
    whole, frac = f"{q:f}".split(".")
    if style == "indian" and len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
        out = f"{whole}.{frac}"
    elif style == "eu":
        out = f"{int(whole):,}".replace(",", ".") + "," + frac
    else:
        out = f"{int(whole):,}.{frac}"
    return f"-{out}" if neg else out


def fmt_qty(q: Decimal, style: str) -> str:
    s = _s(q)
    return s.replace(".", ",") if style == "eu" else s


MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def fmt_date(d: date, style: str) -> str:
    return {
        "dmy_slash": f"{d.day:02d}/{d.month:02d}/{d.year}",
        "mdy_slash": f"{d.month:02d}/{d.day:02d}/{d.year}",
        "d_mon_y": f"{d.day:02d} {MONTHS[d.month - 1][:3]} {d.year}",
        "month_d_y": f"{MONTHS[d.month - 1]} {d.day}, {d.year}",
        "iso": d.isoformat(),
        "dmy_dash": f"{d.day:02d}-{d.month:02d}-{d.year}",
        "dmy_dot": f"{d.day:02d}.{d.month:02d}.{d.year}",
    }[style]


def show_money(inv: Invoice, value: Decimal) -> str:
    s = fmt_money(value, inv.money_style)
    if inv.currency_display == "none":
        return s
    sym = inv.currency_symbol
    if sym in ("$", "£", "€", "US$"):
        return f"{sym}{s}" if inv.money_style != "eu" else f"{s} {sym}"
    return f"{sym} {s}"
