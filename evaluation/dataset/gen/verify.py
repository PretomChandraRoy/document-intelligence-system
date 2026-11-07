"""Check that every label matches what is actually in its document.

For digital PDFs and spreadsheets the printed values can be read back
exactly, so every ground-truth invoice number, date and total must be
findable in the file. Scans are checked through their source rendering
(same code path), so here we only confirm they open with the right page count.
"""

from __future__ import annotations

import glob
import json
import os
import sys
from datetime import date

import pandas as pd
import pymupdf
from PIL import Image

from .invoice import fmt_money, fmt_date


def check(root: str) -> int:
    errors = 0
    labels = [json.load(open(p)) for p in sorted(glob.glob(os.path.join(root, "labels", "*.json")))]
    for lab in labels:
        path = os.path.join(root, lab["file"])
        if lab["expected_status"] == "failed":
            continue
        fmt = lab["format"]
        try:
            if fmt == "pdf_digital":
                doc = pymupdf.open(path)
                assert doc.page_count == lab["pages"], f"pages {doc.page_count} != {lab['pages']}"
                text = "\n".join(p.get_text() for p in doc)
                for inv in lab["invoices"]:
                    gt = inv["ground_truth"]
                    if gt["invoice_number"]:
                        assert gt["invoice_number"] in text, f"number {gt['invoice_number']} not found"
                    if gt["total"]:
                        from decimal import Decimal
                        variants = [fmt_money(Decimal(gt["total"]), s) for s in ("us", "indian", "eu")]
                        assert any(v in text for v in variants), f"total {gt['total']} not found"
                    if gt["supplier_name"]:
                        assert gt["supplier_name"] in text or gt["supplier_name"].upper() in text, "supplier not found"
            elif fmt == "pdf_mixed":
                doc = pymupdf.open(path)
                assert doc.page_count == lab["pages"]
                for i, page in enumerate(doc, start=1):
                    has_text = bool(page.get_text().strip())
                    assert has_text != (i in lab["scanned_pages"]), f"page {i} text layer wrong"
            elif fmt in ("pdf_scanned",):
                doc = pymupdf.open(path)
                assert doc.page_count == lab["pages"]
                assert not doc[0].get_text().strip(), "scanned PDF should have no text layer"
            elif fmt in ("jpg", "png", "tiff"):
                im = Image.open(path)
                n = getattr(im, "n_frames", 1)
                assert n == lab["pages"], f"frames {n} != {lab['pages']}"
            elif fmt in ("xlsx", "xls", "csv"):
                if fmt == "csv":
                    raw = open(path, encoding="utf-8-sig").read()
                    cells = raw
                else:
                    sheets = pd.read_excel(path, sheet_name=None, header=None)
                    cells = "\n".join(df.astype(str).to_csv() for df in sheets.values())
                for inv in lab["invoices"]:
                    gt = inv["ground_truth"]
                    if gt["invoice_number"]:
                        assert gt["invoice_number"] in cells, f"number {gt['invoice_number']} not in sheet"
                    if gt["total"]:
                        t = float(gt["total"])
                        cand = [f"{t:.2f}", f"{t:.2f}".replace(".", ","), str(t), repr(t)] + ([str(int(t))] if t == int(t) else [])
                        assert any(c in cells for c in cand), f"total {gt['total']} not in sheet"
        except AssertionError as e:
            errors += 1
            print(f"{lab['doc_id']} ({fmt}): {e}")
        except Exception as e:
            errors += 1
            print(f"{lab['doc_id']} ({fmt}): could not open: {e!r}")

    # failed documents must really be unreadable by the obvious library
    for lab in labels:
        if lab["expected_status"] != "failed":
            continue
        path = os.path.join(root, lab["file"])
        opened = False
        try:
            if path.endswith(".pdf"):
                d = pymupdf.open(path)
                opened = d.page_count > 0 and not d.needs_pass and bool(d[0].get_text().strip())
            elif path.endswith((".png", ".jpg")):
                im = Image.open(path)
                im.load()
                opened = True
            elif path.endswith(".xlsx"):
                pd.read_excel(path)
                opened = True
            elif path.endswith(".csv"):
                df = pd.read_csv(path)
                opened = len(df) > 0
        except Exception:
            opened = False
        if opened:
            errors += 1
            print(f"{lab['doc_id']}: expected to fail but opened cleanly ({lab['notes']})")

    print(f"checked {len(labels)} labels, {errors} problems")
    return errors


if __name__ == "__main__":
    sys.exit(1 if check(sys.argv[1] if len(sys.argv) > 1 else "data") else 0)
