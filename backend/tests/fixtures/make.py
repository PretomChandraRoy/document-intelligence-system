"""Build the test files from known invoices, using the dataset generator.

Every file comes with its ground truth, so tests can check exact values.
"""

from __future__ import annotations

import io
import os
import random
import zipfile
from dataclasses import dataclass

import pymupdf
from PIL import Image

from gen.degrade import SEVERITY, degrade, pdf_to_images, save_images_as_pdf, scan_pdf
from gen.invoice import InvoiceFactory
from gen.pdf_templates import render_bundle, render_pdf
from gen.sheets import render_sheet


@dataclass
class Fixture:
    path: str
    truth: list[dict]

    @property
    def gt(self) -> dict:
        return self.truth[0]


def build(d) -> dict[str, Fixture]:
    d = str(d)
    f = InvoiceFactory(seed=1234)
    rng = random.Random(1234)
    out: dict[str, Fixture] = {}
    p = lambda name: os.path.join(d, name)

    def pdf(name, inv, tpl):
        render_pdf(inv, p(name), tpl)
        out[name] = Fixture(p(name), [inv.ground_truth()])
        return inv

    # digital PDFs, one per layout
    bd = pdf("classic.pdf", f.make("bd", 4), "classic")
    pdf("modern.pdf", f.make("uk", 3), "modern")
    pdf("receipt.pdf", f.make("eu", 3), "receipt")
    pdf("homecare.pdf", f.make("homecare", 3), "homecare")
    pdf("long.pdf", f.make("us", 50), "classic")
    pdf("wrong_total.pdf", f.inject(f.make("us", 3), "wrong_total"), "classic")
    pdf("missing_date.pdf", f.inject(f.make("uk", 2), "missing_invoice_date"), "modern")
    pdf("wrong_line.pdf", f.inject(f.make("us", 3), "wrong_line_amount"), "classic")

    # scans and photos
    src = f.make("us", 3)
    render_pdf(src, p("_src.pdf"), "classic")
    for name, level in (("scan_clean.png", "clean"), ("scan_mild.jpg", "mild"), ("scan_severe.jpg", "severe")):
        img = scan_pdf(p("_src.pdf"), level, rng)[0]
        img.save(p(name), **({"quality": 85} if name.endswith(".jpg") else {}))
        out[name] = Fixture(p(name), [src.ground_truth()])
    clean = pdf_to_images(p("_src.pdf"), 200)[0]
    clean.rotate(3.0, expand=False, fillcolor=255).save(p("scan_rotated.png"))
    out["scan_rotated.png"] = Fixture(p("scan_rotated.png"), [src.ground_truth()])

    two = f.make("bd", 40)
    render_pdf(two, p("_two.pdf"), "modern")
    save_images_as_pdf(scan_pdf(p("_two.pdf"), "mild", rng), p("scanned.pdf"), 170)
    out["scanned.pdf"] = Fixture(p("scanned.pdf"), [two.ground_truth()])
    imgs = scan_pdf(p("_two.pdf"), "clean", rng)
    imgs[0].save(p("multi.tiff"), save_all=True, append_images=imgs[1:], compression="tiff_lzw")
    out["multi.tiff"] = Fixture(p("multi.tiff"), [two.ground_truth()])

    # mixed: page 1 digital, page 2 scanned
    doc = pymupdf.open(p("_two.pdf"))
    mixed = pymupdf.open()
    mixed.insert_pdf(doc, from_page=0, to_page=0)
    page2 = scan_pdf(p("_two.pdf"), "clean", rng)[1]
    page2.convert("RGB").save(p("_p2.jpg"), quality=90)
    pg = mixed.new_page(width=doc[1].rect.width, height=doc[1].rect.height)
    pg.insert_image(pg.rect, filename=p("_p2.jpg"))
    mixed.save(p("mixed.pdf"))
    out["mixed.pdf"] = Fixture(p("mixed.pdf"), [two.ground_truth()])

    # bundle of three invoices
    b = [(f.make("us", 2), "classic"), (f.make("bd", 3), "receipt"), (f.make("homecare", 2), "homecare")]
    render_bundle(b, p("bundle.pdf"))
    out["bundle.pdf"] = Fixture(p("bundle.pdf"), [i.ground_truth() for i, _ in b])

    # spreadsheets
    def sheet(name, invs, fmt, layout):
        render_sheet(invs, p(name), fmt, layout, random.Random(5))
        out[name] = Fixture(p(name), [i.ground_truth() for i in invs])

    sheet("form.xlsx", [f.make("bd", 3)], "xlsx", "form")
    sheet("multisheet.xlsx", [f.make("uk", 4)], "xlsx", "multisheet")
    sheet("ledger.xlsx", [f.make("us", 2), f.make("us", 3), f.make("bd", 1)], "xlsx", "ledger")
    sheet("form.xls", [f.make("us", 2)], "xls", "form")
    sheet("ledger.csv", [f.make("uk", 2), f.make("uk", 2)], "csv", "ledger")
    eu = f.make("eu", 3)
    eu.money_style = "eu"
    sheet("eu.csv", [eu], "csv", "form")

    # duplicate: same invoice as PDF and as a photo
    dup = f.make("bd", 2)
    pdf("dup_a.pdf", dup, "classic")
    img = scan_pdf(p("dup_a.pdf"), "clean", rng)[0]
    img.save(p("dup_b.png"))
    out["dup_b.png"] = Fixture(p("dup_b.png"), [dup.ground_truth()])

    # cross-verification: PDF and its spreadsheet record, total differs
    cv = f.make("us", 3)
    pdf("cross.pdf", cv, "modern")
    rec = cv.clone("rec")
    from decimal import Decimal
    rec.total = rec.total + Decimal("10.00")
    sheet("cross.xlsx", [rec], "xlsx", "form")

    # broken files
    ok = open(out["classic.pdf"].path, "rb").read()
    raw = {
        "truncated.pdf": ok[: len(ok) // 3],
        "random.pdf": random.Random(9).randbytes(4096),
        "empty.png": b"",
        "renamed.xlsx": b"Supplier,Total\nAcme,100\n",
        "garbage.csv": bytes(range(256)) * 8,
        "header_only.csv": b"Invoice No,Invoice Date,Supplier,Total\n",
    }
    jb = io.BytesIO()
    img.convert("RGB").save(jb, "JPEG", quality=85)
    raw["truncated.jpg"] = jb.getvalue()[: len(jb.getvalue()) // 2]
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
    raw["notes.docx"] = zb.getvalue()
    for name, data in raw.items():
        with open(p(name), "wb") as fh:
            fh.write(data)
        out[name] = Fixture(p(name), [])
    e = pymupdf.open(out["classic.pdf"].path)
    e.save(p("encrypted.pdf"), encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o-secret", user_pw="u-secret")
    out["encrypted.pdf"] = Fixture(p("encrypted.pdf"), [])
    return out
