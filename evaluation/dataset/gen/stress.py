"""Generate one large multi-invoice PDF for throughput testing.

The brief says incoming PDFs run to about 1,000 pages. This builds a PDF of
at least --pages pages made of many invoices back to back, with labels, so
the pipeline's speed and invoice splitting can be measured at that size.

    python -m gen.stress --pages 1000 --scanned-fraction 0.2 --out data_stress

Scanned pages are rasterised and degraded, so they exercise the OCR path.
The output is not committed to git (it is large and fully reproducible).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import tempfile
import time

import pymupdf

from .degrade import SEVERITY, scan_pdf
from .invoice import InvoiceFactory
from .pdf_templates import render_pdf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=1000)
    ap.add_argument("--scanned-fraction", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="data_stress")
    a = ap.parse_args()

    t0 = time.time()
    rng = random.Random(a.seed)
    fac = InvoiceFactory(a.seed)
    os.makedirs(a.out, exist_ok=True)
    out = pymupdf.open()
    invoices = []
    with tempfile.TemporaryDirectory() as tmp:
        while out.page_count < a.pages:
            inv = fac.make(n_items=rng.choice([3, 5, 8, 12, 30, 45]))
            tpl = "homecare" if inv.locale == "homecare" else rng.choice(["classic", "modern", "receipt"])
            p = os.path.join(tmp, "x.pdf")
            render_pdf(inv, p, tpl)
            scanned = rng.random() < a.scanned_fraction
            if scanned:
                imgs = scan_pdf(p, "mild", rng)
                src = pymupdf.open()
                for im in imgs:
                    ip = os.path.join(tmp, "x.jpg")
                    im.convert("RGB").save(ip, quality=80)
                    page = src.new_page(width=595, height=842)
                    page.insert_image(page.rect, filename=ip)
            else:
                src = pymupdf.open(p)
            start = out.page_count + 1
            out.insert_pdf(src)
            invoices.append({"invoice_id": inv.invoice_id, "pages": [start, out.page_count],
                             "scanned": scanned, "ground_truth": inv.ground_truth(),
                             "expected_flags": inv.expected_flags()})
            src.close()
    path = os.path.join(a.out, f"stress_{a.pages}p.pdf")
    out.save(path, garbage=3, deflate=True)
    with open(os.path.join(a.out, f"stress_{a.pages}p.json"), "w") as fh:
        json.dump({"file": os.path.basename(path), "pages": out.page_count,
                   "invoices": invoices}, fh, indent=1)
    size = os.path.getsize(path) / 1e6
    print(f"{out.page_count} pages, {len(invoices)} invoices, {size:.1f} MB, built in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
