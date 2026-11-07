"""Build the labelled evaluation dataset.

Usage:
    python -m gen.build --out data --seed 42

Outputs:
    data/files/<doc_id>.<ext>     the documents
    data/labels/<doc_id>.json     ground truth for each document
    data/groups.json              documents that contain the same invoice
                                  (duplicates and cross-verification pairs)
    data/manifest.csv             one row per document, for quick inspection
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import shutil
from collections import Counter
from decimal import Decimal

import pymupdf

from .degrade import SEVERITY, scan_pdf, save_images_as_pdf
from .invoice import Invoice, InvoiceFactory, money
from .pdf_templates import render_bundle, render_pdf
from .sheets import render_sheet

DEFECT_QUOTA = {
    "wrong_total": 14, "wrong_subtotal": 8, "wrong_line_amount": 6,
    "missing_customer_name": 6, "missing_invoice_date": 6,
    "missing_invoice_number": 3, "missing_currency": 3,
}


class Builder:
    def __init__(self, out: str, seed: int):
        self.out = out
        self.files = os.path.join(out, "files")
        self.labels = os.path.join(out, "labels")
        self.tmp = os.path.join(out, "_tmp")
        for d in (self.files, self.labels, self.tmp):
            os.makedirs(d, exist_ok=True)
        self.r = random.Random(seed)
        self.f = InvoiceFactory(seed)
        self.docs: list[dict] = []
        self.groups: list[dict] = []
        defects = [d for d, n in DEFECT_QUOTA.items() for _ in range(n)]
        self.r.shuffle(defects)
        self.defects = defects
        self._live: dict[str, Invoice] = {}  # invoice_id -> Invoice, for duplicates and twins

    # -- helpers ---------------------------------------------------------------
    def next_id(self) -> str:
        return f"d{len(self.docs) + 1:03d}"

    def template_for(self, inv: Invoice) -> str:
        return "homecare" if inv.locale == "homecare" else self.r.choice(["classic", "modern", "receipt"])

    def invoice(self, locale=None, n_items=None, allow_defect=True) -> Invoice:
        inv = self.f.make(locale, n_items)
        # spread the defect quota over the first eligible invoices, about 1 in 3
        if allow_defect and self.defects and self.r.random() < 0.33:
            d = self.defects.pop()
            if d == "missing_currency" and inv.currency is None:
                d = "wrong_total"
            self.f.inject(inv, d)
        return inv

    def record(self, doc_id, ext, fmt, invoices, *, layout=None, degradation=None,
               pages=None, page_ranges=None, status="completed", error=None, notes=None):
        label = {
            "doc_id": doc_id,
            "file": f"files/{doc_id}.{ext}",
            "format": fmt,
            "layout": layout,
            "degradation": degradation,
            "pages": pages,
            "split": "dev" if self.r.random() < 0.3 else "test",
            "expected_status": status,
            "expected_error": error,
            "invoices": [],
            "notes": notes,
        }
        for i, inv in enumerate(invoices):
            entry = {
                "invoice_id": inv.invoice_id,
                "locale": inv.locale,
                "defects": inv.defects,
                "ground_truth": inv.ground_truth(),
                "expected_flags": inv.expected_flags(),
            }
            if page_ranges:
                entry["pages"] = list(page_ranges[i])
            label["invoices"].append(entry)
        self.docs.append(label)
        for inv in invoices:
            self._live[inv.invoice_id] = inv
        return label

    def path(self, doc_id, ext):
        return os.path.join(self.files, f"{doc_id}.{ext}")

    # -- document kinds --------------------------------------------------------
    def digital_pdf(self, inv: Invoice, template=None, notes=None) -> dict:
        doc_id = self.next_id()
        template = template or self.template_for(inv)
        pages = render_pdf(inv, self.path(doc_id, "pdf"), template)
        return self.record(doc_id, "pdf", "pdf_digital", [inv], layout=template, pages=pages, notes=notes)

    def scanned(self, inv: Invoice, fmt: str, level: str, notes=None) -> dict:
        """fmt: pdf_scanned | jpg | png | tiff"""
        doc_id = self.next_id()
        template = self.template_for(inv)
        src = os.path.join(self.tmp, f"{doc_id}.pdf")
        pages = render_pdf(inv, src, template)
        images = scan_pdf(src, level, self.r)
        dpi = SEVERITY[level]["dpi"]
        if fmt == "pdf_scanned":
            ext = "pdf"
            save_images_as_pdf(images, self.path(doc_id, ext), dpi)
        elif fmt == "tiff":
            ext = "tiff"
            images[0].save(self.path(doc_id, ext), save_all=True, append_images=images[1:],
                           compression="tiff_lzw", dpi=(dpi, dpi))
        else:
            if len(images) > 1:
                raise ValueError("single-image formats need a one-page invoice")
            ext = fmt
            kw = {"quality": SEVERITY[level]["jpeg"]} if fmt == "jpg" else {}
            images[0].save(self.path(doc_id, ext), dpi=(dpi, dpi), **kw)
        return self.record(doc_id, ext, fmt, [inv], layout=template, degradation=level,
                           pages=pages, notes=notes)

    def sheet(self, invoices: list[Invoice], fmt: str, layout: str, notes=None) -> dict:
        doc_id = self.next_id()
        meta = render_sheet(invoices, self.path(doc_id, fmt), fmt, layout, self.r)
        return self.record(doc_id, fmt, fmt, invoices, layout=layout,
                           notes=notes or json.dumps(meta))

    def bundle(self, invoices: list[Invoice], level=None) -> dict:
        doc_id = self.next_id()
        pairs = [(inv, self.template_for(inv)) for inv in invoices]
        if level is None:
            ranges = render_bundle(pairs, self.path(doc_id, "pdf"))
            fmt = "pdf_digital"
        else:
            src = os.path.join(self.tmp, f"{doc_id}.pdf")
            ranges = render_bundle(pairs, src)
            images = scan_pdf(src, level, self.r)
            save_images_as_pdf(images, self.path(doc_id, "pdf"), SEVERITY[level]["dpi"])
            fmt = "pdf_scanned"
        pages = ranges[-1][1]
        return self.record(doc_id, "pdf", fmt, invoices, layout="bundle", degradation=level,
                           pages=pages, page_ranges=ranges,
                           notes="Several invoices in one PDF; the system must split them.")

    def mixed(self, invoices: list[Invoice], scan_pages: set[int], level: str, notes: str) -> dict:
        """A PDF where some pages have a text layer and others are scans."""
        doc_id = self.next_id()
        pairs = [(inv, self.template_for(inv)) for inv in invoices]
        src_path = os.path.join(self.tmp, f"{doc_id}.pdf")
        ranges = render_bundle(pairs, src_path)
        src = pymupdf.open(src_path)
        out = pymupdf.open()
        for i in range(src.page_count):
            pno = i + 1
            if pno in scan_pages:
                one = os.path.join(self.tmp, f"{doc_id}_p{pno}.pdf")
                single = pymupdf.open()
                single.insert_pdf(src, from_page=i, to_page=i)
                single.save(one)
                img = scan_pdf(one, level, self.r)[0]
                ip = os.path.join(self.tmp, f"{doc_id}_p{pno}.jpg")
                img.convert("RGB").save(ip, quality=SEVERITY[level]["jpeg"])
                page = out.new_page(width=src[i].rect.width, height=src[i].rect.height)
                page.insert_image(page.rect, filename=ip)
            else:
                out.insert_pdf(src, from_page=i, to_page=i)
        out.save(self.path(doc_id, "pdf"), garbage=3, deflate=True)
        lab = self.record(doc_id, "pdf", "pdf_mixed", invoices,
                          layout="bundle" if len(invoices) > 1 else pairs[0][1],
                          degradation=level, pages=src.page_count,
                          page_ranges=ranges if len(invoices) > 1 else None, notes=notes)
        lab["scanned_pages"] = sorted(scan_pages)
        return lab

    # -- groups: duplicates and cross-verification -----------------------------
    def add_group(self, relation: str, members: list[tuple[dict, Invoice]]):
        gts = [inv.ground_truth() for _, inv in members]
        mismatches = sorted({k for k in gts[0] for g in gts[1:] if g[k] != gts[0][k]})
        self.groups.append({
            "relation": relation,
            "docs": [d["doc_id"] for d, _ in members],
            "invoice_ids": [inv.invoice_id for _, inv in members],
            "key": {"supplier_name": members[0][1].supplier_name,
                    "invoice_number": members[0][1].invoice_number},
            "expected_mismatches": mismatches,
        })
        for doc, inv in members:
            for entry in doc["invoices"]:
                if entry["invoice_id"] == inv.invoice_id:
                    entry["expected_flags"] = sorted(set(entry["expected_flags"]) | {"duplicate"}
                                                     | {f"cross_mismatch:{m}" for m in mismatches})

    def twin(self, inv: Invoice, change: str | None) -> Invoice:
        t = inv.clone(inv.invoice_id + "b")
        t.defects = []
        r = self.r
        if change == "total":
            t.total = t.total + money(r.uniform(5, 60) * (110 if t.locale == "bd" else 1))
            t.defects.append("twin_total_differs")
        elif change == "quantity":
            li = r.choice(t.line_items)
            li.quantity = li.quantity + 1
            li.amount = money(li.quantity * li.unit_price)
            t.subtotal = money(sum(x.amount for x in t.line_items))
            if t.tax is not None:
                t.tax = money(t.subtotal * t.tax_rate / 100)
            t.total = t.subtotal + (t.tax or Decimal("0"))
            t.defects.append("twin_quantity_differs")
        elif change == "date":
            from datetime import timedelta
            t.invoice_date = t.invoice_date + timedelta(days=r.choice([-3, -1, 1, 10]))
            t.defects.append("twin_date_differs")
        return t

    # -- corrupted files -------------------------------------------------------
    def corrupted(self):
        ok = os.path.join(self.tmp, "ok.pdf")
        render_pdf(self.f.make("us"), ok, "classic")
        data = open(ok, "rb").read()
        cases = [
            ("pdf", "pdf_digital", data[: len(data) // 3], "corrupted", "PDF truncated to one third"),
            ("pdf", "pdf_digital", os.urandom(4096), "corrupted", "Random bytes with a .pdf extension"),
            ("png", "png", b"", "empty_file", "Zero-byte PNG"),
            ("xlsx", "xlsx", b"Supplier,Total\nAcme,100\n", "corrupted", "Plain text renamed to .xlsx"),
            ("csv", "csv", os.urandom(2048), "corrupted", "Binary data with a .csv extension"),
        ]
        for ext, fmt, payload, err, note in cases:
            doc_id = self.next_id()
            with open(self.path(doc_id, ext), "wb") as fh:
                fh.write(payload)
            self.record(doc_id, ext, fmt, [], status="failed", error=err, notes=note)

        # truncated JPEG: the header is valid but the image data stops halfway
        doc_id = self.next_id()
        inv = self.f.make("bd", 3)
        src = os.path.join(self.tmp, "trunc.pdf")
        render_pdf(inv, src, "classic")
        img = scan_pdf(src, "mild", self.r)[0]
        jp = os.path.join(self.tmp, "trunc.jpg")
        img.save(jp, quality=85)
        b = open(jp, "rb").read()
        with open(self.path(doc_id, "jpg"), "wb") as fh:
            fh.write(b[: len(b) // 2])
        self.record(doc_id, "jpg", "jpg", [], status="failed", error="corrupted",
                    notes="JPEG cut off halfway; must fail cleanly, not return a half-read invoice")

        # password-protected PDF
        doc_id = self.next_id()
        d = pymupdf.open(ok)
        d.save(self.path(doc_id, "pdf"), encryption=pymupdf.PDF_ENCRYPT_AES_256,
               owner_pw="owner-secret", user_pw="user-secret")
        self.record(doc_id, "pdf", "pdf_digital", [], status="failed", error="encrypted",
                    notes="Password-protected PDF")

        # spreadsheet with headers but no data
        doc_id = self.next_id()
        with open(self.path(doc_id, "csv"), "w") as fh:
            fh.write("Invoice No,Invoice Date,Supplier,Total\n")
        self.record(doc_id, "csv", "csv", [], status="failed", error="no_data",
                    notes="Header row only")

    # -- the full composition --------------------------------------------------
    def build(self):
        r = self.r
        levels = ["clean", "mild", "mild", "moderate", "moderate", "severe"]

        # 1. digital PDFs (50): 10 home care, 7 long multi-page
        for i in range(50):
            if i < 10:
                self.digital_pdf(self.invoice("homecare"))
            elif i < 17:
                self.digital_pdf(self.invoice(n_items=r.randint(35, 70)),
                                 notes="Long invoice spanning several pages")
            else:
                self.digital_pdf(self.invoice())

        # 2. scanned PDFs (20): 4 multi-page
        for i in range(20):
            n = r.randint(35, 50) if i < 4 else None
            self.scanned(self.invoice(n_items=n), "pdf_scanned", levels[i % len(levels)])

        # 3. images: JPG 20, PNG 20, TIFF 15 (3 multi-page TIFF)
        for fmt, count in (("jpg", 20), ("png", 20), ("tiff", 15)):
            for i in range(count):
                multi = fmt == "tiff" and i < 3
                n = r.randint(35, 45) if multi else r.randint(1, 8)
                loc = "homecare" if i % 6 == 0 else None
                self.scanned(self.invoice(loc, n), fmt, levels[i % len(levels)])

        # 4. spreadsheets
        for fmt, plan in (("xlsx", ["form"] * 8 + ["multisheet"] * 7 + ["ledger"] * 5),
                          ("xls", ["form"] * 5 + ["multisheet"] * 5),
                          ("csv", ["ledger"] * 8 + ["form"] * 7)):
            for layout in plan:
                if layout == "ledger" and r.random() < 0.6:
                    invs = [self.invoice() for _ in range(r.randint(3, 6))]
                else:
                    invs = [self.invoice()]
                self.sheet(invs, fmt, layout)

        # 5. multi-invoice bundles
        self.bundle([self.invoice(allow_defect=False) for _ in range(10)])
        self.bundle([self.invoice(allow_defect=False) for _ in range(8)], level="mild")

        # 6. duplicates: the same invoice re-sent as a photo or scan (6)
        originals = [d for d in self.docs if d["format"] == "pdf_digital" and len(d["invoices"]) == 1
                     and d["pages"] == 1 and d["layout"] != "bundle"]
        for d in r.sample(originals, 6):
            inv = self._invoice_from(d)
            dup = inv.clone(inv.invoice_id + "d")
            new = self.scanned(dup, r.choice(["jpg", "png", "pdf_scanned"]), r.choice(["mild", "moderate"]),
                               notes=f"Duplicate of {d['doc_id']}")
            self.add_group("duplicate", [(d, inv), (new, dup)])

        # 7. PDF vs Excel cross-verification (10 pairs: 7 agree, 3 differ)
        changes = [None] * 7 + ["total", "quantity", "date"]
        r.shuffle(changes)
        for ch in changes:
            inv = self.f.make(n_items=r.randint(2, 6))
            pdf = self.digital_pdf(inv, notes="Cross-verification source document")
            tw = self.twin(inv, ch)
            sh = self.sheet([tw], r.choice(["xlsx", "csv", "xls"]), r.choice(["form", "ledger"]),
                            notes=f"Accounting record for {pdf['doc_id']}" + (f"; {ch} differs" if ch else ""))
            self.add_group("cross_check_pdf_excel", [(pdf, inv), (sh, tw)])

        # 8. PDF vs PDF cross-verification (5 pairs: 2 agree, 3 differ)
        for ch in [None, None, "total", "quantity", "date"]:
            inv = self.f.make(n_items=r.randint(2, 6))
            a = self.digital_pdf(inv, template="classic", notes="Supplier copy")
            tw = self.twin(inv, ch)
            b = self.digital_pdf(tw, template=r.choice(["modern", "receipt"]),
                                 notes=f"Internal copy of {a['doc_id']}" + (f"; {ch} differs" if ch else ""))
            self.add_group("cross_check_pdf_pdf", [(a, inv), (b, tw)])

        # 9. corrupted and unreadable files
        self.corrupted()

        # 10. mixed PDFs: digital and scanned pages in the same file
        #     (added after the rest so earlier documents keep their ids)
        self.mixed([self.invoice(n_items=r.randint(40, 50))], {2}, "mild",
                   "One invoice; page 1 digital, page 2 scanned")
        self.mixed([self.invoice(n_items=r.randint(40, 50))], {1}, "moderate",
                   "One invoice; page 1 scanned, later pages digital")
        invs = [self.invoice(allow_defect=False) for _ in range(3)]
        self.mixed(invs, {2}, "mild", "Three invoices; the second is a scan between two digital ones")

        self.write_outputs()
        shutil.rmtree(self.tmp)

    def _invoice_from(self, doc: dict) -> Invoice:
        return self._live[doc["invoices"][0]["invoice_id"]]

    def write_outputs(self):
        for d in self.docs:
            with open(os.path.join(self.labels, f"{d['doc_id']}.json"), "w") as fh:
                json.dump(d, fh, indent=2, ensure_ascii=False)
        with open(os.path.join(self.out, "groups.json"), "w") as fh:
            json.dump(self.groups, fh, indent=2, ensure_ascii=False)
        with open(os.path.join(self.out, "manifest.csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["doc_id", "file", "format", "layout", "degradation", "pages", "split",
                        "expected_status", "n_invoices", "flags", "notes"])
            for d in self.docs:
                flags = sorted({f for i in d["invoices"] for f in i["expected_flags"]})
                w.writerow([d["doc_id"], d["file"], d["format"], d["layout"], d["degradation"],
                            d["pages"], d["split"], d["expected_status"], len(d["invoices"]),
                            ";".join(flags), d["notes"] or ""])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    if os.path.exists(a.out):
        shutil.rmtree(a.out)
    b = Builder(a.out, a.seed)
    b.build()

    c = Counter(d["format"] for d in b.docs)
    n_inv = sum(len(d["invoices"]) for d in b.docs)
    flags = Counter(f for d in b.docs for i in d["invoices"] for f in i["expected_flags"])
    print(f"documents: {len(b.docs)}  invoices: {n_inv}")
    print("by format:", dict(c))
    print("flags:", dict(flags))
    print("groups:", Counter(g["relation"] for g in b.groups))


if __name__ == "__main__":
    main()
