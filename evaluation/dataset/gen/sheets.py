"""Render invoices to XLSX, XLS and CSV in the layouts accounts teams use.

  form       - key/value header block, then an items table, then totals
  multisheet - 'Summary' sheet for header fields, 'Items' sheet for lines,
               sometimes an unrelated 'Notes' sheet the parser must ignore
  ledger     - one row per line item with the header fields repeated; one
               file can hold several invoices (a typical ERP export)
"""

from __future__ import annotations

import csv
import random
from datetime import datetime

import openpyxl
import xlwt

from .invoice import Invoice, fmt_date, fmt_money, _s

LEDGER_COLS = ["Invoice No", "Invoice Date", "Supplier", "Customer", "Currency",
               "Item Description", "Qty", "Unit Price", "Line Amount",
               "Subtotal", "Tax", "Total"]


def _num(d):
    return None if d is None else float(d)


def _date_cell(inv: Invoice, as_text: bool):
    if inv.invoice_date is None:
        return None
    if as_text:
        return fmt_date(inv.invoice_date, inv.date_style)
    return datetime(inv.invoice_date.year, inv.invoice_date.month, inv.invoice_date.day)


def form_rows(inv: Invoice, date_as_text: bool) -> list[list]:
    rows = [["INVOICE"], []]
    if inv.supplier_name:
        rows.append(["Supplier", inv.supplier_name])
    if inv.invoice_number:
        rows.append(["Invoice Number", inv.invoice_number])
    if inv.invoice_date:
        rows.append(["Invoice Date", _date_cell(inv, date_as_text)])
    if inv.customer_name:
        rows.append(["Bill To", inv.customer_name])
    if inv.currency:
        rows.append(["Currency", inv.currency])
    rows += [[], ["Description", "Quantity", "Unit Price", "Amount"]]
    for li in inv.line_items:
        rows.append([li.description, _num(li.quantity), _num(li.unit_price), _num(li.amount)])
    rows.append([])
    if inv.subtotal is not None:
        rows.append(["", "", "Subtotal", _num(inv.subtotal)])
    if inv.tax is not None:
        rows.append(["", "", inv.tax_label, _num(inv.tax)])
    if inv.total is not None:
        rows.append(["", "", "Total", _num(inv.total)])
    return rows


def summary_rows(inv: Invoice, date_as_text: bool) -> list[list]:
    rows = [["Field", "Value"]]
    for k, v in [("Invoice No", inv.invoice_number), ("Date", _date_cell(inv, date_as_text)),
                 ("Vendor", inv.supplier_name), ("Customer", inv.customer_name),
                 ("Currency", inv.currency), ("Net", _num(inv.subtotal)),
                 (inv.tax_label, _num(inv.tax)), ("Gross Total", _num(inv.total))]:
        if v is not None:
            rows.append([k, v])
    return rows


def items_rows(inv: Invoice) -> list[list]:
    rows = [["Line", "Description", "Qty", "Rate", "Amount"]]
    for i, li in enumerate(inv.line_items, 1):
        rows.append([i, li.description, _num(li.quantity), _num(li.unit_price), _num(li.amount)])
    return rows


def ledger_rows(invoices: list[Invoice], date_as_text: bool) -> list[list]:
    rows = [LEDGER_COLS]
    for inv in invoices:
        for li in inv.line_items:
            rows.append([inv.invoice_number, _date_cell(inv, date_as_text), inv.supplier_name,
                         inv.customer_name, inv.currency, li.description, _num(li.quantity),
                         _num(li.unit_price), _num(li.amount), _num(inv.subtotal),
                         _num(inv.tax), _num(inv.total)])
    return rows


# -- writers -----------------------------------------------------------------
def write_xlsx(path: str, sheets: dict[str, list[list]]) -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, datetime):
                    cell.number_format = "DD/MM/YYYY"
                elif isinstance(cell.value, float):
                    cell.number_format = "#,##0.00"
        ws.column_dimensions["A"].width = 32
        ws.column_dimensions["B"].width = 28
    wb.save(path)


def write_xls(path: str, sheets: dict[str, list[list]]) -> None:
    wb = xlwt.Workbook()
    date_style = xlwt.easyxf(num_format_str="DD/MM/YYYY")
    num_style = xlwt.easyxf(num_format_str="#,##0.00")
    for name, rows in sheets.items():
        ws = wb.add_sheet(name)
        for i, r in enumerate(rows):
            for j, v in enumerate(r):
                if v is None:
                    continue
                if isinstance(v, datetime):
                    ws.write(i, j, v, date_style)
                elif isinstance(v, float):
                    ws.write(i, j, v, num_style)
                else:
                    ws.write(i, j, v)
    wb.save(path)


def write_csv(path: str, rows: list[list], dialect: str, inv_style: str = "us") -> None:
    """dialect: 'us' (comma, dot decimal) or 'eu' (semicolon, comma decimal)."""
    delim = ";" if dialect == "eu" else ","

    def cell(v):
        if v is None:
            return ""
        if isinstance(v, float):
            s = f"{v:.2f}"
            return s.replace(".", ",") if dialect == "eu" else s
        if isinstance(v, datetime):
            return v.strftime("%Y-%m-%d")
        return str(v)

    with open(path, "w", newline="", encoding="utf-8-sig" if dialect == "eu" else "utf-8") as f:
        w = csv.writer(f, delimiter=delim)
        for r in rows:
            w.writerow([cell(v) for v in r])


def render_sheet(invoices: list[Invoice], path: str, fmt: str, layout: str,
                 rng: random.Random) -> dict:
    date_as_text = rng.random() < 0.4
    if layout == "form":
        sheets = {"Invoice": form_rows(invoices[0], date_as_text)}
    elif layout == "multisheet":
        inv = invoices[0]
        sheets = {"Summary": summary_rows(inv, date_as_text), "Items": items_rows(inv)}
        if rng.random() < 0.5:
            sheets["Notes"] = [["Prepared by accounts team"], ["Do not edit totals manually"]]
    elif layout == "ledger":
        sheets = {"Export": ledger_rows(invoices, date_as_text)}
    else:
        raise ValueError(layout)

    if fmt == "xlsx":
        write_xlsx(path, sheets)
    elif fmt == "xls":
        write_xls(path, sheets)
    elif fmt == "csv":
        if len(sheets) > 1:
            raise ValueError("CSV cannot hold several sheets")
        dialect = "eu" if invoices[0].money_style == "eu" else "us"
        write_csv(path, next(iter(sheets.values())), dialect)
        return {"sheets": 1, "csv_dialect": dialect, "date_as_text": date_as_text}
    return {"sheets": len(sheets), "sheet_names": list(sheets), "date_as_text": date_as_text}
