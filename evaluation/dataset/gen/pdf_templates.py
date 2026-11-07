"""Render invoices to digital (text-layer) PDFs with four distinct layouts.

Layouts differ in field labels, positions, fonts and table styling, so an
extractor cannot rely on one fixed template. Long invoices flow onto extra
pages; totals appear only on the last page, as on real multi-page invoices.
"""

from __future__ import annotations

from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from .invoice import Invoice, fmt_date, fmt_qty, show_money, fmt_money

W, H = A4
MARGIN = 50


def _fit(text: str, font: str, size: float, width: float) -> str:
    if stringWidth(text, font, size) <= width:
        return text
    while text and stringWidth(text + "...", font, size) > width:
        text = text[:-1]
    return text + "..."


def _period(inv: Invoice) -> str | None:
    if not inv.service_period:
        return None
    a, b = inv.service_period.split("|")
    return f"{fmt_date(date.fromisoformat(a), inv.date_style)} - {fmt_date(date.fromisoformat(b), inv.date_style)}"


class Template:
    name = "base"
    font = "Helvetica"
    bold = "Helvetica-Bold"
    size = 10
    row_h = 18
    labels = {}
    first_page_table_top = 560
    other_page_table_top = 760
    bottom_limit = 90
    totals_height = 110

    # columns: (key, header, x, width, align)
    cols = [
        ("description", "Description", MARGIN, 270, "l"),
        ("quantity", "Qty", 330, 50, "r"),
        ("unit_price", "Unit Price", 390, 80, "r"),
        ("amount", "Amount", 480, 65, "r"),
    ]

    def __init__(self, inv: Invoice):
        self.inv = inv

    # -- hooks ---------------------------------------------------------------
    def header(self, c: Canvas, first: bool) -> None:
        raise NotImplementedError

    def table_header(self, c: Canvas, y: float) -> float:
        c.setFont(self.bold, self.size)
        for key, head, x, w, align in self.cols:
            self._text(c, head, x, w, y, align)
        c.line(MARGIN, y - 5, W - MARGIN, y - 5)
        return y - self.row_h - 2

    def row(self, c: Canvas, y: float, li, i: int) -> None:
        inv = self.inv
        c.setFont(self.font, self.size)
        vals = {
            "description": li.description,
            "quantity": fmt_qty(li.quantity, inv.money_style),
            "unit_price": fmt_money(li.unit_price, inv.money_style),
            "amount": fmt_money(li.amount, inv.money_style),
        }
        for key, head, x, w, align in self.cols:
            self._text(c, vals[key], x, w, y, align)

    def totals(self, c: Canvas, y: float) -> None:
        inv = self.inv
        L = self.labels
        lines = []
        if inv.subtotal is not None:
            lines.append((L.get("subtotal", "Subtotal"), show_money(inv, inv.subtotal), False))
        if inv.tax is not None:
            rate = f" ({fmt_qty(inv.tax_rate, inv.money_style)}%)" if inv.tax_rate else ""
            lines.append((f"{inv.tax_label}{rate}", show_money(inv, inv.tax), False))
        if inv.total is not None:
            lines.append((L.get("total", "Total"), show_money(inv, inv.total), True))
        y -= 10
        for label, val, strong in lines:
            c.setFont(self.bold if strong else self.font, self.size + (1 if strong else 0))
            c.drawRightString(440, y, label)
            c.drawRightString(W - MARGIN, y, val)
            y -= self.row_h

    def footer(self, c: Canvas, page: int, pages: int) -> None:
        c.setFont(self.font, 8)
        c.drawCentredString(W / 2, 40, f"Page {page} of {pages}")

    # -- engine --------------------------------------------------------------
    @staticmethod
    def _text(c, s, x, w, y, align):
        if align == "r":
            c.drawRightString(x + w, y, s)
        else:
            c.drawString(x, y, _fit(s, c._fontname, c._fontsize, w))

    def paginate(self) -> list[list]:
        items = self.inv.line_items
        pages, cur = [], []
        top = self.first_page_table_top
        cap = int((top - self.row_h - self.bottom_limit) // self.row_h)
        for li in items:
            if len(cur) >= cap:
                pages.append(cur)
                cur = []
                cap = int((self.other_page_table_top - self.row_h - self.bottom_limit) // self.row_h)
            cur.append(li)
        pages.append(cur)
        # make sure the totals block fits after the final rows
        last_top = self.first_page_table_top if len(pages) == 1 else self.other_page_table_top
        used = self.row_h + 2 + len(pages[-1]) * self.row_h
        if last_top - used - self.totals_height < 50 and len(pages[-1]) > 1:
            moved = pages[-1][-2:]
            pages[-1] = pages[-1][:-2]
            pages.append(moved)
        return pages

    def render(self, path: str) -> int:
        c = Canvas(path, pagesize=A4)
        c.setTitle("Invoice")
        c.setCreator("synthetic-invoice-generator")
        pages = self.paginate()
        idx = 0
        for p, rows in enumerate(pages, start=1):
            first = p == 1
            self.header(c, first)
            y = self.first_page_table_top if first else self.other_page_table_top
            y = self.table_header(c, y)
            for li in rows:
                self.row(c, y, li, idx)
                idx += 1
                y -= self.row_h
            if p == len(pages):
                c.line(330, y + 8, W - MARGIN, y + 8)
                self.totals(c, y)
            else:
                c.setFont(self.font, 8)
                c.drawRightString(W - MARGIN, y - 4, "Continued on next page")
            self.footer(c, p, len(pages))
            c.showPage()
        c.save()
        return len(pages)


class Classic(Template):
    """Plain business invoice, supplier block top-left, meta table top-right."""
    name = "classic"
    labels = {"subtotal": "Subtotal", "total": "Total"}

    def header(self, c, first):
        inv = self.inv
        if not first:
            c.setFont(self.bold, 11)
            c.drawString(MARGIN, H - 60, f"{inv.supplier_name or ''}")
            if inv.invoice_number:
                c.setFont(self.font, 9)
                c.drawRightString(W - MARGIN, H - 60, f"Invoice {inv.invoice_number} (continued)")
            return
        c.setFont(self.bold, 22)
        c.drawRightString(W - MARGIN, H - 70, "INVOICE")
        if inv.supplier_name:
            c.setFont(self.bold, 14)
            c.drawString(MARGIN, H - 70, inv.supplier_name)
        c.setFont(self.font, 9)
        c.drawString(MARGIN, H - 86, _fit(inv.supplier_address, self.font, 9, 300))
        y = H - 110
        c.setFont(self.font, 10)
        if inv.invoice_number:
            c.drawRightString(440, y, "Invoice No:")
            c.drawRightString(W - MARGIN, y, inv.invoice_number)
            y -= 16
        if inv.invoice_date:
            c.drawRightString(440, y, "Invoice Date:")
            c.drawRightString(W - MARGIN, y, fmt_date(inv.invoice_date, inv.date_style))
            y -= 16
        if inv.currency_display == "code":
            c.drawRightString(440, y, "Currency:")
            c.drawRightString(W - MARGIN, y, inv.currency)
        if inv.customer_name:
            c.setFont(self.bold, 10)
            c.drawString(MARGIN, H - 170, "Bill To:")
            c.setFont(self.font, 10)
            c.drawString(MARGIN, H - 186, inv.customer_name)
            c.setFont(self.font, 9)
            c.drawString(MARGIN, H - 200, _fit(inv.customer_address, self.font, 9, 300))


class Modern(Template):
    """Coloured header band, zebra-striped table, 'Amount Due'."""
    name = "modern"
    labels = {"subtotal": "Sub Total", "total": "Amount Due"}
    band = colors.HexColor("#1f3a5f")

    def header(self, c, first):
        inv = self.inv
        c.setFillColor(self.band)
        c.rect(0, H - (110 if first else 60), W, 110 if first else 60, stroke=0, fill=1)
        c.setFillColor(colors.white)
        if inv.supplier_name:
            c.setFont(self.bold, 16 if first else 11)
            c.drawString(MARGIN, H - (55 if first else 38), inv.supplier_name)
        if first:
            c.setFont(self.font, 9)
            c.drawString(MARGIN, H - 75, _fit(inv.supplier_address, self.font, 9, 320))
            c.setFont(self.bold, 18)
            c.drawRightString(W - MARGIN, H - 55, "Tax Invoice" if inv.tax else "Invoice")
        c.setFillColor(colors.black)
        if not first:
            return
        y = H - 150
        c.setFont(self.bold, 9)
        c.drawString(MARGIN, y, "BILLED TO")
        c.drawString(330, y, "DETAILS")
        c.setFont(self.font, 10)
        if inv.customer_name:
            c.drawString(MARGIN, y - 16, inv.customer_name)
            c.setFont(self.font, 9)
            c.drawString(MARGIN, y - 30, _fit(inv.customer_address, self.font, 9, 260))
        c.setFont(self.font, 10)
        yy = y - 16
        if inv.invoice_number:
            c.drawString(330, yy, f"Invoice # {inv.invoice_number}")
            yy -= 15
        if inv.invoice_date:
            c.drawString(330, yy, f"Issued: {fmt_date(inv.invoice_date, inv.date_style)}")
            yy -= 15
        if inv.currency_display == "code":
            c.drawString(330, yy, f"Currency: {inv.currency}")

    def row(self, c, y, li, i):
        if i % 2 == 0:
            c.setFillColor(colors.HexColor("#eef2f7"))
            c.rect(MARGIN, y - 5, W - 2 * MARGIN, self.row_h, stroke=0, fill=1)
            c.setFillColor(colors.black)
        super().row(c, y, li, i)


class Receipt(Template):
    """Monospaced, terse labels, closer to a till receipt or ERP printout."""
    name = "receipt"
    font = "Courier"
    bold = "Courier-Bold"
    size = 9
    row_h = 15
    labels = {"subtotal": "NET AMOUNT", "total": "TOTAL PAYABLE"}
    cols = [
        ("description", "ITEM", MARGIN, 260, "l"),
        ("quantity", "QTY", 320, 45, "r"),
        ("unit_price", "RATE", 375, 80, "r"),
        ("amount", "AMOUNT", 465, 80, "r"),
    ]

    def header(self, c, first):
        inv = self.inv
        c.setFont(self.bold, 12)
        if inv.supplier_name:
            c.drawCentredString(W / 2, H - 60, inv.supplier_name.upper())
        if not first:
            return
        c.setFont(self.font, 9)
        c.drawCentredString(W / 2, H - 75, _fit(inv.supplier_address, self.font, 9, 450))
        c.drawCentredString(W / 2, H - 100, "-" * 60)
        y = H - 120
        if inv.invoice_number:
            c.drawString(MARGIN, y, f"INV. NO. : {inv.invoice_number}")
        if inv.invoice_date:
            c.drawString(330, y, f"DT. : {fmt_date(inv.invoice_date, inv.date_style)}")
        if inv.customer_name:
            c.drawString(MARGIN, y - 15, f"CUSTOMER: {inv.customer_name}")
        if inv.currency_display == "code":
            c.drawString(330, y - 15, f"CURRENCY: {inv.currency}")
        c.drawCentredString(W / 2, y - 35, "-" * 60)


class HomeCare(Template):
    """US home care billing statement: service period, hours and rates."""
    name = "homecare"
    labels = {"subtotal": "Total Charges", "total": "Balance Due"}
    cols = [
        ("description", "Service", MARGIN, 250, "l"),
        ("quantity", "Hours/Units", 310, 70, "r"),
        ("unit_price", "Rate", 390, 75, "r"),
        ("amount", "Amount", 475, 70, "r"),
    ]

    def header(self, c, first):
        inv = self.inv
        if inv.supplier_name:
            c.setFont("Times-Bold", 16 if first else 11)
            c.drawString(MARGIN, H - 65, inv.supplier_name)
        if not first:
            return
        c.setFont("Times-Roman", 9)
        c.drawString(MARGIN, H - 80, _fit(inv.supplier_address, "Times-Roman", 9, 320))
        c.setFont("Times-Bold", 13)
        c.drawRightString(W - MARGIN, H - 65, "STATEMENT OF SERVICES")
        c.setStrokeColor(colors.HexColor("#2e6b4f"))
        c.setLineWidth(2)
        c.line(MARGIN, H - 95, W - MARGIN, H - 95)
        c.setLineWidth(1)
        c.setStrokeColor(colors.black)
        y = H - 125
        c.setFont("Times-Roman", 10)
        if inv.customer_name:
            c.drawString(MARGIN, y, f"Client: {inv.customer_name}")
            c.drawString(MARGIN, y - 14, _fit(inv.customer_address, "Times-Roman", 9, 260))
        yy = y
        if inv.invoice_number:
            c.drawString(330, yy, f"Invoice #: {inv.invoice_number}")
            yy -= 14
        if inv.invoice_date:
            c.drawString(330, yy, f"Invoice Date: {fmt_date(inv.invoice_date, inv.date_style)}")
            yy -= 14
        p = _period(inv)
        if p:
            c.drawString(330, yy, f"Service Period: {p}")
            yy -= 14
        c.drawString(330, yy, "Terms: Net 30")


TEMPLATES = {t.name: t for t in (Classic, Modern, Receipt, HomeCare)}


def render_pdf(inv: Invoice, path: str, template: str) -> int:
    return TEMPLATES[template](inv).render(path)


def render_bundle(invoices: list[tuple[Invoice, str]], path: str) -> list[tuple[int, int]]:
    """Render several invoices into one PDF. Returns (first_page, last_page) per invoice."""
    import pymupdf
    import tempfile, os
    out = pymupdf.open()
    ranges = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (inv, tpl) in enumerate(invoices):
            p = os.path.join(tmp, f"{i}.pdf")
            render_pdf(inv, p, tpl)
            src = pymupdf.open(p)
            start = out.page_count + 1
            out.insert_pdf(src)
            ranges.append((start, out.page_count))
            src.close()
    out.save(path, garbage=3, deflate=True)
    return ranges
